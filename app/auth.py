from fastapi import Request, HTTPException
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from .models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)

def get_current_user(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    user = db.get(User, user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid user")
    return user

def require_roles(user: User, *roles: str):
    if user.role == "admin":
        return
    if user.role not in roles:
        raise HTTPException(status_code=403, detail="Unauthorized")
