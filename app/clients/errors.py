"""Понятные ошибки внешних сервисов. Текст для механика — в user_message, без трасс и 500."""


class ClientError(Exception):
    """Базовая ошибка клиента внешнего сервиса."""

    user_message = "Сервис временно недоступен, повторите позже."

    def __init__(self, service: str, detail: str = "") -> None:
        self.service = service
        self.detail = detail
        super().__init__(f"{service}: {self.user_message} {detail}".strip())


class NotFound(ClientError):
    """Сервис не знает такой проверки или машины (404)."""

    user_message = "Проверка не найдена. Выберите другую машину или проверку."


class ValidationFailed(ClientError):
    """Сервис отклонил запрос как некорректный (400, 418, 422). Не ретраим."""

    user_message = "Сервис отклонил данные заявки. Проверьте поля и повторите."


class Unavailable(ClientError):
    """Сервис недоступен: сеть, таймаут, 5xx или ответ не по схеме."""

    user_message = "Сервис диагностики временно недоступен, повторите."
