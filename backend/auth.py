import os
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from .database import get_db
from .email_utils import send_reset_email
from .logger import logger
from .models import PasswordResetToken, User

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "eduai-fallback-key-set-in-env")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")
router = APIRouter(prefix="/auth", tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _hash_password(password: str) -> str:
    return pwd_context.hash(password)


def _verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def _create_token(email: str) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    return jwt.encode({"sub": email, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: Optional[str] = payload.get("sub")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Geçersiz token")
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Kullanıcı bulunamadı")
    return user


@router.post("/register", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, body: RegisterRequest, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == body.email).first():
        raise HTTPException(status_code=400, detail="Bu e-posta zaten kayıtlı")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalı")
    user = User(email=body.email, password_hash=_hash_password(body.password))
    db.add(user)
    db.commit()
    token = _create_token(body.email)
    return {"access_token": token, "token_type": "bearer"}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == form.username).first()
    if not user or not _verify_password(form.password, user.password_hash):
        raise HTTPException(status_code=401, detail="E-posta veya şifre hatalı")
    token = _create_token(user.email)
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "ad": current_user.ad or "",
        "soyad": current_user.soyad or "",
        "created_at": current_user.created_at,
    }


class UpdateProfileRequest(BaseModel):
    ad: str = ""
    soyad: str = ""


@router.patch("/profile")
def update_profile(body: UpdateProfileRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.ad = body.ad.strip()
    current_user.soyad = body.soyad.strip()
    db.add(current_user)
    db.commit()
    return {"ok": True, "ad": current_user.ad, "soyad": current_user.soyad}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not _verify_password(body.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Mevcut şifre hatalı")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Yeni şifre en az 6 karakter olmalı")
    current_user.password_hash = _hash_password(body.new_password)
    db.add(current_user)
    db.commit()
    return {"ok": True}


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


@router.post("/forgot-password")
@limiter.limit("3/minute")
def forgot_password(request: Request, body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    # Kullanıcı yoksa bile aynı yanıtı dön (email sızıntısını önle)
    if not user:
        return {"ok": True, "message": "Eğer bu e-posta kayıtlıysa sıfırlama bağlantısı gönderildi."}

    # Eski token'ları geçersiz kıl
    db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.used == 0,
    ).update({"used": 1})

    token = str(uuid4())
    expires = datetime.utcnow() + timedelta(hours=1)
    db.add(PasswordResetToken(user_id=user.id, token=token, expires_at=expires))
    db.commit()

    base_url = str(request.base_url).rstrip("/")
    reset_url = f"{base_url}/reset?token={token}"

    smtp_configured = bool(os.environ.get("SMTP_USER", "").strip() and os.environ.get("SMTP_PASSWORD", "").strip())

    if smtp_configured:
        try:
            send_reset_email(user.email, reset_url)
        except Exception as e:
            logger.error(f"Şifre sıfırlama e-postası gönderilemedi ({user.email}): {e}")
            raise HTTPException(
                status_code=500,
                detail="E-posta gönderilemedi. local.env dosyasında SMTP_USER ve SMTP_PASSWORD tanımlı mı kontrol edin.",
            )
        return {"ok": True, "message": "Sıfırlama bağlantısı e-posta adresinize gönderildi."}
    else:
        # Demo modu: SMTP ayarlanmamış, bağlantıyı direkt döndür
        logger.info(f"[DEMO] Şifre sıfırlama bağlantısı: {reset_url}")
        return {"ok": True, "demo": True, "reset_url": reset_url, "message": "SMTP ayarlı değil — bağlantı aşağıda gösterildi."}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
@limiter.limit("5/minute")
def reset_password(request: Request, body: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_row = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == body.token,
        PasswordResetToken.used == 0,
    ).first()

    if not token_row:
        raise HTTPException(status_code=400, detail="Geçersiz veya kullanılmış bağlantı")

    expires = token_row.expires_at
    expires_naive = expires.replace(tzinfo=None) if expires.tzinfo else expires
    if datetime.utcnow() > expires_naive:
        raise HTTPException(status_code=400, detail="Bağlantı süresi dolmuş. Yeni sıfırlama talep edin.")

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Şifre en az 6 karakter olmalı")

    user = db.query(User).filter(User.id == token_row.user_id).first()
    user.password_hash = _hash_password(body.new_password)
    token_row.used = 1
    db.commit()

    return {"ok": True, "message": "Şifreniz başarıyla güncellendi. Giriş yapabilirsiniz."}
