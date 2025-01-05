from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from . import models, database, auth
import uvicorn

app = FastAPI()

# Создание всех таблиц в базе данных
models.Base.metadata.create_all(bind=database.engine)

# Подключение маршрутов авторизации
app.include_router(auth.router)

# Главная страница
@app.get("/", response_class=HTMLResponse)
def read_root():
    html_content = """
    <html>
        <head>
            <title>Главная страница</title>
        </head>
        <body>
            <h1>Добро пожаловать на сайт!</h1>
            <p>Это главное API-приложение с регистрацией, авторизацией и подтверждением почты.</p>
            <p>Используйте доступные маршруты для взаимодействия с приложением.</p>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Запуск приложения
if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
