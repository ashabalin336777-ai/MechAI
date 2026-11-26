"""Точка входа FastAPI. На этой фазе: healthcheck и заглушка главной страницы."""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(title="MechAI", version="0.1.0")

INDEX_HTML = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Цифровой механик</title>
</head>
<body>
  <main>
    <h1>Цифровой механик</h1>
    <p>Стенд в разработке. Вход и агент появятся в следующих фазах.</p>
  </main>
</body>
</html>
"""


@app.get("/health")
def health() -> dict[str, str]:
    """Проверка живости сервиса. Без авторизации и без обращения к внешним сервисам."""
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Заглушка главной страницы."""
    return INDEX_HTML
