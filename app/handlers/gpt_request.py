from openai import OpenAI
from app.utils import measure_time  # Добавьте импорт


# Конфигурация OpenAI
client = OpenAI(api_key="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")

# Конкретный ассистент ID
ASSISTANT_ID = "asst_jaWku4zA0ufJJuxdG68enKgT"


@measure_time
def send_custom_request(
    user_query,
    web_links,
    document_summary,
    history_summary=None,
    skip_vector_store=False
):
    """
    Отправляет кастомный запрос ассистенту с пользовательским вводом, ссылками,
    саммари документа и историей переписки.
    Если skip_vector_store=True, просим ассистента не обращаться к векторному хранилищу.
    Threads API не поддерживает роль "system", поэтому объединяем все инструкции в одно "user"-сообщение.
    """
    try:
        # (A) Формируем "префикс" для user-сообщения
        # Если skip_vector_store=True, просим ассистента не обращаться к векторке
        if skip_vector_store:
            preface = (
                "Ты — юридический ассистент. У пользователя есть прикреплённый файл. "
                "НЕ обращайся к векторному хранилищу. Анализируй только текст файла "
                "и контекст, который я тебе передаю.\n\n"
            )
        else:
            preface = (
                "Ты — юридический ассистент. Если запрос юридический и нет файла, "
                "можешь обращаться к векторному хранилищу и подмешивать релевантные документы. "
                "Если это обычный вопрос, тоже можешь обращаться к векторке, если сочтёшь нужным.\n\n"
            )

        # (B) Формируем итоговый контент для "user"
        content = preface
        if history_summary:
            content += f"Краткая история переписки:\n{history_summary}\n\n"

        if web_links:
            content += "Ссылки на релевантные материалы:\n" + "\n".join(web_links) + "\n\n"

        if document_summary:
            content += f"Саммари из документа:\n{document_summary}\n\n"

        content += f"Пользовательский запрос: {user_query}\n"

        # (C) Создаём новый поток (thread)
        thread = client.beta.threads.create()

        # (D) Отправляем всё как одно "user"-сообщение
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=content
        )

        # (E) Считываем ответ ассистента в режиме stream
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
                            response_text += block.text.value
                if event.event == "thread.message.completed":
                    break

        return response_text

    except Exception as e:
        return f"Ошибка при отправке кастомного запроса: {e}"
