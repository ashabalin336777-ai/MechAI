"""Проверка админ-доступа: Bearer ADMIN_TOKEN (сравнение через hmac, токен не пишется в журнал).

Без ADMIN_TOKEN админ-эндпоинты отвечают 404: их как будто нет.
"""

import hmac

from fastapi import HTTPException, Request


def check_admin(request: Request) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=404)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(status_code=401, detail="Неверный токен")
