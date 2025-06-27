from datetime import timedelta
from typing import Annotated

from fastapi import Depends, APIRouter, HTTPException, status, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from src.models import db_manager, Usuario, RolUsuarioEnum

from src.auth_dependencies import (
    authenticate_user, 
    create_access_token, 
    get_current_user_from_cookie_or_header,
    Token,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

from src.settings import settings

router = APIRouter()

templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)
@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    current_user: Annotated[Usuario | None, Depends(get_current_user_from_cookie_or_header)]
):
    """Página principal - redirige a login si no está autenticado"""

    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Mostrar página de login"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login_for_web(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    session: Session = Depends(db_manager.get_session)
):
    """Procesar login de usuario desde formulario web"""
    user = authenticate_user(session, email, password)
    
    if not user:
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Email o contraseña incorrectos"
        })
    
    # Crear token JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, 
        expires_delta=access_token_expires
    )

    response: RedirectResponse
    if user.rol == RolUsuarioEnum.ADMIN:
        response = RedirectResponse(url="/dashboard", status_code=status.HTTP_302_FOUND)
    else:
        response = RedirectResponse(url="/propietario/dashboard", status_code=status.HTTP_302_FOUND)
    
    # Redirigir a la página de bienvenida con cookie
    response.set_cookie(
        key="access_token",
        value=access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=False  # En producción debería ser True con HTTPS
    )
    
    return response


@router.get("/logout")
async def logout():
    """Cerrar sesión del usuario"""
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response



# OAuth2 Endpoint para obtener token JWT de aplicaciones no necesariamente web
@router.post("/token")
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: Annotated[Session, Depends(db_manager.get_session)]
) -> Token:
    """
    Endpoint estándar OAuth2 para obtener token JWT (para API).
    Compatible con OAuth2PasswordBearer - usa username/password del form.
    """
    user = authenticate_user(session, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")
