"""Проверка админ-доступа: Bearer ADMIN_TOKEN (сравнение через hmac, токен не пишется в журнал).

Без ADMIN_TOKEN админ-эндпоинты отвечают 404: их как будто нет.
Страница /admin/logs дополнительно принимает cookie после входа по токену: в cookie лежит HMAC
от токена, сам токен в браузере не сохраняется.
"""

import hashlib
import hmac

from fastapi import HTTPException, Request

ADMIN_COOKIE = "mechai_admin"
ADMIN_COOKIE_MAX_AGE_S = 8 * 60 * 60
_COOKIE_CONTEXT = b"mechai-admin-logs-v1"


def check_admin(request: Request) -> None:
    expected = request.app.state.settings.admin_token
    if not expected:
        raise HTTPException(status_code=404)
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token_matches(token, expected):
        raise HTTPException(status_code=401, detail="Неверный токен")


def token_matches(token: str, expected: str) -> bool:
    return hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


def admin_cookie_value(expected: str) -> str:
    return hmac.new(expected.encode("utf-8"), _COOKIE_CONTEXT, hashlib.sha256).hexdigest()


def is_admin(request: Request, expected: str) -> bool:
    """Bearer ADMIN_TOKEN или действующая cookie после входа на странице."""
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token_matches(token, expected):
        return True
    cookie = request.cookies.get(ADMIN_COOKIE, "")
    return bool(cookie) and hmac.compare_digest(
        cookie.encode("utf-8"), admin_cookie_value(expected).encode("utf-8")
    )
