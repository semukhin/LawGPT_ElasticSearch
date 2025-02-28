"""
Модуль для работы с GPT-4 через OpenAI API.
Поддерживает отправку запросов пользователей к ассистенту с возможностью функциональных вызовов.
"""
from openai import OpenAI
import json
import logging
from typing import Dict
from sqlalchemy.orm import Session 
from app.handlers.parallel_search import run_parallel_search
from app.utils import measure_time
from app.handlers.es_law_search import search_law_chunks
from app.handlers.garant_process import process_garant_request
from app.handlers.web_search import google_search, search_and_scrape
from app.services.deepresearch_service import DeepResearchService
from app.context_manager import ContextManager, OpenAIProvider
from app.models import Message 



# Инициализация DeepResearchService
deep_research_service = DeepResearchService()

# Конфигурация OpenAI
client = OpenAI(api_key="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")

# Конкретный ассистент ID
ASSISTANT_ID = "asst_jaWku4zA0ufJJuxdG68enKgT"

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Определение функций для function calling
search_functions = [
    {
        "name": "search_law_chunks",
        "description": "Поиск релевантных законов/правовых актов в Elasticsearch.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "search_garant",
        "description": "Поиск документов через API Гаранта с передачей результатов в DeepResearch без summary.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "search_web",
        "description": "Поиск информации в интернете с передачей результатов в DeepResearch без summary.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    },
    {
        "name": "search_deep_research",
        "description": "Глубокий анализ с использованием DeepResearch.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    }
]

def log_function_call(function_name: str, arguments: Dict) -> None:
    """Логирует вызов функции с аргументами для отладки."""
    logging.info(f"🔍 ФУНКЦИЯ ВЫЗВАНА: {function_name}")
    logging.info(f"🔍 АРГУМЕНТЫ: {json.dumps(arguments, ensure_ascii=False)}")


async def handle_function_call(function_name: str, arguments: Dict) -> Dict:
    """Обработка вызова функций ассистентом."""
    query = arguments.get("query", "")
    
    # Логируем вызов функции для отладки
    log_function_call(function_name, arguments)

    if function_name == "search_law_chunks":
        try:
            logging.info("🔍 Выполнение поиска в Elasticsearch для запроса: '%s'", query)
            es_results = search_law_chunks(query)
            if es_results:
                logging.info(f"✅ Найдено {len(es_results)} релевантных чанков в Elasticsearch")
                for i, chunk in enumerate(es_results[:2]):  # Выводим первые 2 чанка для проверки
                    logging.info(f"📄 Чанк {i+1}: {chunk[:100]}...")
                
                deep_results = await deep_research_service.research("\n".join(es_results))
                return {"deep_research_results": deep_results.to_dict()}
            logging.info("❌ Результаты поиска в законодательстве не найдены.")
            return {"error": "Результаты поиска в законодательстве не найдены."}
        except Exception as e:
            logging.error(f"Ошибка при поиске в законодательстве: {str(e)}")
            return {"error": f"Ошибка при поиске в законодательстве: {str(e)}"}

    elif function_name == "search_garant":
        try:
            logging.info("🔍 Выполнение поиска в Гаранте для запроса: '%s'", query)
            # Создаем простую функцию логирования, которая требуется в process_garant_request
            def rag_module(level, message):
                logging_level = getattr(logging, level.upper(), logging.INFO)
                logging.log(logging_level, message)
                return f"[{level.upper()}] {message}"
                
            garant_results = process_garant_request(query, logs=[], rag_module=rag_module)
            if garant_results:
                logging.info(f"✅ Получены результаты из Гаранта: {garant_results.get('docx_file_path', '')}")
                deep_results = await deep_research_service.research(garant_results.get("docx_file_path", ""))
                return {"deep_research_results": deep_results.to_dict()}
            logging.info("❌ Результаты Гаранта не найдены.")
            return {"error": "Результаты Гаранта не найдены."}
        except Exception as e:
            logging.error(f"Ошибка при поиске в Гаранте: {str(e)}")
            return {"error": f"Ошибка при поиске в Гаранте: {str(e)}"}

    elif function_name == "search_web":
        try:
            logging.info("🔍 Выполнение поиска в интернете для запроса: '%s'", query)
            logs = []
            web_results = google_search(query, logs=logs)
            
            for log in logs:
                logging.info(f"🌐 {log}")
                
            if not web_results or len(web_results) == 0:
                logging.info("❌ Не найдено результатов в интернете.")
                return {"error": "Не найдено результатов в интернете."}
                
            # Пытаемся получить более богатые результаты через скрейпинг
            try:
                logging.info("🔍 Выполнение скрейпинга найденных URL...")
                scraped_results = await search_and_scrape(query, logs=logs)
                scraped_texts = []
                for result in scraped_results:
                    if result.is_successful():
                        scraped_texts.append(f"URL: {result.url}\nTitle: {result.title}\nContent: {result.text[:500]}...")
                        logging.info(f"✅ Успешно скрейпнута страница: {result.url} - {result.title}")
                
                if scraped_texts:
                    combined_text = "\n\n".join(scraped_texts)
                    logging.info(f"🔍 Отправка скрейпнутого контента в DeepResearch ({len(scraped_texts)} страниц)")
                    deep_results = await deep_research_service.research(combined_text)
                    return {"deep_research_results": deep_results.to_dict()}
            except Exception as scrape_error:
                logging.warning(f"Ошибка при скрейпинге, используем обычные результаты поиска: {str(scrape_error)}")
            
            # Fallback к обычным результатам, если скрейпинг не удался
            logging.info(f"🔍 Отправка результатов поиска в DeepResearch ({len(web_results)} результатов)")
            deep_results = await deep_research_service.research("\n".join(web_results))
            return {"deep_research_results": deep_results.to_dict()}
        except Exception as e:
            logging.error(f"Ошибка при поиске в интернете: {str(e)}")
            return {"error": f"Ошибка при поиске в интернете: {str(e)}"}
    
    elif function_name == "search_deep_research":
        try:
            logging.info("🔍 Выполнение прямого DeepResearch для запроса: '%s'", query)
            deep_results = await deep_research_service.research(query)
            logging.info("✅ DeepResearch успешно выполнен")
            return {"deep_research_results": deep_results.to_dict()}
        except Exception as e:
            logging.error(f"Ошибка при выполнении deep research: {str(e)}")
            return {"error": f"Ошибка при выполнении deep research: {str(e)}"}

    logging.warning("⚠️ Функция '%s' не распознана.", function_name)
    return {"error": "Неизвестная функция"}



@measure_time
async def send_custom_request(
    user_query: str, 
    thread_id: str,
    db: Session
) -> str:
    """
    Отправляет запрос ассистенту с параллельным поиском во всех источниках.
    
    Args:
        user_query: Запрос пользователя.
        thread_id: ID треда
        db: Сессия базы данных
        
    Returns:
        str: Ответ ассистента.
    """
    logging.info(f"➡️ Начало send_custom_request с user_query='{user_query}'")

    # Получаем историю сообщений
    messages_history = db.query(Message).filter_by(thread_id=thread_id).order_by(Message.created_at).all()

    # Преобразуем в формат для ContextManager
    context_messages = [
        {"role": msg.role, "content": msg.content} 
        for msg in messages_history
    ]

    # Создаем провайдера
    openai_provider = OpenAIProvider(client)

    # Создаем менеджер контекста
    context_manager = ContextManager()
    
    # Системное сообщение
    system_message = (
        "Ты — юридический ассистент. Прежде чем ответить на вопрос, "
        "я проведу многосторонний поиск информации из различных источников "
        "и проанализирую её для предоставления наиболее полного и точного ответа."
    )

    # Подготавливаем контекст
    prepared_context = context_manager.prepare_context(
        context_messages, 
        system_message
    )

    try:
        # Запускаем параллельный поиск по всем источникам
        search_results = await run_parallel_search(user_query)
        
        # Собираем все результаты в единый текст для анализа
        combined_text = "Результаты исследования по запросу:\n\n"
        
        # Добавляем результаты из Elasticsearch
        if "elasticsearch" in search_results and search_results["elasticsearch"]:
            combined_text += "## Результаты из законодательства:\n\n"
            for i, chunk in enumerate(search_results["elasticsearch"][:10], 1):  # Берем первые 10 чанков
                combined_text += f"{i}. {chunk}\n\n"
                
        # Добавляем результаты из Гаранта
        if "garant" in search_results and search_results["garant"].get("text"):
            combined_text += "## Результаты из Гаранта:\n\n"
            garant_text = search_results["garant"]["text"]
            # Ограничиваем размер текста, если он слишком большой
            if len(garant_text) > 10000:
                combined_text += garant_text[:10000] + "...\n\n"
            else:
                combined_text += garant_text + "\n\n"
                
        # Добавляем результаты из веб-поиска
        if "web" in search_results and search_results["web"]:
            combined_text += "## Результаты из интернет-источников:\n\n"
            for i, web_result in enumerate(search_results["web"][:5], 1):  # Берем до 5 результатов
                combined_text += f"{i}. **{web_result['title']}**\n"
                combined_text += f"   URL: {web_result['url']}\n"
                combined_text += f"   {web_result['text'][:1000]}...\n\n"
        
        # Отправляем объединенные результаты в DeepResearch
        deep_research_service = DeepResearchService()
        deep_results = await deep_research_service.research(combined_text)
        
        # Формируем промпт для финального ответа
        followup_prompt = """
        На основе проведенного исследования, подготовь развернутый ответ на запрос пользователя.
        
        Запрос пользователя: "{query}"
        
        Результаты исследования:
        {analysis}
        
        Твой ответ должен:
        1. Начинаться с краткого вывода по запросу
        2. Структурироваться в логические разделы
        3. Включать конкретные ссылки на законы, судебные решения и другие источники
        4. Быть информативным и полным
        
        Важно: если в результатах исследования есть судебные решения или нормативные акты, обязательно укажи их реквизиты (номер, дату, орган).
        """
        
        # Получение финального ответа
        followup_response = client.chat.completions.create(
            model="gpt-4o",
            messages=prepared_context + [
                {"role": "user", "content": followup_prompt.format(
                    query=user_query,
                    analysis=deep_results.analysis
                )}
            ]
        )

        final_text = followup_response.choices[0].message.content
        logging.info(f"📢 Финальный ответ: {final_text[:100]}...")
        return final_text

    except Exception as e:
        error_message = f"Ошибка при обработке запроса: {str(e)}"
        logging.error(error_message)
        return f"Извините, произошла ошибка при обработке запроса: {str(e)}"

# Синхронная версия функции для обратной совместимости
def send_custom_request_sync(user_query: str) -> str:
    """
    Синхронная обертка для send_custom_request.
    Используйте эту функцию в неасинхронном коде.
    
    Args:
        user_query: Запрос пользователя.
        
    Returns:
        str: Ответ ассистента.
    """
    import asyncio
    
    # Создаем новый цикл событий, если его нет
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(
        send_custom_request(user_query=user_query)
    )


# Обработка цитат
def format_legal_references(text):
    """Оформляет ссылки на законы и судебные дела в тексте."""
    import re
    
    # Оформление статей законов
    text = re.sub(r'(ст\.\s*(\d+\.?\s*)+\s*ГК\s*РФ)', r'**\1**', text, flags=re.IGNORECASE)
    text = re.sub(r'(ст\.\s*(\d+\.?\s*)+\s*УК\s*РФ)', r'**\1**', text, flags=re.IGNORECASE)
    
    # Оформление номеров дел
    text = re.sub(r'(дело\s*№?\s*[А-Я\d-]+/\d+)', r'*\1*', text, flags=re.IGNORECASE)
    
    return text

