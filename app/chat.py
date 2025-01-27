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
    """Моковый ответ для загрузки файла."""
    return {
        "message": "Файл загружен",
        "filename": "testfile.docx"  # Фиксированное имя файла для теста
    }

@router.post("/api/remove_file")
async def remove_file(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для удаления файла."""
    return {"message": "Файл удалён успешно."}

@router.post("/api/new_chat")
async def new_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для создания нового чата."""
    return {"thread_id": "12345"}  # Фиксированный ID треда для теста

@router.post("/api/chat/{thread_id}/send_message")
async def send_message(
    thread_id: str,
    request: MessageRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Моковый ответ для отправки сообщения."""
    return {
        "response": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Donec nec condimentum turpis. Vestibulum quis nisi rhoncus, consequat ante ac, bibendum mauris. Sed pellentesque pellentesque magna at hendrerit. Aenean porttitor arcu et condimentum varius. Duis non nunc augue. Donec tristique velit velit, nec facilisis est aliquet sit amet. Pellentesque tempus laoreet leo ut vestibulum. Nam a vehicula nisi, vel vehicula dui. Aliquam sed ante dapibus, eleifend massa eu, rhoncus augue. Pellentesque convallis lobortis lectus, at malesuada orci tincidunt non. Sed non ex efficitur, venenatis risus vel, dictum metus. Quisque ornare magna velit, ac posuere risus sollicitudin vel. Nulla dapibus, lectus sit amet blandit molestie, orci tellus tempor nunc, at tincidunt dui dui nec lacus. Ut vitae dictum quam, sed malesuada nunc. Curabitur facilisis a nisl ut porta. Nulla facilisi. Pellentesque habitant morbi tristique senectus et netus et malesuada fames ac turpis egestas. Vestibulum congue enim nec ex vulputate, id maximus ex scelerisque. Pellentesque lectus est, pretium at velit consectetur, finibus sodales orci. Sed ullamcorper feugiat justo. Nunc a auctor quam. Suspendisse ac feugiat risus. Aenean sagittis mauris non libero auctor, sed congue neque sollicitudin. In nec luctus purus, at maximus ligula. Nullam posuere felis quam, auctor sollicitudin nunc semper sit amet. Etiam ac eros volutpat, fringilla urna non, sollicitudin elit. Donec vel arcu ante. Vestibulum in tristique sem. Mauris nulla ipsum, elementum at orci vitae, elementum gravida nulla. Nam consectetur varius risus id facilisis. Nullam dignissim velit sed elit condimentum maximus. Sed sodales mollis orci sit amet facilisis. Curabitur facilisis sit amet augue at luctus. Quisque convallis vitae erat sit amet consectetur. Vivamus convallis dolor nec sapien sollicitudin rhoncus. Donec in dictum est, a vestibulum elit. Aenean vehicula pulvinar nisi, non ultricies orci semper vitae. Maecenas dictum tellus in luctus commodo. Curabitur dignissim sed lacus eget venenatis. Etiam nec tortor sed augue suscipit efficitur ac vel dolor. Nunc augue est, egestas et rutrum sed, tempor a diam. Vivamus finibus at neque eu scelerisque. Maecenas egestas, mi id gravida euismod, augue elit viverra nunc, non pretium arcu tortor a leo. Quisque malesuada, dui a dictum dignissim, tellus dui ultricies dui, sed elementum eros urna semper nunc. Maecenas risus ipsum, interdum eget suscipit eget, luctus vitae leo. Maecenas eget mollis erat, at elementum nisl. Morbi eu odio fringilla, finibus tellus non, mattis nisi. Phasellus consequat quam blandit urna fringilla lobortis. Donec viverra mi sit amet efficitur viverra. Sed tincidunt quam in ligula lacinia cursus. Suspendisse accumsan tortor viverra, dictum risus nec, pretium diam. Nunc laoreet nunc nulla, egestas pretium tellus accumsan ut. Curabitur aliquam interdum leo, ac egestas turpis congue ut. Nullam bibendum est nunc, et aliquam diam convallis a. Morbi et tempor tortor. Quisque pretium mauris a odio commodo, sed commodo ante rutrum. Suspendisse varius imperdiet nisl, non convallis nisi aliquet rutrum. Fusce condimentum, erat at porta ullamcorper, ligula lacus sollicitudin quam, ut iaculis ligula diam vel neque. Nullam tellus ante, pellentesque sit amet lorem et, tristique tempus neque.",  # Фиксированный ответ
        "download_link": "http://127.0.0.1:8000/download/testfile.docx"  # Фиксированная ссылка
    }

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
    """Моковый ответ для скачивания файла."""
    # Возвращаем фиктивный файл
    file_path = Path("testfile.docx")
    file_path.write_text("Это тестовый файл.")  # Создаём фиктивный файл
    return FileResponse(file_path, filename=filename)

@router.get("/api/threads")
async def get_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для получения списка тредов."""
    return {
        "threads": [
            {"id": "12345", "created_at": "2023-10-01T12:00:00"},  # Фиксированные данные
            {"id": "67890", "created_at": "2023-10-02T12:00:00"}
        ]
    }

@router.get("/api/thread/{thread_id}/messages")
async def get_thread_messages(
    thread_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для получения сообщений в треде."""
    return {
        "messages": [
            {"role": "user", "content": "Привет!", "created_at": "2023-10-01T12:00:00"},
            {"role": "assistant", "content": "Здравствуйте! Чем могу помочь?", "created_at": "2023-10-01T12:01:00"}
        ]
    }


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