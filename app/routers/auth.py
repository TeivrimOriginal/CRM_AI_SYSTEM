from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.deps import COOKIE_NAME, get_current_user, require_supervisor
from app.models import User
from app.schemas_auth import (
    LoginRequest, MeResponse, PasswordChange, ProfileUpdate,
    RegisterRequest, UserOut, UserRoleUpdate,
)
from app.security import create_access_token, hash_password, verify_password
router = APIRouter(prefix="/api/auth", tags=["auth"])
@router.post("/register")
def register(payload: RegisterRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    email = payload.email.strip().lower()
    if not email or not payload.password or not payload.full_name.strip():
        raise HTTPException(status_code=422, detail="Заполните все поля")
    if len(payload.password) < 6:
        raise HTTPException(status_code=422, detail="Пароль минимум 6 символов")
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="Пользователь с таким email уже существует")
    users_count = db.scalar(select(func.count()).select_from(User)) or 0
    role = "supervisor" if users_count == 0 else "manager"
    u = User(
        email=email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name.strip(),
        role=role,
        timezone=payload.timezone or "Europe/Moscow",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    token = create_access_token(subject=u.email, role=u.role)
    response.set_cookie(key=COOKIE_NAME, value=token, httponly=True, samesite="lax",
                        max_age=60 * 60 * 12, path="/")
    return {"ok": True, "role": u.role}
@router.post("/login")
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> dict:
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    token = create_access_token(subject=user.email, role=user.role)
    response.set_cookie(key=COOKIE_NAME, value=token, httponly=True, samesite="lax",
                        max_age=60 * 60 * 12, path="/")
    return {"ok": True, "role": user.role}
@router.post("/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}
@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email, full_name=user.full_name,
                      role=user.role, timezone=user.timezone)
@router.post("/profile", response_model=MeResponse)
def update_profile(payload: ProfileUpdate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)) -> MeResponse:
    if payload.full_name:
        user.full_name = payload.full_name.strip()
    if payload.timezone:
        user.timezone = payload.timezone
    db.commit()
    db.refresh(user)
    return MeResponse(id=user.id, email=user.email, full_name=user.full_name,
                      role=user.role, timezone=user.timezone)
@router.post("/change-password")
def change_password(payload: PasswordChange, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)) -> dict:
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Старый пароль неверен")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=422, detail="Пароль минимум 6 символов")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
@router.get("/users", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    return db.scalars(select(User).order_by(User.id)).all()
@router.post("/users/{user_id}/role", response_model=UserOut)
def update_user_role(user_id: int, payload: UserRoleUpdate,
                     db: Session = Depends(get_db), user: User = Depends(require_supervisor)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if payload.role not in ("manager", "supervisor"):
        raise HTTPException(status_code=422, detail="Роль: manager или supervisor")
    if u.id == user.id and payload.role != "supervisor":
        raise HTTPException(status_code=409, detail="Нельзя снять с себя роль supervisor")
    if u.id == user.id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="Нельзя заблокировать себя")
    u.role = payload.role
    u.is_active = payload.is_active
    db.commit()
    db.refresh(u)
    return u
