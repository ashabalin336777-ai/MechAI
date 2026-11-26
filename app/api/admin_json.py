"""JSON-ответы /admin/*: явная кодировка UTF-8.

PowerShell 5.1 без charset читает ответ как Latin-1, и русский текст превращается в кашу.
Middleware касается и ответов с ошибками (401/404/422), которые строит FastAPI сам.
"""

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

ADMIN_JSON_TYPE = "application/json; charset=utf-8"


def use_admin_json_charset(app: FastAPI) -> None:
    @app.middleware("http")
    async def admin_json_charset(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        content_type = response.headers.get("content-type", "")
        if request.url.path.startswith("/admin") and content_type.startswith("application/json"):
            response.headers["content-type"] = ADMIN_JSON_TYPE
        return response
