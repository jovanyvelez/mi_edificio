from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from typing import Annotated
from datetime import datetime
from pathlib import Path

from src.models import db_manager, Usuario, Propietario, Apartamento
from src.auth_dependencies import propietario_or_admin_required_web
from src.settings import settings
from src.utils.propietario_utils import (
    get_estado_cuenta_completo, 
    get_cartera_morosa, 
)

# Configurar plantillas
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def propietario_dashboard(
    request: Request, 
    session: Annotated[Session, Depends(db_manager.get_session)],
    current_user: Annotated[Usuario, Depends(propietario_or_admin_required_web)]
):
    """Dashboard principal del propietario"""
    
    # Obtener el propietario asociado al usuario actual
    if not current_user.propietario_id:
        # Si es admin, puede acceder pero sin datos específicos de propietario
        if current_user.rol.upper() == "ADMIN":
            return templates.TemplateResponse("propietario/dashboard.html", {
                "request": request,
                "current_user": current_user,
                "es_admin": True,
                "mensaje": "Accediendo como administrador - Seleccione un propietario para ver sus datos"
            })
        else:
            raise HTTPException(
                status_code=404, 
                detail="No se encontró información de propietario asociada a este usuario"
            )
    
    propietario = session.get(Propietario, current_user.propietario_id)
    
    # Obtener apartamentos del propietario
    apartamentos = session.exec(
        select(Apartamento).where(Apartamento.propietario_id == propietario.id)
    ).all()
    
    # Estadísticas básicas
    total_apartamentos = len(apartamentos)
    
    # Si tiene apartamentos, obtener estado de cuenta
    estado_cuenta = None
    if total_apartamentos > 0:
        estado_cuenta = await get_estado_cuenta_completo(propietario.id)
    
    return templates.TemplateResponse("propietario/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "propietario": propietario,
        "apartamentos": apartamentos,
        "total_apartamentos": total_apartamentos,
        "estado_cuenta": estado_cuenta,
        "es_admin": current_user.rol.upper() == "ADMIN"
    })


@router.get("/estado-cuenta", response_class=HTMLResponse)
async def estado_cuenta(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    current_user: Annotated[Usuario, Depends(propietario_or_admin_required_web)]
):
    """Vista detallada del estado de cuenta del propietario"""
    
    # Obtener el propietario asociado al usuario actual
    if not current_user.propietario_id and current_user.rol.upper() != "ADMIN":
        raise HTTPException(
            status_code=404, 
            detail="No se encontró información de propietario asociada a este usuario"
        )
    
    if current_user.propietario_id:
        propietario = session.get(Propietario, current_user.propietario_id)
        # Obtener estado de cuenta completo
        estado_cuenta = await get_estado_cuenta_completo(propietario.id)
    else:
        estado_cuenta = {"apartamentos": [], "resumen": {}}
    
    return templates.TemplateResponse("propietario/estado_cuenta.html", {
        "request": request,
        "current_user": current_user,
        "propietario": propietario,
        "estado_cuenta": estado_cuenta,
        "fecha_actual": datetime.now().strftime("%d/%m/%Y")
    })


@router.get("/cartera-morosa", response_class=HTMLResponse)
async def cartera_morosa(
    request: Request,
    current_user: Annotated[Usuario, Depends(propietario_or_admin_required_web)]
):
    """Vista de la cartera morosa del edificio - solo informativa para propietarios"""
    
    # Obtener información de cartera morosa
    cartera = await get_cartera_morosa()
    
    # Calcular estadísticas
    total_morosos = len(cartera)
    total_deuda = sum(item["saldo_pendiente"] for item in cartera)
    
    return templates.TemplateResponse("propietario/cartera_morosa.html", {
        "request": request,
        "current_user": current_user,
        "cartera_morosa": cartera,
        "total_morosos": total_morosos,
        "total_deuda": total_deuda,
        "fecha_consulta": datetime.now().strftime("%d/%m/%Y")
    })


@router.get("/apartamento/{apartamento_id}/detalle", response_class=HTMLResponse)
async def detalle_apartamento(
    apartamento_id: int,
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    current_user: Annotated[Usuario, Depends(propietario_or_admin_required_web)]
):
    """Vista detallada de un apartamento específico"""
    
    # Verificar que el apartamento existe
    apartamento = session.get(Apartamento, apartamento_id)
    if not apartamento:
        raise HTTPException(status_code=404, detail="Apartamento no encontrado")
    
    # Si no es admin, verificar que sea propietario del apartamento
    if current_user.rol.upper() != "ADMIN":
        if not current_user.propietario_id or apartamento.propietario_id != current_user.propietario_id:
            raise HTTPException(
                status_code=403, 
                detail="No tienes permisos para ver este apartamento"
            )
    
    # Obtener saldos del apartamento
    from src.utils.propietario_utils import get_saldo_apartamento
    saldos = await get_saldo_apartamento(apartamento_id)
    
    # Obtener movimientos detallados
    from src.models import RegistroFinancieroApartamento, Concepto
    movimientos = session.exec(
        select(RegistroFinancieroApartamento, Concepto)
        .join(Concepto, RegistroFinancieroApartamento.concepto_id == Concepto.id)
        .where(RegistroFinancieroApartamento.apartamento_id == apartamento_id)
        .order_by(RegistroFinancieroApartamento.fecha_efectiva.desc())
    ).all()
    
    return templates.TemplateResponse("propietario/detalle_apartamento.html", {
        "request": request,
        "current_user": current_user,
        "apartamento": apartamento,
        "saldos": saldos,
        "movimientos": [
            {
                "registro": mov[0],
                "concepto": mov[1]
            } for mov in movimientos
        ],
        "saldo_actual": saldos[-1]["saldo_acumulado"] if saldos else 0.0
    })


