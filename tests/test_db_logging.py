"""Текст ошибки БД в логах не содержит пароль и строку подключения."""

import psycopg

from app.db.database import describe_error

RAW_PASSWORD = "p@ss%40word"  # в URL закодирован как p%40ss%2540word
DATABASE_URL = f"postgresql://gen_user:{RAW_PASSWORD}@db.example:5432/default_db?sslmode=require"


def test_describe_error_keeps_class_and_message() -> None:
    exc = psycopg.OperationalError("connection timeout expired")
    assert describe_error(exc, DATABASE_URL) == "OperationalError: connection timeout expired"


def test_describe_error_removes_raw_password() -> None:
    exc = psycopg.OperationalError(f"auth failed, password {RAW_PASSWORD} rejected")
    text = describe_error(exc, DATABASE_URL)
    assert RAW_PASSWORD not in text
    assert "***" in text


def test_describe_error_removes_unquoted_password() -> None:
    exc = psycopg.OperationalError("auth failed for p@ss%40word")
    text = describe_error(exc, DATABASE_URL)
    assert RAW_PASSWORD not in text


def test_describe_error_removes_whole_url() -> None:
    exc = psycopg.OperationalError(f"bad dsn: {DATABASE_URL}")
    text = describe_error(exc, DATABASE_URL)
    assert DATABASE_URL not in text
    assert RAW_PASSWORD not in text


def test_describe_error_without_url_still_works() -> None:
    exc = psycopg.ProgrammingError("invalid dsn")
    assert describe_error(exc, "") == "ProgrammingError: invalid dsn"


def test_describe_error_limits_length() -> None:
    exc = psycopg.OperationalError("x" * 1000)
    text = describe_error(exc, "")
    assert len(text) <= len("OperationalError: ") + 300
