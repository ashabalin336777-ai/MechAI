"""Общая HTTP-основа клиентов: таймаут, один повтор при сбое, маппинг статусов в ошибки."""

import time
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.clients.errors import ClientError, NotFound, Unavailable, ValidationFailed
from app.obs.retry import record_retry

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_TIMEOUT_S = 5.0
MAX_ATTEMPTS = 2  # одна попытка и один повтор
RETRY_PAUSE_S = 2.0
# all: повтор при сетевом сбое, таймауте и 5xx (чтение, диагноз);
# connect: повтор только если запрос не дошёл до сервиса (заявка: повтор после таймаута может
# создать вторую заявку); none: без повтора (проверка доступности).
RetryPolicy = Literal["all", "connect", "none"]


def error_for_status(status_code: int, service: str) -> ClientError | None:
    """Возвращает ошибку для HTTP-статуса или None, если статус успешный."""
    if status_code < 400:
        return None
    if status_code == 404:
        return NotFound(service, f"HTTP {status_code}")
    if status_code in (400, 418, 422):
        return ValidationFailed(service, f"HTTP {status_code}")
    return Unavailable(service, f"HTTP {status_code}")


class ServiceClient:
    """Клиент внешнего сервиса. Полные URL, чтобы тесты могли подставить TestClient."""

    service_name = "service"

    def __init__(self, base_url: str, *, http: httpx.Client | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http or httpx.Client(timeout=DEFAULT_TIMEOUT_S)

    def close(self) -> None:
        self._http.close()

    def _url(self, path: str) -> str:
        return f"{self._base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        body: BaseModel | None = None,
        *,
        retry: RetryPolicy = "all",
    ) -> httpx.Response:
        payload: Any = body.model_dump(mode="json") if body is not None else None
        attempt = 1
        while True:
            try:
                response = self._http.request(method, self._url(path), json=payload)
            except httpx.TransportError as exc:
                if attempt >= MAX_ATTEMPTS or not _retry_transport(exc, retry):
                    raise Unavailable(self.service_name, f"сеть: {exc}") from exc
                self._pause_before_retry(exc, attempt)
                attempt += 1
                continue
            failure = error_for_status(response.status_code, self.service_name)
            if failure is None:
                return response
            if attempt >= MAX_ATTEMPTS or retry != "all" or response.status_code < 500:
                raise failure
            self._pause_before_retry(failure, attempt)
            attempt += 1

    def _pause_before_retry(self, exc: Exception, attempt: int) -> None:
        record_retry(self.service_name, exc, attempt, RETRY_PAUSE_S)
        time.sleep(RETRY_PAUSE_S)

    def _parse(self, response: httpx.Response, model: type[ModelT]) -> ModelT:
        try:
            return model.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise Unavailable(self.service_name, "ответ не по схеме") from exc

    def health(self) -> bool:
        """Сервис отвечает на GET /health. Ошибки не пробрасываем: это проверка, а не операция."""
        try:
            self._request("GET", "/health", retry="none")
        except ClientError:
            return False
        return True


def _retry_transport(exc: httpx.TransportError, policy: RetryPolicy) -> bool:
    if policy == "all":
        return True
    if policy == "connect":
        return isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout))
    return False
