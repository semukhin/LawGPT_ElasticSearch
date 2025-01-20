from openai import OpenAI

# Конфигурация OpenAI
client = OpenAI(api_key="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")

# Конкретный ассистент ID
ASSISTANT_ID = "asst_jaWku4zA0ufJJuxdG68enKgT"

def send_custom_request(user_query, web_links, document_summary, history_summary=None):
    """
    Отправляет кастомный запрос ассистенту с пользовательским вводом, ссылками, саммари документа и историей переписки.
    """
    try:
        # Формируем контент для отправки
        content = f"Пользовательский запрос: {user_query}\n\n"

        if history_summary:
            content += f"Краткая история переписки:\n{history_summary}\n\n"

        if web_links:
            content += f"Ссылки на релевантные материалы:\n" + "\n".join(web_links) + "\n\n"

        content += f"Саммари из документа:\n{document_summary}"

        # Создание нового потока для общения
        thread = client.beta.threads.create()

        # Отправка текста ассистенту
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
        return f"Ошибка при отправке кастомного запроса: {e}"
