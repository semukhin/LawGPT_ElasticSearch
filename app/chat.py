import openai
import os
import re
import logging
from fastapi import Request, UploadFile, File, Form, HTTPException, FastAPI
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
from app.handlers.user_doc_request import extract_text_from_docx
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
DOCX_FOLDER = "/Users/admin/Documents/LAWGPT/LawGPT_FastAPI_version/LawGPT_FastAPI_version/documents_docx"
os.makedirs(DOCX_FOLDER, exist_ok=True)  # Убеждаемся, что папка существует

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
    request: Request,
    thread_id: str,
    query: str = Form(...),
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Отправляет сообщение в тред. Если прикреплен .docx, извлекает из него текст и добавляет к запросу.
    Если документ есть – отключает поиск в Гаранте и веб-сёрче.
    """
    if not query:
        raise HTTPException(status_code=400, detail="Запрос не должен быть пустым!")

    # Проверяем, существует ли тред
    thread = db.query(Thread).filter_by(id=thread_id, user_id=current_user.id).first()
    thread_created = False

    if not thread:
        new_thread = client.beta.threads.create()
        thread_id = new_thread.id
        thread_created = True

        thread = Thread(id=thread_id, user_id=current_user.id)
        db.add(thread)
        db.commit()

    # Получаем все предыдущие сообщения
    previous_messages = db.query(Message).filter_by(thread_id=thread_id).all()

    # ✅ ВЕРНУЛ ПРОВЕРКУ НА "ЮРИДИЧЕСКИЙ ЗАПРОС"
    has_legal_context = False
    for msg in previous_messages:
        if msg.role == "user" and await is_legal_query_gpt(msg.content):
            has_legal_context = True
            break  # Достаточно одного юридического сообщения

    # Проверяем, является ли текущий запрос юридическим
    is_legal = await is_legal_query_gpt(query)

    logging.info(f"📌 Запрос классифицирован как {'юридический' if is_legal else 'НЕ юридический'}: {query}")

    # Проверяем, нужно ли выполнять поиск в Гаранте и интернете
    should_search = await should_search_external(query)

    # Обработка прикрепленного файла
    extracted_text = ""
    has_document = False  

    if file and file.filename.endswith(".docx"):
        has_document = True
        file_path = os.path.join(UPLOAD_FOLDER, file.filename)

        # Убедимся, что папка существует
        os.makedirs(UPLOAD_FOLDER, exist_ok=True)

        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())

        logging.info(f"📂 Файл сохранён: {file_path}")

        # Извлекаем текст из документа
        extracted_text = extract_text_from_docx(file_path)
        logging.info(f"📜 Извлечённый текст из документа:\n{extracted_text}")

    # Формируем финальный запрос для ассистента
    user_query = query
    if extracted_text:
        user_query = f"Пользователь прикрепил документ. Его текст:\n{extracted_text}\n\nВопрос: {query}"

    logging.info(f"📝 Итоговый запрос ассистенту:\n{user_query}")

    # ✅ ЕСЛИ ЗАПРОС НЕ ЮРИДИЧЕСКИЙ И НЕТ ПРЕДЫДУЩЕГО ЮРИДИЧЕСКОГО КОНТЕКСТА
    if not has_legal_context and not is_legal:
        assistant_response = "Привет! Я юридический ассистент. Если у вас есть юридический вопрос, уточните, пожалуйста. Например, 'Как расторгнуть договор?'"
        logging.info(f"👋 НЕ юридический запрос. Ответ: {assistant_response}")

        db.add(Message(thread_id=thread_id, role="user", content=query))
        db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
        db.commit()

        return {
            "assistant_response": assistant_response,
            "new_thread_id": thread_id if thread_created else None,
        }

    # ✅ ЕСЛИ ЕСТЬ ДОКУМЕНТ – НЕ ЗАПУСКАЕМ ГАРАНТ И ВЕБ-СЁРЧ
    if has_document:
        assistant_response = send_custom_request(user_query=user_query, web_links=None, document_summary=None)
        logging.info(f"🤖 Ответ ассистента (без поиска): {assistant_response}")

        db.add(Message(thread_id=thread_id, role="user", content=query))
        db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
        db.commit()

        return {
            "assistant_response": assistant_response,
            "new_thread_id": thread_id if thread_created else None,
        }

    # === Если документа нет, включаем Гарант и веб-сёрч ===
    logs = []

    loop = asyncio.get_event_loop()

    # Проверяем, является ли google_search асинхронной функцией
    if asyncio.iscoroutinefunction(google_search):
        google_results_task = asyncio.create_task(google_search(user_query, logs))
    else:
        google_results_task = loop.run_in_executor(None, google_search, user_query, logs)

    # Проверяем, является ли process_garant_request асинхронной функцией
    if asyncio.iscoroutinefunction(process_garant_request):
        garant_results_task = asyncio.create_task(process_garant_request(user_query, logs, lambda lvl, msg: logs.append(msg)))
    else:
        garant_results_task = loop.run_in_executor(None, process_garant_request, user_query, logs, lambda lvl, msg: logs.append(msg))

    # Ожидаем результаты обеих функций
    google_results, garant_results = await asyncio.gather(google_results_task, garant_results_task)

    # Формируем список результатов веб-поиска
    google_summaries = [f"{result['summary']} ({result['link']})" for result in google_results]

    logging.info(f"🌐 Найдено {len(google_summaries)} результатов веб-поиска")
    logging.info(f"📄 Результаты ГАРАНТ: {garant_results}")


    assistant_response = send_custom_request(
        user_query=user_query,
        web_links=google_summaries if google_summaries else None,
        document_summary=garant_results if garant_results else None
    )

    assistant_response = remove_source_references(assistant_response)
    logging.info(f"🧠 Ответ ассистента: {assistant_response}")

    db.add(Message(thread_id=thread_id, role="user", content=query))
    db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
    db.commit()

    # === Гарантированно добавляем document_url ===
    document_url = None
    if isinstance(garant_results, dict) and "document_url" in garant_results:
        raw_url = garant_results["document_url"]
        logging.info(f"✅ Найдена оригинальная ссылка: {raw_url}")

        # Формируем правильный URL с текущим хостом и портом
        base_url = str(request.base_url).rstrip("/")
        document_filename = raw_url.split("/")[-1]
        document_url = f"{base_url}/download/{document_filename}"

        logging.info(f"🔗 Финальная ссылка на скачивание: {document_url}")
    else:
        logging.warning(f"⚠️ Не найден document_url в garant_results: {garant_results}")

    response = {"assistant_response": assistant_response}

    if document_url:
        response["document_download_url"] = document_url

    if thread_created:
        response["new_thread_id"] = thread_id  

    logging.info(f"📨 Финальный JSON-ответ: {response}")

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


@router.get("/download/{filename}")
async def download_document(filename: str):
    """
    Позволяет скачивать юридические документы .docx.
    """
    file_path = os.path.join(DOCX_FOLDER, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Документ не найден")

    return FileResponse(file_path, filename=filename, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ========================== API ДЛЯ ПОЛУЧЕНИЯ СООБЩЕНИЙ ==========================
@measure_time
@router.get("/messages/{thread_id}")
async def get_messages(thread_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Получает все сообщения из указанного треда.
    """
    messages = db.query(Message).filter_by(thread_id=thread_id).order_by(Message.created_at).all()
    return {"messages": [{"role": msg.role, "content": msg.content, "created_at": msg.created_at} for msg in messages]}


@router.get("/chat/threads")
async def get_threads(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Получает все треды текущего пользователя.
    """
    threads = db.query(Thread).filter_by(user_id=current_user.id).order_by(Thread.created_at).all()
    return {"threads": [{"id": thread.id, "created_at": thread.created_at} for thread in threads]}

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
