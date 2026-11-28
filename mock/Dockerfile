# Образ заглушек заказчика (mock_ml, mock_toir). Контекст сборки — корень репозитория (см. docker-compose.yml).
# Команду запуска задаёт docker-compose.yml: сначала докачка vehicles.json по MATERIALS_URL, затем uvicorn.
# Модуль докачки app/materials.py копируется отдельно: mock/ код не меняем.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY mock/requirements.txt .
RUN pip install -r requirements.txt

COPY mock/ .
COPY app/materials.py /opt/mechai/materials.py
