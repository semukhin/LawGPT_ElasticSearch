from openai import OpenAI
from docx import Document

# Конфигурация OpenAI
client = OpenAI(api_key="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")

# Конкретный ассистент ID
ASSISTANT_ID = "asst_6WnW2HLJQ5pfklMCBiAR3qnJ"
MAX_TOKENS = 8000

def extract_text_from_docx(docx_file_path):
    """
    Извлекает текст из DOCX файла и разбивает его на блоки для отправки.
    """
    document = Document(docx_file_path)
    full_text = "\n".join([p.text for p in document.paragraphs])

    # Разбиваем текст на блоки, чтобы избежать превышения лимита токенов
    words = full_text.split()
    chunks = []
    current_chunk = []
    current_token_count = 0

    for word in words:
        current_token_count += len(word) // 4  # Оценка: 1 слово ≈ 4 символа
        if current_token_count >= MAX_TOKENS:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_token_count = len(word) // 4
        current_chunk.append(word)

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def send_message_to_assistant(content):
    """
    Отправляет текст кастомному ассистенту OpenAI и возвращает ответ.
    """
    try:
        # Создание нового потока для общения
        thread = client.beta.threads.create()

        # Отправка текста пользователем
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=content
        )

        # Получение ответа от ассистента
        response_text = ""
        with client.beta.threads.runs.stream(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        ) as stream:
            for event in stream:
                # Сбор текста по частям
                if event.event == "thread.message.delta":
                    delta = event.data.delta
                    for block in delta.content:
                        if block.type == "text" and block.text.value:
                            response_text += block.text.value
                # Завершение потока
                if event.event == "thread.message.completed":
                    break

        return response_text

    except Exception as e:
        return f"Ошибка при отправке сообщения: {e}"


def process_docx_with_assistant(docx_file_path):
    """
    Отправляет текст из DOCX ассистенту и возвращает общий ответ.
    """
    try:
        text_chunks = extract_text_from_docx(docx_file_path)
        all_responses = []

        for chunk in text_chunks:
            response = send_message_to_assistant(chunk)
            if response:
                all_responses.append(response)
            else:
                return "Ошибка при получении ответа на один из блоков."

        # Объединяем все ответы в один
        return "\n\n".join(all_responses)

    except Exception as e:
        return f"Ошибка при обработке DOCX: {e}"
