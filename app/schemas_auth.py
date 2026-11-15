from pydantic import BaseModel
class LoginRequest(BaseModel):
    email: str
    password: str
class MeResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: str
    timezone: str
class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    timezone: str = "Europe/Moscow"
class UserOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    email: str
    full_name: str
    role: str
    timezone: str
    is_active: bool
class UserRoleUpdate(BaseModel):
    role: str
    is_active: bool = True
class ProfileUpdate(BaseModel):
    full_name: str | None = None
    timezone: str | None = None
class PasswordChange(BaseModel):
    old_password: str
    new_password: str
