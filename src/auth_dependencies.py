"""
Dependencias de autenticación reutilizables para toda la aplicación.
Implementa el patrón OAuth2PasswordBearer de FastAPI siguiendo el tutorial oficial.
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from dotenv import load_dotenv
import os

import jwt
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlmodel import Session, select

from src.models import db_manager, Usuario


load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")
ACCESS_TOKEN_EXPIRE_MINUTES = 30


# OAuth2 scheme configuration - FastAPI puede buscar automáticamente el token en headers
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Pydantic models for API responses
class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None


class UserInDB(BaseModel):
    email: str
    nombre: str
    rol: str
    is_active: bool


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verificar contraseña usando bcrypt"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Generar hash de contraseña usando bcrypt"""
    return pwd_context.hash(password)


def get_user_by_email(session: Session, email: str) -> Usuario | None:
    """Obtener usuario por email desde la base de datos"""
    statement = select(Usuario).where(Usuario.email == email)
    return session.exec(statement).first()


def authenticate_user(session: Session, email: str, password: str) -> Usuario | bool:
    """Autenticar usuario con email y contraseña"""
    user = get_user_by_email(session, email)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Crear token JWT con expiración"""
    print("Creating access token with data:", data)
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def get_current_user_from_token(
    token: str,
    session: Annotated[Session, Depends(db_manager.get_session)]
) -> Usuario | None:
    """Obtener usuario actual desde el token JWT"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if ALGORITHM is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(username=email)
    except InvalidTokenError:
        raise credentials_exception

    if token_data.username is None:
        raise credentials_exception

    user = get_user_by_email(session, email=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: Annotated[Session, Depends(db_manager.get_session)]
) -> Usuario:
    """
    Dependency principal para obtener el usuario actual desde el token JWT.
    Usa OAuth2PasswordBearer que busca automáticamente el token en el header Authorization.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if ALGORITHM is None:
        raise credentials_exception

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = TokenData(username=email)
    except InvalidTokenError:
        raise credentials_exception

    if token_data.username is None:
        raise credentials_exception

    user = get_user_by_email(session, email=token_data.username)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[Usuario, Depends(get_current_user)]
) -> Usuario:
    """Dependency que verifica que el usuario esté activo"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_user_from_cookie_or_header(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
) -> Usuario | None:
    """
    Dependency especial para rutas web que puede obtener el token desde cookies o headers.
    Retorna None si no hay token válido (no lanza excepción).
    """
    token = None

    # Intentar obtener token desde cookie primero
    token = request.cookies.get("access_token")

    # Si no hay token en cookie, intentar desde Authorization header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]

    if not token:
        return None

    if ALGORITHM is None:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            return None

        user = get_user_by_email(session, email)
        return user if user and user.is_active else None
    except InvalidTokenError:
        return None


async def get_current_user_required_web(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
) -> Usuario:
    """
    Dependency para rutas web que requieren autenticación.
    Busca el token en cookies o headers y lanza excepción si no encuentra uno válido.
    """
    user = await get_current_user_from_cookie_or_header(request, session)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token no encontrado o inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# Dependencias de roles
async def admin_required(
    current_user: Annotated[Usuario, Depends(get_current_active_user)]
) -> Usuario:
    """Dependency que requiere que el usuario sea administrador"""
    if current_user.rol.upper() != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para administradores"
        )
    return current_user


async def propietario_or_admin_required(
    current_user: Annotated[Usuario, Depends(get_current_active_user)]
) -> Usuario:
    """Dependency que requiere que el usuario sea propietario o administrador"""
    if current_user.rol.upper() not in ["ADMIN", "PROPIETARIO"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para propietarios o administradores"
        )
    return current_user


async def inquilino_or_above_required(
    current_user: Annotated[Usuario, Depends(get_current_active_user)]
) -> Usuario:
    """Dependency que requiere que el usuario sea inquilino, propietario o administrador"""
    if current_user.rol.upper() not in ["ADMIN", "PROPIETARIO", "INQUILINO"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para inquilinos, propietarios o administradores"
        )
    return current_user


# Dependencias de roles para rutas web (soportan cookies y headers)
async def admin_required_web(
    current_user: Annotated[Usuario, Depends(get_current_user_required_web)]
) -> Usuario:
    """Dependency para rutas web que requiere que el usuario sea administrador"""
    if current_user.rol.upper() != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para administradores"
        )
    return current_user


async def propietario_or_admin_required_web(
    current_user: Annotated[Usuario, Depends(get_current_user_required_web)]
) -> Usuario:
    """Dependency para rutas web que requiere que el usuario sea propietario o administrador"""
    if current_user.rol.upper() not in ["ADMIN", "PROPIETARIO"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para propietarios o administradores"
        )
    return current_user


async def inquilino_or_above_required_web(
    current_user: Annotated[Usuario, Depends(get_current_user_required_web)]
) -> Usuario:
    """Dependency para rutas web que requiere que el usuario sea inquilino, propietario o administrador"""
    if current_user.rol.upper() not in ["ADMIN", "PROPIETARIO", "INQUILINO"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso solo para inquilinos, propietarios o administradores"
        )
    return current_user

