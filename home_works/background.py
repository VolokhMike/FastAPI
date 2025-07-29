import asyncio
import pathlib
import random
import time
import datetime
import aiofiles
import httpx
import uvicorn
import yagmail
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from PIL import Image
from io import BytesIO

module_path = pathlib.Path(__file__).parent

USER = "your_email_address"
PASSWORD = "your_password"
yag = yagmail.SMTP(user=USER, password=PASSWORD)

app = FastAPI(title="Notification Service")

class Customer(BaseModel):
    name: str = Field(examples=["Alex"])
    email: EmailStr = Field(examples=["alex@company.com"])
    phone: str = Field(examples=["+15551234567"])

class MailRequest(BaseModel):
    email: EmailStr
    subject: str
    content: str

customers_storage: list[Customer] = []
job_queue = asyncio.Queue()

async def dispatch_notification(recipient: str, title: str, message: str) -> None:
    yag.send(to=recipient, subject=title, contents=message)
    print(f"Уведомление доставлено получателю {recipient}")

async def record_activity_log(user_email: str, operation: str) -> None:
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{timestamp} | {operation.upper()} | {user_email}\n"
    async with aiofiles.open(module_path / "activity.txt", "a", encoding="utf-8") as f:
        await f.write(entry)
    print(f"Активность зафиксирована {entry.strip()}")

async def perform_external_request() -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get("https://httpbin.org/delay/3", timeout=10)
        print(f"Ответ от внешнего сервиса {response.json()}")

async def blocking_operation(duration: int) -> None:
    time.sleep(duration)
    print(f"Блокирующая операция завершена за {duration} секунд")

async def save_customer_data(full_name: str, email_addr: str, phone_num: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get("https://jsonplaceholder.typicode.com/users/")
    async with aiofiles.open(module_path / "customers.txt", "w", encoding="utf-8") as fp:
        for customer in response.json():
            await fp.write(
                f"name = {customer['name']} | email = {customer['email']} | phone = {customer['phone']}\n\n"
            )
        await fp.write(f"name = {full_name} | email = {email_addr} | phone = {phone_num}\n\n")
    print("Данные клиентов сохранены в файл")

async def fetch_remote_file(resource_url: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(resource_url)
    async with aiofiles.open(module_path / resource_url.split("/")[-1], "wb") as fp:
        await fp.write(response.content)
    print(f"Ресурс '{resource_url}' успешно загружен")

async def process_image_from_web(image_url: str) -> None:
    async with httpx.AsyncClient() as client:
        response = await client.get(image_url)
    picture = Image.open(BytesIO(response.content))
    picture = picture.resize((300, 300))
    output_path = module_path / "processed_image.jpg"
    picture.save(output_path)
    print(f"Изображение обработано и сохранено как {output_path}")

async def execute_job_queue():
    while True:
        job = await job_queue.get()
        try:
            await job
        except Exception as e:
            print(f"Ошибка при выполнении задания из очереди {e}")
        else:
            job_queue.task_done()
            print("Фоновое задание выполнено успешно")
        if job_queue.empty():
            print("Очередь заданий пуста")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(execute_job_queue())

@app.post("/signup", status_code=status.HTTP_201_CREATED, response_model=Customer)
async def create_account(customer_info: Customer, bg_tasks: BackgroundTasks):
    if customer_info.email in {c.email for c in customers_storage}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Клиент уже зарегистрирован")
    customers_storage.append(customer_info)
    bg_tasks.add_task(perform_external_request)
    bg_tasks.add_task(save_customer_data, customer_info.name, customer_info.email, customer_info.phone)
    bg_tasks.add_task(dispatch_notification, customer_info.email, "Добро пожаловать", f"Здравствуйте, {customer_info.name}!")
    bg_tasks.add_task(blocking_operation, 5)
    bg_tasks.add_task(record_activity_log, customer_info.email, "создание аккаунта")
    print("Регистрация добавлена в очередь обработки")
    return customer_info

@app.post("/notify/", status_code=status.HTTP_202_ACCEPTED)
async def send_notification(request: MailRequest, bg_tasks: BackgroundTasks):
    bg_tasks.add_task(dispatch_notification, request.email, request.subject, request.content)
    bg_tasks.add_task(record_activity_log, request.email, "отправка уведомления")
    return {"message": f"Уведомление для {request.email} поставлено в очередь"}

@app.get("/fetch/", status_code=status.HTTP_202_ACCEPTED)
async def retrieve_resource(resource_url: str, bg_tasks: BackgroundTasks):
    bg_tasks.add_task(fetch_remote_file, resource_url=resource_url)
    return {"success": "Ресурс будет загружен в фоновом режиме"}

@app.post("/schedule-job/", status_code=status.HTTP_202_ACCEPTED)
async def schedule_background_job(task_name: str):
    wait_time = random.randint(3, 10)
    async def execute():
        print(f"Задание '{task_name}' с ожиданием {wait_time} секунд запущено.")
        await asyncio.sleep(wait_time)
        print(f"Задание '{task_name}' завершено успешно.")
    await job_queue.put(execute())
    return {"message": f"Задание '{task_name}' запланировано"}

if __name__ == "__main__":
    uvicorn.run("main:app", reload=True)