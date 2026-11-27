# Образ приложения. Руководства из data/manuals и заглушки из mock/ копируются при сборке (тома в App Platform запрещены).
# mock/ нужен для запасного режима MOUNT_MOCKS=1; в обычном режиме заглушки живут в своих сервисах compose.
# Копируем только data/manuals, а не весь data/: остальное в data/ в образ не нужно.
FROM python:3.12-slim

# Хэш коммита передаётся при сборке (build-аргумент GIT_SHA) и виден в /health.
ARG GIT_SHA=unknown
ENV GIT_SHA=${GIT_SHA} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY data/manuals ./data/manuals
COPY data/known_conflicts.yaml ./data/known_conflicts.yaml
COPY eval/questions.yaml ./eval/questions.yaml
COPY eval/agent_scenarios.yaml ./eval/agent_scenarios.yaml
COPY mock ./mock

RUN useradd --create-home --uid 10001 appuser \
    && chown appuser:appuser /app/data/manuals
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
