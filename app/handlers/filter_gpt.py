import logging
import openai
from openai import OpenAI

# Конфигурация OpenAI
client = OpenAI(api_key="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")

# ID кастомного ассистента (фильтр-ассистент)
ASSISTANT_ID = "asst_GEmrQov7KBnSUOSfDnLk1Z32"

async def send_message_to_assistant(content: str) -> str:
    """
    Отправляет текст кастомному ассистенту OpenAI и возвращает ответ.
    """
    try:
        # Создаём новый поток для общения
        thread = client.beta.threads.create()

        # Отправляем сообщение ассистенту
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=content
        )

        # Получаем ответ от ассистента
        response_text = ""
        with client.beta.threads.runs.stream(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        ) as stream:
            for event in stream:
                if event.event == "thread.message.delta":
                    delta = event.data.delta
                    for block in delta.content:
                        if block.type == "text" and block.text.value:
                            response_text += block.text.value.strip()

                if event.event == "thread.message.completed":
                    break

        # Логируем ответ
        logging.info(f"📌 Ответ ассистента: {response_text}")

        # Проверяем, что ответ – "true" или "false"
        response_text = response_text.lower()
        if response_text not in ["true", "false"]:
            logging.warning(f"⚠️ Непредвиденный ответ от ассистента: {response_text}")
            return "false"  # Безопасный ответ по умолчанию

        return response_text

    except Exception as e:
        logging.error(f"❌ Ошибка при отправке сообщения ассистенту: {e}")
        return "false"  # Если ошибка, считаем, что запрос не юридический



async def should_search_external(query: str) -> bool:
    """
    Определяет, требует ли запрос пользователя поиска в "Гаранте" и интернете.
    """
    try:
        prompt = f"Требует ли этот запрос пользователя поиск в СПС Гарант и в интернете чтобы ответить на него? Ответь только 'true' (если да) или 'false' (если не требуется).\nЗапрос: {query}"
        response = await send_message_to_assistant(prompt)
        response = response.strip().lower()

        logging.info(f"📌 GPT-Классификация необходимости поиска: {query}")
        logging.info(f"🔍 Нужен поиск? {response}")

        if response == "true":
            return True
        
    except Exception as e:
        logging.error(f"❌ Ошибка при проверке необходимости поиска: {e}")
        return False
