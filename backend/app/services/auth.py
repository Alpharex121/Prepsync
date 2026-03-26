from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import psycopg
from jose import JWTError, jwt
from passlib.context import CryptContext
from psycopg.errors import UniqueViolation

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")


def _ensure_users_table() -> None:
    with psycopg.connect(settings.postgres_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        connection.commit()


def register_user(username: str, password: str) -> None:
    hashed = get_password_hash(password)

    try:
        with psycopg.connect(settings.postgres_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, hashed),
                )
            connection.commit()
    except UniqueViolation as exc:
        raise ValueError("Username already exists") from exc
    except Exception as exc:
        raise RuntimeError("Unable to save user to database") from exc


def _get_password_hash(username: str) -> str | None:
    try:
        with psycopg.connect(settings.postgres_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute(
                    "SELECT password_hash FROM users WHERE username = %s",
                    (username,),
                )
                row = cursor.fetchone()
            connection.commit()
    except Exception as exc:
        raise RuntimeError("Unable to read user from database") from exc

    if not row:
        return None
    return str(row[0])


def authenticate_user(username: str, password: str) -> bool:
    hashed_password = _get_password_hash(username)
    if not hashed_password:
        return False
    return verify_password(password, hashed_password)


def get_user(username: str) -> Mapping[str, str] | None:
    try:
        with psycopg.connect(settings.postgres_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        username TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cursor.execute("SELECT username FROM users WHERE username = %s", (username,))
                row = cursor.fetchone()
            connection.commit()
    except Exception as exc:
        raise RuntimeError("Unable to read user from database") from exc

    if not row:
        return None
    return {"username": str(row[0])}


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(subject: str) -> str:
    expires_delta = timedelta(minutes=settings.jwt_access_token_expire_minutes)
    expire = datetime.now(UTC) + expires_delta
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise ValueError("Invalid token") from exc

    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise ValueError("Invalid token subject")
    return username


# Ensure table exists at import/startup paths too.
try:
    _ensure_users_table()
except Exception:
    # Requests will return explicit DB errors when auth endpoints are used.
    pass
