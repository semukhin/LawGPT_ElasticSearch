import requests
from bs4 import BeautifulSoup
from app.handlers.gpt_handler import send_message_to_assistant

# Ваши ключи Google Custom Search
API_KEY = "AIzaSyAIEt6AC2rHfLb8W90R0Gp_lcFN3RnKQak"
CX = "31a742e3d78ce478c"  # Ваш Custom Search Engine ID

# Конфигурация для дополнительного ассистента
OPENAI_API_KEY = "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"
ASSISTANT_ID = "asst_KItBNJMXCUhrVUS0rumxW307"

def summarize_link(link, logs):
    """
    Загружает текст по ссылке, отправляет его на саммари через кастомного ассистента OpenAI.
    """
    try:
        # Логируем начало обработки ссылки
        logs.append(f"[INFO]: Начинаем обработку ссылки: {link}")

        # Заголовки для имитации запроса от браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        # Загружаем HTML страницы
        response = requests.get(link, headers=headers, timeout=10)
        response.raise_for_status()
        html_content = response.text

        logs.append("[INFO]: HTML успешно загружен.")
        
        # Извлекаем текст из HTML
        soup = BeautifulSoup(html_content, "html.parser")
        page_text = ' '.join(soup.stripped_strings)

        logs.append(f"[INFO]: Извлечённый текст (первые 500 символов): {page_text[:500]}...")

        # Ограничиваем текст, чтобы не превысить лимит токенов (примерно 4000 токенов)
        trimmed_text = page_text[:12000]
        logs.append(f"[INFO]: Ограниченный текст для отправки (первые 500 символов): {trimmed_text[:500]}...")

        # Отправляем текст на саммари через кастомный ассистент
        logs.append("[INFO]: Отправка текста в кастомного ассистента OpenAI.")
        response_text = send_message_to_assistant(trimmed_text)

        if response_text:
            logs.append("[INFO]: Успешно получено саммари.")
            logs.append(f"[INFO]: Саммари: {response_text}")
            return response_text
        else:
            logs.append("[ERROR]: Не удалось получить ответ от ассистента.")
            return f"Ошибка при обработке ссылки {link}."

    except requests.exceptions.RequestException as e:
        error_message = f"[ERROR]: Ошибка при создании саммари для ссылки {link}: {e}"
        logs.append(error_message)
        print(error_message)
        return f"Ошибка при обработке ссылки {link}."

    except Exception as e:
        error_message = f"[ERROR]: Неожиданная ошибка при создании саммари для ссылки {link}: {e}"
        logs.append(error_message)
        print(error_message)
        return f"Ошибка при обработке ссылки {link}."



def google_search(query, logs):
    """
    Выполняет поиск через Google Custom Search API, обрабатывает ссылки и возвращает саммари для них.
    """
    try:
        url = f"https://www.googleapis.com/customsearch/v1"
        params = {
            "key": API_KEY,
            "cx": CX,
            "q": query,
        }
        response = requests.get(url, params=params)
        response.raise_for_status()
        results = response.json().get("items", [])
        
        # Извлекаем только топ-3 ссылки
        top_links = [item.get("link") for item in results[:3] if item.get("link")]
        
        # Генерируем саммари для каждой ссылки
        summaries = []
        for link in top_links:
            summary = summarize_link(link, logs)
            summaries.append({"link": link, "summary": summary})
        
        return summaries
    except Exception as e:
        print(f"Ошибка при запросе к Google API: {e}")
        return []
