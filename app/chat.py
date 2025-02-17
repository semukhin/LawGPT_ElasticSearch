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
from app.models import User, Message, Thread, Document
from app.auth import get_current_user
from app.handlers.web_search import google_search
from app.handlers.garant_process import process_garant_request
from app.handlers.gpt_request import send_custom_request
from app.handlers.filter_gpt import send_message_to_assistant, should_search_external
from app.handlers.user_doc_request import extract_text_from_docx, extract_text_from_pdf, extract_text_from_any_document
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.auth import get_current_user
import asyncio
import inspect
from fastapi import APIRouter, Depends, HTTPException
from app.auth import get_current_user
from app.utils import measure_time
from datetime import datetime
from transliterate import translit
from pathlib import Path
import aiofiles



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
DOCX_FOLDER = "/home/semukhin/Documents/GitHub/LawGPT_FastAPI_version/LawGPT_FastAPI_version/documents_docx"
os.makedirs(DOCX_FOLDER, exist_ok=True) 
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


# Константы
os.makedirs(UPLOAD_FOLDER, exist_ok=True)



@measure_time
async def is_legal_query_gpt(query: str) -> bool:
    """
    Запрашивает у фильтр-ассистента: является ли запрос юридическим?
    Возвращает True/False.
    """
    try:
        classification_prompt = (
            "Этот запрос юридический? Ответь только 'true' или 'false'.\n"
            f"Запрос: {query}"
        )
        # Используем send_message_to_assistant (функция из filter_gpt)
        response = await send_message_to_assistant(classification_prompt)
        response = response.strip().lower()

        logging.info(f"📌 OpenAI GPT-Классификация запроса: {query}")
        logging.info(f"🔍 Ответ GPT: {response}")

        if response == "true":
            return True
        elif response == "false":
            return False
        else:
            logging.warning(f"⚠️ Непредвиденный ответ от ассистента: {response}")
            return False  # Безопасное значение
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке юридической тематики: {e}")
        return False


# Функция обработки загруженных файлов
async def process_uploaded_file(file: UploadFile):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_filename = file.filename.replace(" ", "_")
    filename_no_ext, file_extension = os.path.splitext(original_filename)
    transliterated_filename = translit(filename_no_ext, 'ru', reversed=True)

    new_filename = f"{timestamp}_{transliterated_filename}{file_extension}"
    file_path = os.path.join(UPLOAD_FOLDER, new_filename)

    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    logging.info(f"📁 Файл сохранён: {file_path}")

    extracted_text = None
    if file_extension.lower() == ".docx":
        extracted_text = extract_text_from_docx(file_path)
    elif file_extension.lower() == ".pdf":
        extracted_text = extract_text_from_pdf(file_path)

    return file_path, extracted_text



# ========================== Основная точка входа: ЧАТ ==========================
@measure_time
@router.post("/chat/{thread_id}")
async def chat_in_thread(
    request: Request,
    thread_id: str,
    query: str = Form(None),
    file: UploadFile = File(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Чат с ассистентом:
    1. Если пользователь прикрепил файл (DOC/PDF) → извлекаем текст (OCR/parsing), передаём ассистенту.
    2. Если запрос не юридический → отправляем напрямую (без поиска).
    3. Если юридический запрос без файла → ищем в Гаранте, интернете и т.д.
    """

    # 0. Проверяем, чтобы был хотя бы текст или файл
    if not query and not file:
        raise HTTPException(status_code=400, detail="Запрос должен содержать текст или файл")

    # 1. Ищем (или создаём) тред
    thread = db.query(Thread).filter_by(id=thread_id, user_id=current_user.id).first()
    if not thread:
        new_thread = client.beta.threads.create()
        thread_id = new_thread.id
        thread = Thread(id=thread_id, user_id=current_user.id)
        db.add(thread)
        db.commit()

    # 2. (Опционально) получаем последнее сообщение пользователя в этом треде
    last_message = (
        db.query(Message)
        .filter_by(thread_id=thread_id, role="user")
        .order_by(Message.created_at.desc())
        .first()
    )

    extracted_text = None  # Сюда поместим распознанный текст, если есть файл

    # 3. Если пользователь прикрепил файл → пропускаем поиск
    if file and file.filename:
        try:
            # (A) Считываем содержимое
            file_content = await file.read()
            if not file_content:
                raise HTTPException(status_code=400, detail="Ошибка: загруженный файл пустой!")

            # (B) Генерируем имя файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_filename = file.filename.replace(" ", "_")
            filename_no_ext, file_extension = os.path.splitext(original_filename)

            try:
                transliterated_filename = translit(filename_no_ext, 'ru', reversed=True)
            except Exception as e:
                logging.warning(f"⚠️ Ошибка транслитерации: {str(e)}")
                transliterated_filename = filename_no_ext

            new_filename = f"{timestamp}_{transliterated_filename}{file_extension}"
            file_path = os.path.join(UPLOAD_FOLDER, new_filename)

            # (C) Сохраняем файл асинхронно
            async with aiofiles.open(file_path, "wb") as buffer:
                await buffer.write(file_content)

            # (D) Проверяем, что файл действительно сохранён
            if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                raise HTTPException(status_code=500, detail="Ошибка: файл не был корректно сохранён!")

            logging.info(f"📁 Файл успешно загружен: {file_path}")

            # (E) Сохраняем документ в БД
            new_document = Document(user_id=current_user.id, file_path=file_path)
            db.add(new_document)
            db.commit()
            db.refresh(new_document)

            # (F) Извлекаем (OCR/parsing) текст
            extracted_text = extract_text_from_any_document(file_path)
            logging.info(f"📜 Извлечённый текст:\n{extracted_text}")

        except Exception as e:
            logging.error(f"❌ Ошибка обработки файла: {str(e)}")
            raise HTTPException(status_code=500, detail="Ошибка обработки файла")

        # (G) Отправляем в ассистента (без поиска, skip_vector_store=True)
        assistant_response = send_custom_request(
            user_query=query,
            web_links=None,
            document_summary=extracted_text,  # ВАЖНО: передаём распознанный текст ассистенту
            skip_vector_store=True
        )

        # (H) Сохраняем сообщения в БД
        db.add(Message(thread_id=thread_id, role="user", content=f"Документ: {new_filename}"))
        db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
        db.commit()

        # (I) Возвращаем ответ — добавим также recognized_text, чтобы пользователь видел
        return {
            "assistant_response": assistant_response,
            "recognized_text": extracted_text,
            "file_name": new_filename,
            "file_path": file_path
        }

    # 4. Если файла нет, проверяем, юридический ли запрос
    is_legal = await is_legal_query_gpt(query)
    logging.info(f"📌 Запрос классифицирован как {'юридический' if is_legal else 'НЕ юридический'}: {query}")

    # 4.1 Если запрос не юридический → без поиска
    if not is_legal:
        assistant_response = send_custom_request(
            user_query=query,
            web_links=None,
            document_summary=None,
            skip_vector_store=False
        )
        db.add(Message(thread_id=thread_id, role="user", content=query))
        db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
        db.commit()
        return {"assistant_response": assistant_response}

    # 5. Иначе (юридический запрос без файла), проверяем need_search
    should_search = await should_search_external(query)
    if not should_search:
        # Если поиск не нужен
        assistant_response = send_custom_request(
            user_query=query,
            web_links=None,
            document_summary=None
        )
        db.add(Message(thread_id=thread_id, role="user", content=query))
        db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
        db.commit()
        return {"assistant_response": assistant_response, "new_thread_id": thread_id}

    # 6. Запускаем поиск (Гарант, Google)
    logs = []
    loop = asyncio.get_event_loop()
    google_task = loop.run_in_executor(None, google_search, query, logs)
    garant_task = loop.run_in_executor(None, process_garant_request, query, logs, lambda lvl, msg: logs.append(msg))
    google_results, garant_results = await asyncio.gather(google_task, garant_task)

    google_summaries = [f"{res['summary']} ({res['link']})" for res in google_results]
    logging.info(f"🌐 Найдено {len(google_summaries)} результатов веб-поиска")
    logging.info(f"📄 Результаты ГАРАНТ: {garant_results}")

    # 7. Формируем финальный запрос ассистенту, подмешивая результаты
    assistant_response = send_custom_request(
        user_query=query,
        web_links=google_summaries if google_summaries else None,
        # Если extracted_text остался None, подмешиваем garant_results, иначе extracted_text
        document_summary=extracted_text if extracted_text else garant_results if garant_results else None
    )

    # Убираем служебные ссылки вида 【\d+:\d+†source】
    assistant_response = remove_source_references(assistant_response)

    # 8. Сохраняем в БД итоговые сообщения
    db.add(Message(thread_id=thread_id, role="user", content=query))
    db.add(Message(thread_id=thread_id, role="assistant", content=assistant_response))
    db.commit()

    # 9. Если Гарант вернул ссылку на скачивание
    document_url = None
    if isinstance(garant_results, dict) and "document_url" in garant_results:
        base_url = str(request.base_url).rstrip("/")
        document_filename = garant_results["document_url"].split("/")[-1]
        document_url = f"{base_url}/download/{document_filename}"
        logging.info(f"🔗 Финальная ссылка на скачивание: {document_url}")

    # 10. Формируем ответ
    response = {"assistant_response": assistant_response}
    if document_url:
        response["document_download_url"] = document_url

    return response


def remove_source_references(text: str) -> str:
    """
    Удаляет ссылки вида 【4:18†...】, 【4:0†...】, 【4:11†...】 и т. п.
    """
    # Шаблон: '【\d+:\d+†[^】]*】'
    # 1) '【' - открывающая скобка
    # 2) '\d+:\d+' - числа, двоеточие, снова числа (например, 4:18)
    # 3) '†' - символ '†'
    # 4) '[^】]*' - любая последовательность символов, кроме '】'
    # 5) '】' - закрывающая скобка
    pattern = r'【\d+:\d+†[^】]*】'
    return re.sub(pattern, '', text).strip()


# ========================== Прочие эндпоинты ==========================

@measure_time
@router.post("/upload_file")
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Загружает файл и привязывает его к последнему треду пользователя.
    (Пример эндпоинта; если нужно, используйте.)
    """
    if not file.filename.endswith(".docx"):
        raise HTTPException(status_code=400, detail="Поддерживаются только .docx файлы.")

    thread = db.query(Thread).filter_by(user_id=current_user.id).order_by(Thread.created_at.desc()).first()
    if not thread:
        return JSONResponse(status_code=400, content={"error": "Сначала начните чат."})

    filename = file.filename.replace(" ", "_")
    file_path = os.path.join(UPLOAD_FOLDER, filename)

    async with aiofiles.open(file_path, "wb") as buffer:
        await buffer.write(await file.read())

    file_message = Message(thread_id=thread.id, role="user", content=file_path)
    db.add(file_message)
    db.commit()

    return {"message": "Файл загружен", "filename": filename}


@router.get("/download/{filename}")
async def download_document(filename: str):
    """
    Позволяет скачивать .docx из DOCUMENTS_FOLDER (пример).
    """
    file_path = os.path.join(DOCX_FOLDER, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Документ не найден")

    return FileResponse(
        file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )


# ========================== API ДЛЯ ПОЛУЧЕНИЯ СООБЩЕНИЙ ==========================
@measure_time
@router.get("/messages/{thread_id}")
async def get_messages(
    thread_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Возвращает все сообщения из указанного треда.
    """
    messages = (
        db.query(Message)
        .filter_by(thread_id=thread_id)
        .order_by(Message.created_at)
        .all()
    )
    return {"messages": [{"role": msg.role, "content": msg.content, "created_at": msg.created_at} for msg in messages]}



@router.get("/chat/threads")
async def get_threads(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Получает все треды текущего пользователя.
    """
    threads = (
        db.query(Thread)
        .filter_by(user_id=current_user.id)
        .order_by(Thread.created_at)
        .all()
    )
    return {"threads": [{"id": thread.id, "created_at": thread.created_at} for thread in threads]}



# ========================== API ДЛЯ СОЗДАНИЯ ТРЕДОВ ==========================
@measure_time
@router.post("/create_thread")
async def create_new_thread(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Создаёт новый тред в OpenAI и сохраняет в БД.
    """
    thread = client.beta.threads.create()
    thread_id = thread.id

    new_thread = Thread(id=thread_id, user_id=current_user.id)
    db.add(new_thread)
    db.commit()

    return {"message": "Thread created successfully.", "thread_id": thread_id}


# ========================== ПОДКЛЮЧЕНИЕ РОУТЕРА ==========================
app.include_router(router)
