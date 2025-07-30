import re
from fastapi import FastAPI, HTTPException, Request, Response, status, Depends
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, EmailStr, field_validator
from datetime import datetime, date
from typing import List
import aiosqlite
import uvicorn

app = FastAPI()

SQLITE_DB_NAME = "library.db"

async def establish_db_connection():
    async with aiosqlite.connect(SQLITE_DB_NAME) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn
        
async def initialize_database():
    async with aiosqlite.connect(SQLITE_DB_NAME) as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                year INTEGER,
                quantity INTEGER
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                location TEXT NOT NULL
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                phone TEXT NOT NULL
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS rsvps (
                user_id INTEGER,
                event_id INTEGER,
                PRIMARY KEY (user_id, event_id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (event_id) REFERENCES events(id)
            );
        """)
        await conn.commit()
        
app = FastAPI(on_startup=[initialize_database])

@app.exception_handler(RequestValidationError)
async def handle_validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "message": "Некорректные данные",
            "errors": [
                {"field": ".".join(map(str, err["loc"])), "message": err["msg"]}
                for err in exc.errors()
            ]
        }
    )

class BookCreation(BaseModel):
    title: str
    author: str
    year: int
    quantity: int

class BookDetails(BookCreation):
    id: int

@app.get("/books/", response_model=List[BookDetails])
async def retrieve_all_books(connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT * FROM books") as cursor:
        rows = await cursor.fetchall()
        return [BookDetails(**row) for row in rows]
    
@app.get("/books/{book_id}", response_model=BookDetails)
async def retrieve_single_book(book_id: int, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT * FROM books WHERE id = ?", (book_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, detail="Публикация не обнаружена.")
        return BookDetails(**row)

@app.post("/books/", response_model=BookDetails, status_code=201)
async def create_new_book(data: BookCreation, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT * FROM books WHERE title = ? AND author = ? AND year = ?", (data.title, data.author, data.year)) as cursor:
        exists = await cursor.fetchone()
        if exists:
            raise HTTPException(400, detail="Данная публикация уже добавлена.")
    async with connection.cursor() as cursor:
        await cursor.execute(
            "INSERT INTO books (title, author, year, quantity) VALUES (?, ?, ?, ?) RETURNING *;",
            (data.title, data.author, data.year, data.quantity),
        )
        row = await cursor.fetchone()
        await connection.commit()
        return BookDetails(**row)

class UserSignup(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    phone: str
    
    @field_validator("first_name", "last_name")
    @classmethod
    def check_name_format(cls, v):
        if len(v) < 2 or not v.isalpha():
            raise ValueError("Имя должно содержать минимум 2 буквы")
        return v
    
    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v):
        if len(v) < 8 or not re.search(r"[A-Z]", v) or not re.search(r"[a-z]", v) or not re.search(r"\d", v) or not re.search(r"[!@#$%^&*()_+=\-]", v):
            raise ValueError("Пароль должен содержать минимум 8 символов, включая заглавные и строчные буквы, цифры и специальные символы")
        return v
    
    @field_validator("phone")
    @classmethod
    def check_phone_format(cls, v):
        if not re.fullmatch(r"\+?\d{10,15}", v):
            raise ValueError("Номер телефона должен содержать от 10 до 15 цифр")
        return v

@app.post("/register/", status_code=201)
async def create_user_account(data: UserSignup, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    try:
        await connection.execute("INSERT INTO users (first_name, last_name, email, password, phone) VALUES (?, ?, ?, ?, ?)", (data.first_name, data.last_name, data.email, data.password, data.phone))
        await connection.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(400, detail="Данный email уже используется.")
    return {"status": "успешно"}

class EventCreation(BaseModel):
    title: str
    date: date
    location: str

class EventDetails(EventCreation):
    id: int

@app.post("/events/", response_model=EventDetails, status_code=201)
async def add_new_event(data: EventCreation, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.cursor() as cursor:
        await cursor.execute("INSERT INTO events (title, date, location) VALUES (?, ?, ?) RETURNING *;", (data.title, data.date.isoformat(), data.location),)
        row = await cursor.fetchone()
        await connection.commit()
        return EventDetails(**row)

@app.get("/events/", response_model=List[EventDetails])
async def fetch_all_events(connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT * FROM events") as cursor:
        rows = await cursor.fetchall()
        if not rows:
            return Response(status_code=204)
        return [EventDetails(**row) for row in rows]

@app.get("/events/{event_id}", response_model=EventDetails)
async def fetch_single_event(event_id: int, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT * FROM events WHERE id = ?", (event_id,)) as cursor:
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, detail="Мероприятие не обнаружено.")
        return EventDetails(**row)

@app.put("/events/{event_id}", response_model=EventDetails)
async def modify_event(event_id: int, data: EventCreation, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, detail="Мероприятие не обнаружено.")
        await cursor.execute(
            "UPDATE events SET title = ?, date = ?, location = ? WHERE id = ?",
            (data.title, data.date.isoformat(), data.location, event_id)
        )
        await connection.commit()
        return EventDetails(id=event_id, **data.model_dump())

@app.delete("/events/{event_id}", status_code=200)
async def remove_event(event_id: int, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        if not await cursor.fetchone():
            raise HTTPException(404, detail="Мероприятие не обнаружено.")
        await cursor.execute("DELETE FROM events WHERE id = ?", (event_id,))
        await connection.commit()
        return {"status": "удалено успешно"}

@app.patch("/events/{event_id}/reschedule", response_model=EventDetails)
async def change_event_date(event_id: int, new_date: date, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    if new_date < date.today():
        raise HTTPException(400, detail="Дата не может быть в прошедшем времени.")
    async with connection.cursor() as cursor:
        await cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
        event = await cursor.fetchone()
        if not event:
            raise HTTPException(404, detail="Мероприятие не обнаружено.")
        await cursor.execute("UPDATE events SET date = ? WHERE id = ?", (new_date.isoformat(), event_id))
        await connection.commit()
        return EventDetails(id=event_id, title=event["title"], date=new_date, location=event["location"])

@app.post("/events/{event_id}/rsvp", status_code=201)
async def confirm_attendance(event_id: int, email: EmailStr, connection: aiosqlite.Connection = Depends(establish_db_connection)):
    async with connection.execute("SELECT id FROM users WHERE email = ?", (email,)) as cursor:
        user = await cursor.fetchone()
        if not user:
            raise HTTPException(404, detail="Участник не найден.")
    async with connection.execute("SELECT id FROM events WHERE id = ?", (event_id,)) as cursor:
        event = await cursor.fetchone()
        if not event:
            raise HTTPException(404, detail="Мероприятие не обнаружено.")
    try:
        await connection.execute("INSERT INTO rsvps (user_id, event_id) VALUES (?, ?)", (user["id"], event_id))
        await connection.commit()
    except aiosqlite.IntegrityError:
        raise HTTPException(400, detail="Вы уже подтвердили участие в данном мероприятии.")
    return {"status": "Участие подтверждено успешно"}

if __name__ == '__main__':
    uvicorn.run("json_answer:app", reload=True)