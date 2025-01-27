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
    if not allowed_file(file.filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file format. Only .docx files are allowed."
        )

    # Моковый успешный ответ
    return {
        "status": 200,
        "message": "File uploaded successfully.",
        "filename": "testfile.docx"
    }

@router.post("/api/remove_file")
async def remove_file(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для удаления файла."""
    # Моковый успешный ответ
    return {
        "status": 200,
        "message": "File deleted successfully."
    }

@router.post("/api/new_chat")
async def new_chat(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для создания нового чата."""
    # Моковый успешный ответ
    return {
        "status": 200,
        "thread_id": "12345"
    }

@router.post("/api/chat/{thread_id}/send_message")
async def send_message(
    thread_id: str,
    request: MessageRequest,
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """Моковый ответ для отправки сообщения."""
    # Моковый успешный ответ
    return {
        "status": 200,
        "response": "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Nunc orci nibh, egestas at massa sit amet, dapibus egestas turpis. Praesent id arcu sagittis, viverra enim a, feugiat nisi. Integer orci ipsum, lacinia in magna nec, pulvinar euismod sapien. Suspendisse id tortor venenatis ante consectetur tincidunt non eget sapien. Integer hendrerit, enim in scelerisque tristique, leo elit scelerisque massa, sed iaculis diam sapien eget odio. Ut porta consequat nibh id rhoncus. Vestibulum lorem ante, pharetra ac justo quis, consequat sodales erat. Donec sit amet velit elit. Mauris cursus efficitur massa, nec commodo mi pulvinar ut. Ut euismod, justo vel ultrices pulvinar, eros dolor efficitur neque, eu mollis nisi neque ut dui. Aenean volutpat euismod justo, eu porta neque ultrices ut. Phasellus ullamcorper quis mauris ut ultrices. Sed sem nisl, maximus in viverra a, sagittis at risus. Nullam euismod viverra mi, in mollis lacus mollis eu. Cras pretium blandit velit, ut fermentum dui aliquam faucibus. Nam elementum lorem vitae turpis dictum ullamcorper. Ut fermentum ultricies velit, sit amet tincidunt magna euismod ut. Nullam at eleifend lacus. Nam sed ipsum id odio fringilla vulputate. Praesent eu dapibus eros, sed faucibus leo. Curabitur consequat sapien sed maximus suscipit. Etiam non sodales magna. Vivamus dignissim dignissim porttitor. Maecenas vel ipsum mauris. Nam in tortor tellus. Sed velit ipsum, ornare eu urna a, consequat faucibus est. Integer sapien velit, blandit id suscipit nec, congue sed leo. Pellentesque velit ipsum, fermentum nec porttitor sit amet, placerat sit amet tellus. Morbi convallis felis a massa vulputate, eget dapibus lorem imperdiet. Morbi in tortor eget tortor finibus auctor ut nec enim. Pellentesque volutpat magna at massa commodo varius. Nam in augue dictum, posuere dolor non, consectetur augue. Nullam tempor felis vel nisi interdum, ac condimentum dolor laoreet. Pellentesque a commodo tellus. Donec mattis sagittis efficitur. Curabitur aliquam ex vel tortor tincidunt viverra. In pharetra nunc velit, vitae gravida lorem ultricies vel. Sed vitae lobortis nulla. Praesent est arcu, consequat ut mauris id, fringilla finibus quam. Suspendisse potenti. Phasellus id ornare dolor. Aenean in dictum mauris. Praesent bibendum metus ut arcu ultrices, at faucibus quam blandit. Morbi eu rutrum massa. Quisque ut egestas leo. Vestibulum ante ipsum primis in faucibus orci luctus et ultrices posuere cubilia curae; Cras dictum iaculis risus vitae condimentum. Donec consectetur nibh id nunc pulvinar, eu volutpat arcu porta. Nunc tincidunt, arcu in ultrices tristique, felis erat hendrerit nulla, nec viverra quam nisi eget massa. Praesent in erat nulla. Lorem ipsum dolor sit amet, consectetur adipiscing elit. In tristique blandit quam, vitae eleifend libero mattis non. Interdum et malesuada fames ac ante ipsum primis in faucibus. Lorem ipsum dolor sit amet, consectetur adipiscing elit. Praesent at accumsan lorem, vitae tempus velit. Vivamus sed felis eget dolor laoreet volutpat eget nec odio.",
        "download_link": "http://127.0.0.1:8000/download/testfile.docx"
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
    # Моковый успешный ответ
    file_path = Path("testfile.docx")
    file_path.write_text("This is a test file.")  # Создаём фиктивный файл
    return FileResponse(file_path, filename=filename)

@router.get("/api/threads")
async def get_threads(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Моковый ответ для получения списка тредов."""
    # Моковый успешный ответ
    return {
        "status": 200,
        "threads": [
            {"id": "12345", "created_at": "2023-10-01T12:00:00"},
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
    # Моковый успешный ответ
    return {
        "status": 200,
        "messages": [
            {"role": "user", "content": "Hello!", "created_at": "2023-10-01T12:00:00"},
            {"role": "assistant", "content": "Hi! How can I help you?", "created_at": "2023-10-01T12:01:00"}
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