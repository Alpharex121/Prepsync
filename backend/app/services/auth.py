from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt_sha256"], deprecated="auto")

# Phase 2 in-memory store. Replace with PostgreSQL repository in next phases.
_users: dict[str, str] = {}


def register_user(username: str, password: str) -> None:
    if username in _users:
        raise ValueError("Username already exists")
    _users[username] = get_password_hash(password)


def authenticate_user(username: str, password: str) -> bool:
    hashed_password = _users.get(username)
    if not hashed_password:
        return False
    return verify_password(password, hashed_password)


def get_user(username: str) -> Mapping[str, str] | None:
    if username not in _users:
        return None
    return {"username": username}


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

