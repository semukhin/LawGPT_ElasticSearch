import openai
import os
import re
import logging
from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, APIRouter
from fastapi.responses import JSONResponse, FileResponse
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from dotenv import load_dotenv
from typing import Dict, Any
from werkzeug.utils import secure_filename
from app.database import get_db
from app.models import User, Message, Thread
from app.auth import get_current_user
from app.handlers.web_search import google_search
from app.handlers.garant_process import process_garant_request
from app.handlers.gpt_request import send_custom_request
from app.handlers.filter_gpt import send_message_to_assistant
from app.handlers.filter_gpt import should_search_external
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.auth import get_current_user
import asyncio
import inspect
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
from app.utils import measure_time


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


def remove_source_references(text: str) -> str:
    """Удаляет ссылки вида """
    return re.sub(r'【\d+:\d+†source】', '', text).strip()


# ========================== API ДЛЯ ЧАТА ==========================

router = APIRouter()

# Модель запроса
class ChatRequest(BaseModel):
    query: str

router = APIRouter()

from app.handlers.filter_gpt import send_message_to_assistant


@measure_time
async def is_legal_query_gpt(query: str) -> bool:
    """Отправляет запрос в фильтр-ассистент и получает True/False."""
    try:
        classification_prompt = f"Этот запрос юридический? Ответь только 'true' или 'false'.\nЗапрос: {query}"
        
        response = await send_message_to_assistant(classification_prompt)  # Добавляем await
        response = response.strip().lower()

        logging.info(f"📌 OpenAI GPT-Классификация запроса: {query}")
        logging.info(f"🔍 Ответ GPT: {response}")

        if response == "true":
            return True
        elif response == "false":
            return False
        else:
            logging.warning(f"⚠️ Непредвиденный ответ от ассистента: {response}")
            return False  # Безопасное значение по умолчанию

    except Exception as e:
        logging.error(f"❌ Ошибка при проверке юридической тематики через GPT: {e}")
        return False  # Если ошибка, считаем запрос неюридическим



@measure_time
@router.post("/chat/{thread_id}")
async def chat_in_thread(
    thread_id: str,
    query: dict,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
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

    if not thread:
        new_thread = client.beta.threads.create()
        thread_id = new_thread.id
        thread_created = True

        thread = Thread(id=thread_id, user_id=current_user.id)
        db.add(thread)
        db.commit()

    # Получаем все предыдущие сообщения
    previous_messages = db.query(Message).filter_by(thread_id=thread_id).all()

    # Проверяем, есть ли хотя бы одно юридическое сообщение
    has_legal_context = False
    for msg in previous_messages:
        if msg.role == "user" and await is_legal_query_gpt(msg.content):
            has_legal_context = True
            break  # Достаточно одного юридического сообщения

    # Проверяем, является ли текущий запрос юридическим
    is_legal = await is_legal_query_gpt(user_query)

    logging.info(f"📌 Запрос классифицирован как {'юридический' if is_legal else 'НЕ юридический'}: {user_query}")

    # Проверяем, нужно ли выполнять поиск в Гаранте и интернете
    should_search = await should_search_external(user_query)

    if not has_legal_context and not is_legal:
        assistant_response = "Привет! Я юридический ассистент. Если у вас есть юридический вопрос, уточните, пожалуйста. Например, 'Как расторгнуть договор?'"
        logging.info(f"👋 НЕ юридический запрос. Ответ: {assistant_response}")

        user_message = Message(thread_id=thread_id, role="user", content=user_query)
        db.add(user_message)
        db.commit()

        assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response)
        db.add(assistant_message)
        db.commit()

        response = {"assistant_response": assistant_response}
        if thread_created:
            response["new_thread_id"] = thread_id  # Если тред создан, возвращаем его ID
        return response

    # Если поиск не требуется, просто генерируем ответ
    if not should_search:
        assistant_response = send_custom_request(user_query=user_query)
        logging.info(f"🧠 Ответ ассистента без поиска: {assistant_response}")

        user_message = Message(thread_id=thread_id, role="user", content=user_query)
        db.add(user_message)

        assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response)
        db.add(assistant_message)

        db.commit()

        response = {"assistant_response": assistant_response}
        if thread_created:
            response["new_thread_id"] = thread_id  # Если тред создан, возвращаем его ID
        return response

    # Если поиск необходим, выполняем его
    logs = []
    
    loop = asyncio.get_event_loop()
    if asyncio.iscoroutinefunction(google_search):
        google_results_task = asyncio.create_task(google_search(user_query, logs))
    else:
        google_results_task = loop.run_in_executor(None, google_search, user_query, logs)

    if asyncio.iscoroutinefunction(process_garant_request):
        garant_results_task = asyncio.create_task(process_garant_request(user_query, logs, lambda lvl, msg: logs.append(msg)))
    else:
        garant_results_task = loop.run_in_executor(None, process_garant_request, user_query, logs, lambda lvl, msg: logs.append(msg))

    google_results, garant_results = await asyncio.gather(google_results_task, garant_results_task)

    google_summaries = [f"{result['summary']} ({result['link']})" for result in google_results]

    logging.info(f"🌐 Найдено {len(google_summaries)} результатов веб-поиска")
    logging.info(f"📄 Результаты ГАРАНТ: {garant_results}")

    assistant_response = send_custom_request(
        user_query=user_query,
        web_links=google_summaries,
        document_summary=garant_results
    )

    # Очистка ответа от ссылок на источники
    assistant_response = remove_source_references(assistant_response)
    logging.info(f"🧠 Ответ ассистента: {assistant_response}")

    user_message = Message(thread_id=thread_id, role="user", content=user_query)
    db.add(user_message)

    assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response)
    db.add(assistant_message)

    db.commit()

    response = {"assistant_response": assistant_response}
    
    if thread_created:
        response["new_thread_id"] = thread_id  # Если тред создан, возвращаем его ID

    return response




# ========================== API ДЛЯ ЗАГРУЗКИ ФАЙЛОВ ==========================
@measure_time
@router.post("/upload_file")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
@measure_time
@router.get("/messages/{thread_id}")
async def get_messages(thread_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Получает все сообщения из указанного треда.
    """
    messages = db.query(Message).filter_by(thread_id=thread_id).order_by(Message.created_at).all()
    return {"messages": [{"role": msg.role, "content": msg.content, "created_at": msg.created_at} for msg in messages]}



# ========================== API ДЛЯ СОЗДАНИЯ ТРЕДОВ ==========================
@measure_time
@router.post("/create_thread")
async def create_new_thread(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
