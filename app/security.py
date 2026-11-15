from datetime import datetime, timedelta, timezone
from jose import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher
from app.config import settings
pwd = PasswordHash((BcryptHasher(),))
def hash_password(plain: str) -> str:
    return pwd.hash(plain)
def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd.verify(plain, hashed)
    except Exception:
        return False
def create_access_token(subject: str, role: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
def utcnow() -> datetime:
    return datetime.now(timezone.utc)