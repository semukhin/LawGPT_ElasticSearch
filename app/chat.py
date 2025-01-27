from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from sqlalchemy.orm import Session
from datetime import datetime
from app.database import get_db
from app.models import Thread, Message, User
from app.auth import get_current_user
from app.handlers.garant_process import process_garant_request
from app.handlers.gpt_handler import process_docx_with_assistant
from app.handlers.gpt_request import send_custom_request
from app.handlers.web_search import google_search
from app.handlers.summary_history import create_summary_for_thread
from app.handlers.user_doc_request import extract_text_from_docx
from fastapi.responses import FileResponse
from pathlib import Path
import uuid
from jose import jwt, JWTError
from app.config import SECRET_KEY, ALGORITHM
from app.models import User
from app.database import get_db
from sqlalchemy.orm import Session
import os
import logging
from pydantic import BaseModel

router = APIRouter()

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы для работы с файлами
DOCUMENTS_FOLDER_DOCX = "/Users/admin/Documents/LawGPT_FastAPI_version/LawGPT_FastAPI_version/documents_docx"
UPLOAD_FOLDER = "user_docx"
ALLOWED_EXTENSIONS = {"docx"}
MAX_FILENAME_LENGTH = 20  # Ограничение длины имени файла для отображения на фронте
BASE_URL = "http://127.0.0.1:8000"

# Убедимся, что папки существуют
os.makedirs(DOCUMENTS_FOLDER_DOCX, exist_ok=True)
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

class MessageRequest(BaseModel):
    message: str

async def get_current_user_from_token(token: str, db: Session):
    """Проверяет токен и возвращает текущего пользователя."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="401",
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("user_id")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user

def allowed_file(filename: str) -> bool:
    """Проверяет, поддерживается ли формат файла."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@router.post("/api/upload_file")
async def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Обрабатывает загрузку файла пользователем."""
    if not allowed_file(file.filename):
        raise HTTPException(status_code=400, detail="Неподдерживаемый формат файла")

    # Удаляем старый файл, если он существует
    old_file_path = os.path.join(UPLOAD_FOLDER, f"{current_user.id}.docx")
    if os.path.exists(old_file_path):
        os.remove(old_file_path)

    # Сохраняем новый файл
    filename = f"{current_user.id}.docx"  # Используем ID пользователя как имя файла
    file_path = os.path.join(UPLOAD_FOLDER, filename)
    with open(file_path, "wb") as buffer:
        buffer.write(await file.read())

    # Укорачиваем название файла для отображения
    display_filename = file.filename if len(file.filename) <= MAX_FILENAME_LENGTH else f"{file.filename[:MAX_FILENAME_LENGTH]}..."

    return {"message": "Файл загружен", "filename": display_filename}

@router.post("/api/remove_file")
async def remove_file(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Удаляет текущий прикреплённый файл."""
    try:
        file_path = os.path.join(UPLOAD_FOLDER, f"{current_user.id}.docx")
        if os.path.exists(file_path):
            os.remove(file_path)
            return {"message": "Файл удалён успешно."}
        else:
            raise HTTPException(status_code=404, detail="Файл не найден.")
    except Exception as e:
        logger.error(f"Ошибка при удалении файла: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при удалении файла")

@router.post("/api/new_chat")
async def new_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Создаёт новый чат (тред) для текущего пользователя."""
    try:
        # Создаём новый тред
        new_thread = Thread(user_id=current_user.id)
        db.add(new_thread)
        db.commit()

        logger.info(f"Тред создан: {new_thread.id} для пользователя {current_user.id}")
        return {"thread_id": str(new_thread.id)}  # Возвращаем thread_id как строку
    except Exception as e:
        logger.error(f"Ошибка при создании чата: {e}")
        raise HTTPException(status_code=500, detail="Ошибка при создании чата")

@router.post("/api/chat/{thread_id}/send_message")
async def send_message(
    thread_id: str,
    request: MessageRequest,  # Тело запроса с сообщением
    token: str = Query(...),  # Токен передаётся через параметры запроса
    db: Session = Depends(get_db),
):
    """Обрабатывает отправку сообщения пользователем и возвращает ответ ассистента."""
    try:
        current_user = await get_current_user_from_token(token, db)
    except HTTPException:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")

    # Сохраняем сообщение пользователя в базе данных
    user_message = Message(thread_id=thread_id, role="user", content=request.message, created_at=datetime.utcnow())
    db.add(user_message)
    db.commit()

    # Обрабатываем запрос (например, через GPT или другие обработчики)
    assistant_response, download_link = await process_chat_message(request.message, thread_id, db, current_user)

    # Сохраняем ответ ассистента в базе данных
    assistant_message = Message(thread_id=thread_id, role="assistant", content=assistant_response, created_at=datetime.utcnow())
    db.add(assistant_message)
    db.commit()

    # Если есть ссылка на скачивание, добавляем её в ответ
    if download_link:
        assistant_response += f"\n\nСкачать документ: {download_link}"

    return {"response": assistant_response}

async def process_chat_message(
    query: str,
    thread_id: str,
    db: Session,
    current_user: User
) -> tuple[str, str | None]:
    """Обрабатывает сообщение пользователя и возвращает ответ ассистента и ссылку на скачивание."""
    try:
        logger.info("[LOG]: Обработка сообщения пользователя.")

        # Инициализация переменных
        logs = []
        document_text = None
        document_summary = None
        history_summary = None

        # Проверяем наличие файла пользователя
        user_file_path = os.path.join(UPLOAD_FOLDER, f"{current_user.id}.docx")
        if os.path.exists(user_file_path):
            try:
                logger.info(f"[LOG]: Обработка файла пользователя: {user_file_path}")
                document_text = extract_text_from_docx(user_file_path).strip()
                if not document_text:
                    logger.info("[LOG]: Загруженный файл пустой.")
                    document_text = None

                # Удаляем файл после обработки
                os.remove(user_file_path)
                logger.info("[LOG]: Файл пользователя обработан и удалён.")
            except Exception as e:
                logger.error(f"[LOG]: Ошибка извлечения текста из файла: {e}")
                raise HTTPException(status_code=500, detail="Ошибка обработки документа")

        # Выполняем веб-поиск, если файл не предоставлен
        web_summaries = []
        if not document_text:
            logger.info("[LOG]: Выполняем веб-поиск...")
            web_search_results = google_search(query, logs)
            web_summaries = [f"{result['summary']} ({result['link']})" for result in web_search_results]
            logger.info(f"[LOG]: Результаты веб-поиска: {web_summaries}")

            # Запрос к ГАРАНТ
            logger.info("[LOG]: Выполняем запрос к ГАРАНТ...")
            document_data = process_garant_request(query, logs, lambda t, m: logs.append({t: m}))
            if document_data and "docx_file_path" in document_data:
                docx_file_path = document_data["docx_file_path"]
                document_summary = process_docx_with_assistant(docx_file_path)
                logger.info("[LOG]: Результаты ГАРАНТ обработаны.")
            else:
                logger.info("[LOG]: Результаты ГАРАНТ отсутствуют.")

        # История чата
        if db.query(Message).filter(Message.thread_id == thread_id).count() > 1:
            history_summary = create_summary_for_thread(thread_id)
            logger.info(f"[LOG]: История чата: {history_summary or 'История отсутствует'}")

        # Формируем финальный запрос
        final_query = query
        if document_text:
            final_query += f"\n\nТекст документа:\n{document_text}"

        logger.info("[LOG]: Итоговый запрос в ассистент:")
        logger.info(f"Пользовательский запрос: {query}")
        logger.info(f"Саммери из интернета: {web_summaries}")
        logger.info(f"Текст документа: {document_text or 'Документы отсутствуют'}")
        logger.info(f"Саммери из истории переписки: {history_summary or 'История отсутствует'}")

        # Отправляем запрос ассистенту
        logger.info("[LOG]: Отправляем запрос ассистенту...")
        assistant_response = send_custom_request(
            user_query=final_query,
            web_links=web_summaries,
            document_summary=document_summary or "Документы отсутствуют",
            history_summary=history_summary or "История отсутствует",
        )
        logger.info("[LOG]: Ответ ассистента получен.")

        # Получаем последний добавленный файл
        latest_file = get_latest_file(DOCUMENTS_FOLDER_DOCX)
        download_link = None
        if latest_file:
            download_link = f"{BASE_URL}/download/{latest_file}"

        return assistant_response, download_link

    except Exception as e:
        logger.error(f"[LOG]: Общая ошибка: {e}")
        return "Произошла ошибка при обработке запроса.", None

@router.get("/download/{filename}")
async def download_docx(filename: str):
    """Скачивание DOCX-файла."""
    file_path = os.path.join(DOCUMENTS_FOLDER_DOCX, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(file_path, filename=filename)

@router.get("/api/threads")
async def get_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает список тредов текущего пользователя."""
    threads = db.query(Thread).filter(Thread.user_id == current_user.id).all()
    thread_list = [{"id": str(thread.id), "created_at": thread.created_at} for thread in threads]  # thread_id как строка
    return {"threads": thread_list}

@router.get("/api/thread/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,  # thread_id теперь строка
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Возвращает историю сообщений для конкретного треда."""
    thread = db.query(Thread).filter(Thread.id == thread_id, Thread.user_id == current_user.id).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Тред не найден или у вас нет доступа.")

    messages = db.query(Message).filter(Message.thread_id == thread_id).order_by(Message.created_at).all()
    message_list = [{"role": message.role, "content": message.content, "created_at": message.created_at} for message in messages]
    return {"messages": message_list}


import os
from pathlib import Path

def get_latest_file(directory: str) -> str | None:
    """Возвращает имя последнего добавленного файла в указанной директории."""
    try:
        # Получаем список всех файлов в директории
        files = [f for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]
        
        # Если файлов нет, возвращаем None
        if not files:
            return None
        
        # Сортируем файлы по времени изменения (последний добавленный файл будет первым)
        files.sort(key=lambda x: os.path.getmtime(os.path.join(directory, x)), reverse=True)
        
        # Возвращаем имя последнего файла
        return files[0]
    except Exception as e:
        logger.error(f"[LOG]: Ошибка при поиске последнего файла: {e}")
        return None