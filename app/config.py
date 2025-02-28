MAIL_SETTINGS = {
    "MAIL_SERVER": "smtp.timeweb.ru",
    "MAIL_PORT": 587,
    "MAIL_STARTTLS": True,
    "MAIL_SSL_TLS": False,
    "MAIL_USERNAME": "info@lawgpt.ru",
    "MAIL_PASSWORD": "28h776l991",
    "MAIL_FROM": "info@lawgpt.ru",
}

DATABASE_URL = "mysql+pymysql://gen_user:63)$0oJ\\WRP\\$J@194.87.243.188:3306/default_db" 
SECRET_KEY = "63)$0oJ\WRP\$J"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
ELASTICSEARCH_URL = "http://localhost:9200"
RESPONSE_QUALITY_MONITORING = {
    "enabled": True,
    "save_queries": True,
    "save_responses": True,
    "feedback_enabled": True,
    "minimum_references": 3,  # Минимальное количество ссылок на законы/дела
    "log_directory": "quality_logs"
}

# Добавляем ключ OpenAI
OPENAI_API_KEY = "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"

from fastapi.security import OAuth2PasswordBearer

# Определение схемы OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")