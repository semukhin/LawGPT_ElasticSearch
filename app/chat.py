import openai
import json
import asyncio
import os
import logging
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, APIRouter
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from pathlib import Path
from dotenv import load_dotenv
from typing import Dict, Any
from werkzeug.utils import secure_filename
from app import models, database
from app.models import User, Message, Thread
from app.auth import get_current_user
from app.handlers.web_search import google_search
from app.handlers.gpt_handler import process_docx_with_assistant
from app.handlers.summary_history import create_summary_for_thread
from app.handlers.garant_process import process_garant_request
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app import database
from app.models import User, Message, Thread
from app.auth import get_current_user
from app.handlers.web_search import google_search
from app.handlers.garant_process import process_garant_request
from app.handlers.gpt_request import send_custom_request
import asyncio
import logging



# Load environment variables
load_dotenv()

# OpenAI API credentials
OPENAI_API_KEY="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"
ASSISTANT_ID="asst_jaWku4zA0ufJJuxdG68enKgT"

if not OPENAI_API_KEY or not ASSISTANT_ID:
    raise ValueError("OPENAI_API_KEY or ASSISTANT_ID is missing from environment variables.")

# Initialize OpenAI client
client = openai.OpenAI(api_key=OPENAI_API_KEY)

# FastAPI app instance
app = FastAPI(
    title="OpenAI Assistant API",
    description="API for managing OpenAI assistant threads and messages.",
    version="1.0.0"
)

router = APIRouter()

# File storage
UPLOAD_FOLDER = "uploads"
DOCUMENTS_FOLDER = "processed_documents"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# OAuth2 (Bearer Token) Authentication
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ========================== API ДЛЯ ЧАТА ==========================

router = APIRouter()

# Модель запроса
class ChatRequest(BaseModel):
    query: str


@router.post("/chat/{thread_id}")
async def chat_in_thread(
    thread_id: str,
    query: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    """
    Отправляет сообщение в тред. Если тред не существует, создаёт новый и возвращает его ID.
    """
    user_query = query.get("query")
    if not user_query:
        raise HTTPException(status_code=400, detail="Запрос не должен быть пустым!")

    # Проверяем, существует ли тред
    thread = db.query(Thread).filter_by(id=thread_id, user_id=current_user.id).first()
    thread_created = False  # Флаг, был ли создан новый тред

    # Если треда нет – создаём новый
    if not thread:
        new_thread = client.beta.threads.create()
        thread_id = new_thread.id
        thread_created = True  # Флаг для возврата нового треда

        thread = Thread(id=thread_id, user_id=current_user.id)
        db.add(thread)
        db.commit()

    # Сохраняем сообщение пользователя
    user_message = Message(thread_id=thread_id, role="user", content=user_query)
    db.add(user_message)
    db.commit()

    # Асинхронный поиск Google и ГАРАНТ
    logs = []

    if asyncio.iscoroutinefunction(google_search):
        google_results_task = google_search(user_query, logs)
    else:
        loop = asyncio.get_event_loop()
        google_results_task = loop.run_in_executor(None, google_search, user_query, logs)

    if asyncio.iscoroutinefunction(process_garant_request):
        garant_results_task = process_garant_request(user_query, logs, lambda lvl, msg: logs.append(msg))
    else:
        loop = asyncio.get_event_loop()
        garant_results_task = loop.run_in_executor(None, process_garant_request, user_query, logs, lambda lvl, msg: logs.append(msg))

    google_results, garant_results = await asyncio.gather(google_results_task, garant_results_task)

    # Преобразуем результаты веб-поиска
    google_summaries = [f"{result['summary']} ({result['link']})" for result in google_results]

    logging.info(f"🌐 Найдено {len(google_summaries)} результатов веб-поиска")
    logging.info(f"📄 Результаты ГАРАНТ: {garant_results}")

    # Запрос ассистенту
    assistant_response = send_custom_request(
        user_query=user_query,
        web_links=google_summaries,
        document_summary=garant_results
    )
    logging.info(assistant_response)

    # Сохраняем ответ ассистента
    assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response)
    db.add(assistant_message)
    db.commit()

    response = {"assistant_response": assistant_response}
    
    if thread_created:
        response["new_thread_id"] = thread_id  # Если тред создан, возвращаем его ID

    return response



# @router.post("/chat/{thread_id}")
# async def chat_in_thread(
#     thread_id: str,
#     query: dict,
#     current_user: User = Depends(get_current_user),
#     db: Session = Depends(database.get_db),
#     token: str = Depends(oauth2_scheme)
# ):
#     """
#     Отправляет сообщение в конкретный тред, указанный в URL.
#     """
#     user_query = query.get("query")
#     if not user_query:
#         raise HTTPException(status_code=400, detail="Запрос не должен быть пустым!")


#     # Проверяем, существует ли указанный тред
#     thread = db.query(Thread).filter_by(id=thread_id, user_id=current_user.id).first()
#     if not thread:
#         raise HTTPException(status_code=404, detail="Тред не найден!")


#     # Сохраняем сообщение пользователя в БД
#     user_message = Message(thread_id=thread_id, role="user", content=user_query)
#     db.add(user_message)
#     db.commit()


#     # Отправляем сообщение в OpenAI Assistant
#     client.beta.threads.messages.create(
#         thread_id=thread_id,
#         role="user",
#         content=user_query
#     )


#     # Запускаем ассистента
#     run = client.beta.threads.runs.create(
#         thread_id=thread_id,
#         assistant_id=ASSISTANT_ID
#     )


#     # Ожидаем ответ
#     while True:
#         run_status = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)
#         if run_status.status in ["completed", "failed", "cancelled"]:
#             break
#         await asyncio.sleep(1)


#     # Получаем ответ
#     if run_status.status == "completed":
#         messages = client.beta.threads.messages.list(thread_id=thread_id)
#         latest_message = messages.data[0]
#         assistant_response = latest_message.content[0].text.value

#         assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response)
#         db.add(assistant_message)
#         db.commit()

#         return {"assistant_response": assistant_response}

#     raise HTTPException(status_code=500, detail="Ошибка OpenAI Assistant.")


# ========================== API ДЛЯ ЗАГРУЗКИ ФАЙЛОВ ==========================

@router.post("/upload_file")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    Загружает файл и привязывает его к последнему треду пользователя.
    """
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Поддерживаются только .docx файлы.")

    # Получаем последний тред пользователя
    thread = db.query(Thread).filter_by(user_id=current_user.id).order_by(Thread.created_at.desc()).first()
    if not thread:
        return JSONResponse(status_code=400, content={"error": "Сначала начните чат."})

    # Генерируем безопасное имя файла
    filename = secure_filename(file.filename)
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    # Сохраняем файл
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Записываем в БД
    file_message = Message(thread_id=thread.id, role="user", content=file_path)
    db.add(file_message)
    db.commit()

    return {"message": "Файл загружен", "filename": filename}



# ========================== API ДЛЯ ПОЛУЧЕНИЯ СООБЩЕНИЙ ==========================

@router.get("/messages/{thread_id}")
async def get_messages(thread_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(database.get_db)):
    """
    Получает все сообщения из указанного треда.
    """
    messages = db.query(Message).filter_by(thread_id=thread_id).order_by(Message.created_at).all()
    return {"messages": [{"role": msg.role, "content": msg.content, "created_at": msg.created_at} for msg in messages]}



# ========================== API ДЛЯ СОЗДАНИЯ ТРЕДОВ ==========================

@router.post("/create_thread")
async def create_new_thread(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(database.get_db)
):
    """
    Создаёт новый OpenAI thread, сохраняет его в БД и возвращает его ID.
    """
    # Создаём тред в OpenAI
    thread = client.beta.threads.create()
    thread_id = thread.id

    # Сохраняем тред в БД
    new_thread = Thread(id=thread_id, user_id=current_user.id)
    db.add(new_thread)
    db.commit()

    return {"message": "Thread created successfully.", "thread_id": thread_id}

# ========================== ПОДКЛЮЧЕНИЕ РОУТЕРА ==========================
app.include_router(router)
