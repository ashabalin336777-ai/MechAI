"""Общая HTTP-основа клиентов: таймаут, один ретрай на сетевую ошибку, маппинг статусов в ошибки."""

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.clients.errors import ClientError, NotFound, Unavailable, ValidationFailed

ModelT = TypeVar("ModelT", bound=BaseModel)

DEFAULT_TIMEOUT_S = 5.0
NETWORK_ATTEMPTS = 2  # одна попытка и один ретрай на сетевую ошибку


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

    def _request(self, method: str, path: str, body: BaseModel | None = None) -> httpx.Response:
        payload: Any = body.model_dump(mode="json") if body is not None else None
        last_error: httpx.TransportError | None = None
        for _ in range(NETWORK_ATTEMPTS):
            try:
                response = self._http.request(method, self._url(path), json=payload)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            failure = error_for_status(response.status_code, self.service_name)
            if failure is not None:
                raise failure
            return response
        raise Unavailable(self.service_name, f"сеть: {last_error}")

    def _parse(self, response: httpx.Response, model: type[ModelT]) -> ModelT:
        try:
            return model.model_validate(response.json())
        except (ValidationError, ValueError) as exc:
            raise Unavailable(self.service_name, "ответ не по схеме") from exc

    def health(self) -> bool:
        """Сервис отвечает на GET /health. Ошибки не пробрасываем: это проверка, а не операция."""
        try:
            self._request("GET", "/health")
        except ClientError:
            return False
        return True
