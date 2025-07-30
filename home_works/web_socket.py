import secrets
import sqlite3
import html
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Path, HTTPException, status, Depends
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient
import uvicorn

app = FastAPI()

DATABASE = "messaging.db"

def initialize_database():
    with sqlite3.connect(DATABASE) as conn:
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            token TEXT UNIQUE NOT NULL
        )""")
        conn.commit()

def verify_access_token(token: str):
    with sqlite3.connect(DATABASE) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT token FROM users WHERE token = ?", (token,))
        row = cur.fetchone()
        return row["token"] if row else None

class WebSocketManager:
    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}

    async def establish_connection(self, websocket: WebSocket, username: str, access_token: str):
        await websocket.accept()
        self.active_connections[access_token] = websocket
        await self.send_broadcast_message(f"{username} подключился к чату", exclude={access_token})

    def terminate_connection(self, access_token: str):
        self.active_connections.pop(access_token, None)

    async def send_private_message(self, message: str, access_token: str):
        if access_token in self.active_connections:
            await self.active_connections[access_token].send_text(message)

    async def send_broadcast_message(self, message: str, exclude: set = None):
        for token, websocket in self.active_connections.items():
            if exclude and token in exclude:
                continue
            await websocket.send_text(message)

connection_manager = WebSocketManager()
initialize_database()

@app.post("/signup/{name}")
async def create_user_account(name: str = Path(min_length=2, max_length=30)):
    access_token = secrets.token_urlsafe(32)[:32]
    with sqlite3.connect(DATABASE) as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM users WHERE name = ?", (name,))
        if cur.fetchone():
            raise HTTPException(400, "Пользователь уже зарегистрирован")
        cur.execute("INSERT INTO users (name, token) VALUES (?, ?)", (name, access_token))
        conn.commit()
    return {"message": "Аккаунт создан успешно", "token": access_token}

@app.get("/")
async def home_page():
    return HTMLResponse("""
    <h2>Система мгновенных сообщений</h2>
    <p>Для создания аккаунта: <code>/signup/yourname</code></p>
    <p>Для подключения WebSocket: <code>ws://127.0.0.1:8000/connect/yourname/token</code></p>
    """)

@app.websocket("/connect/{name}/{token}")
async def handle_websocket_connection(websocket: WebSocket, name: str, token: str):
    if verify_access_token(token) != token:
        await websocket.close(code=1008)
        return
    
    await connection_manager.establish_connection(websocket, name, token)
    try:
        while True:
            data = await websocket.receive_json()
            recipient = data.get("to")
            content = html.escape(data.get("message", "")[:500])
            if not content:
                continue
            
            if recipient:
                with sqlite3.connect(DATABASE) as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT token FROM users WHERE name = ?", (recipient,))
                    row = cur.fetchone()
                    if row and row[0] in connection_manager.active_connections:
                        await connection_manager.send_private_message(f"{name} >>> {content}", row[0])
                        await connection_manager.send_private_message(f"Вы >>> {content}", token)
                    else:
                        await connection_manager.send_private_message(f"Пользователь {recipient} не в сети.", token)
            else:
                await connection_manager.send_broadcast_message(f"{name} >>> {content}", exclude={token})
    except WebSocketDisconnect:
        connection_manager.terminate_connection(token)
        await connection_manager.send_broadcast_message(f"{name} покинул чат")

client = TestClient(app)

def test_user_registration_and_token():
    username = "test-user"
    response = client.post(f"/signup/{username}")
    assert response.status_code == 200
    user_token = response.json()["token"]
    assert len(user_token) == 32
    assert verify_access_token(user_token) == user_token

@app.get("/messenger")
async def get_messenger_interface():
    return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
    <title>Система мгновенных сообщений</title>
    <style>
        body { font-family: sans-serif; background: #f4f4f4; margin: 0; padding: 1em; }
        #messages { height: 300px; overflow-y: auto; border: 1px solid #ccc; background: white; padding: 1em; margin-bottom: 1em; }
        input, button { padding: 0.5em; font-size: 1em; }
        .msg { margin: 0.25em 0; }
    </style>
</head>
<body>
    <h2>Система мгновенных сообщений</h2>
    <div>
        <input id="name" placeholder="Ваше имя">
        <button onclick="createAccount()">Создать аккаунт</button>
    </div>
    <div>
        <input id="token" placeholder="Токен доступа">
        <button onclick="establishConnection()">Подключиться</button>
    </div>
    <div id="messages"></div>
    <input id="to" placeholder="Получатель (необязательно)">
    <input id="message" placeholder="Сообщение">
    <button onclick="sendMessage()">Отправить</button>
    
    <script>
        let websocket;
        
        function createAccount() {
            const username = document.getElementById("name").value;
            const endpoint = "/signup/" + encodeURIComponent(username);
            fetch(endpoint, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
            })
                .then((response) => response.json())
                .then((data) => alert("Ваш токен доступа: " + data.token));
        }
        
        function establishConnection() {
            const username = document.getElementById("name").value;
            const accessToken = document.getElementById("token").value;
            websocket = new WebSocket(`ws://127.0.0.1:8000/connect/${username}/${accessToken}`);
            websocket.onmessage = event => {
                const messageElement = document.createElement("div");
                messageElement.textContent = event.data;
                messageElement.className = "msg";
                document.getElementById("messages").appendChild(messageElement);
            };
            websocket.onclose = () => alert("Соединение разорвано");
        }
        
        function sendMessage() {
            const recipient = document.getElementById("to").value;
            const messageContent = document.getElementById("message").value;
            if (websocket && websocket.readyState === WebSocket.OPEN) {
                websocket.send(JSON.stringify({ to: recipient || null, message: messageContent }));
                document.getElementById("message").value = "";
            }
        }
    </script>
</body>
</html>""")

if __name__ == "__main__":
    uvicorn.run("web_socket:app", host="127.0.0.1", port=8000, reload=True)