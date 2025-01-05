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
SECRET_KEY = "your_secret_key"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

from fastapi.security import OAuth2PasswordBearer

# Определение схемы OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")
