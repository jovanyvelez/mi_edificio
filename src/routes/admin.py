from fastapi import APIRouter, Request, Form, HTTPException, status, Depends, File, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select, func, Session
from typing import Optional, Annotated
from datetime import datetime, date
from src.settings import settings
from src.models import (
    db_manager, Usuario, Propietario, Apartamento, Concepto,
    RolUsuarioEnum, TipoMovimientoEnum,
    RegistroFinancieroApartamento, CuotaConfiguracion, ControlProcesamientoMensual,
    TasaInteresMora
)
from src.auth_dependencies import  admin_required_web


# Configurar plantillas
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)

router = APIRouter()

@router.get("/dashboard", response_class=HTMLResponse)
async def admin_dashboard(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                          User: Annotated[Usuario, Depends(admin_required_web)]):
    """Dashboard del administrador"""

    # Estadísticas básicas
    total_propietarios = session.exec(
            select(func.count(Propietario.id))
        ).first() or 0
    
    print(f"Total propietarios: {total_propietarios}\n")
        
    total_apartamentos = session.exec(
            select(func.count(Apartamento.id))
        ).first() or 0
    
    print(f"Total apartamentos: {total_apartamentos}\n")
        
    apartamentos_ocupados = session.exec(
            select(func.count(Apartamento.id)).where(Apartamento.propietario_id.isnot(None))
        ).first() or 0
    
    print(f"Apartamentos ocupados: {apartamentos_ocupados}\n")
        
    apartamentos_sin_propietario = total_apartamentos - apartamentos_ocupados
        
        # Registros financieros del mes actual
    mes_actual = datetime.now().month
    año_actual = datetime.now().year
        
    total_ingresos = session.exec(
        select(func.sum(RegistroFinancieroApartamento.monto))
        .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.CREDITO.value)
        .where(RegistroFinancieroApartamento.mes_aplicable == mes_actual)
        .where(RegistroFinancieroApartamento.año_aplicable == año_actual)
    ).first() or 0
        
    # Crear objeto stats con todas las estadísticas que necesita el template
    stats = {
        "total_apartamentos": total_apartamentos,
        "total_propietarios": total_propietarios,
        "fecha_actual": datetime.now().strftime("%d/%m/%Y")
    }
        
    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "stats": stats,
        "apartamentos_ocupados": apartamentos_ocupados,
        "porcentaje_ocupacion": round((apartamentos_ocupados / total_apartamentos * 100) if total_apartamentos > 0 else 0, 1),
        "total_ingresos": total_ingresos
    })

@router.get("/admin/propietarios", response_class=HTMLResponse)
async def admin_propietarios(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Lista de propietarios"""

    # Obtener propietarios con sus apartamentos usando LEFT OUTER JOIN
    results = session.exec(
        select(Propietario, Apartamento)
        .join(Apartamento, isouter=True)
        .order_by(Propietario.id)
    ).all()
    
    # Organizar los resultados agrupando apartamentos por propietario
    propietarios_dict = {}
    for propietario, apartamento in results:
        if propietario.id not in propietarios_dict:
            propietarios_dict[propietario.id] = propietario
            propietarios_dict[propietario.id].apartamentos = []
        
        if apartamento:  # Solo agregar si el apartamento existe (LEFT JOIN puede devolver None)
            propietarios_dict[propietario.id].apartamentos.append(apartamento)
    
    propietarios = list(propietarios_dict.values())
    
    # Para mantener compatibilidad con la plantilla
    apartamentos = session.exec(select(Apartamento)).all()
    usuarios = session.exec(select(Usuario)).all()
        
    return templates.TemplateResponse("admin/propietarios.html", {
        "request": request,
        "propietarios": propietarios,
        "apartamentos": apartamentos,
        "usuarios": usuarios
    })

@router.get("/admin/apartamentos", response_class=HTMLResponse) 
async def admin_apartamentos(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                            User: Annotated[Usuario, Depends(admin_required_web)]):
    """Lista de apartamentos"""
    
    # Obtener apartamentos con propietarios usando JOIN optimizado
    # Similar a la consulta de propietarios pero desde apartamentos hacia propietarios
    results = session.exec(
        select(Apartamento, Propietario)
        .join(Propietario, isouter=True)  # LEFT JOIN para incluir apartamentos sin propietario
        .order_by(Apartamento.identificador)
    ).all()
    
    # Procesar los resultados del JOIN
    apartamentos = []
    for apartamento_row, propietario_row in results:
        # Asignar el propietario al apartamento si existe
        if propietario_row:
            apartamento_row.propietario = propietario_row
        else:
            apartamento_row.propietario = None
        apartamentos.append(apartamento_row)
    
    # Obtener todos los propietarios para los formularios
    propietarios = session.exec(select(Propietario).order_by(Propietario.nombre_completo)).all()
        
    return templates.TemplateResponse("admin/apartamentos.html", {
        "request": request,
        "apartamentos": apartamentos,
        "propietarios": propietarios
    })

@router.get("/admin/finanzas", response_class=HTMLResponse)
async def admin_finanzas(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                        User: Annotated[Usuario, Depends(admin_required_web)]):
    """Vista de finanzas"""
    
    # Obtener apartamentos y conceptos para los formularios
    apartamentos = session.exec(select(Apartamento)).all()
    conceptos = session.exec(select(Concepto)).all()
        
    # Obtener registros financieros recientes
    registros_recientes = session.exec(
        select(RegistroFinancieroApartamento)
        .order_by(RegistroFinancieroApartamento.fecha_efectiva.desc())
        .limit(10)
        ).all()
        
    return templates.TemplateResponse("admin/finanzas.html", {
            "request": request,
            "apartamentos": apartamentos,
            "conceptos": conceptos,
            "registros_recientes": registros_recientes
        })

@router.get("/admin/pagos/generar-cargos", response_class=HTMLResponse)
async def vista_generar_cargos(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                              User: Annotated[Usuario, Depends(admin_required_web)]):
    """Vista para generar cargos mensuales automáticos"""
    
    from datetime import datetime
    
    # Obtener información de configuraciones existentes
    configuraciones = session.exec(
        select(CuotaConfiguracion)
        .order_by(CuotaConfiguracion.año.desc(), CuotaConfiguracion.mes.desc())
        .limit(12)
    ).all()
    
    # Obtener últimos procesamientos
    procesamientos = session.exec(
        select(ControlProcesamientoMensual)
        .order_by(ControlProcesamientoMensual.año.desc(), ControlProcesamientoMensual.mes.desc())
        .limit(10)
    ).all()
    
    # Estadísticas de apartamentos
    total_apartamentos = session.exec(select(func.count(Apartamento.id))).one()
    apartamentos_configurados = session.exec(
        select(func.count(func.distinct(CuotaConfiguracion.apartamento_id)))
        .where(CuotaConfiguracion.año == datetime.now().year)
    ).one()
    
    return templates.TemplateResponse("admin/pagos_generar_cargos.html", {
        "request": request,
        "configuraciones": configuraciones,
        "procesamientos": procesamientos,
        "total_apartamentos": total_apartamentos,
        "apartamentos_configurados": apartamentos_configurados,
        "año_actual": datetime.now().year,
        "mes_actual": datetime.now().month
    })

@router.post("/admin/pagos/generar-cargos")
async def procesar_generar_cargos(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    User: Annotated[Usuario, Depends(admin_required_web)],
    año: int = Form(...),
    mes: int = Form(...),
    forzar: bool = Form(False)
):
    """Procesar la generación automática de cargos mensuales"""
    
    try:
        # Importar la clase del generador
        from src.utils.generador_pagos import GeneradorAutomatico
        
        # Crear instancia del generador
        generador = GeneradorAutomatico()
        
        # Procesar el mes completo (cuotas + intereses + saldos a favor)
        resultado = generador.procesar_mes(año, mes, forzar)
        
        if resultado.get('ya_procesado'):
            return RedirectResponse(
                url=f"/admin/pagos/generar-cargos?warning=ya_procesado&año={año}&mes={mes}",
                status_code=status.HTTP_302_FOUND
            )
        
        if resultado.get('errores'):
            return RedirectResponse(
                url=f"/admin/pagos/generar-cargos?error=procesamiento&detalles={resultado['errores'][0]}",
                status_code=status.HTTP_302_FOUND
            )
        
        # Preparar parámetros de éxito con todos los resultados
        params = [
            f"success=1",
            f"cuotas_generadas={resultado.get('cuotas_generadas', 0)}",
            f"monto_cuotas={resultado.get('monto_cuotas', 0)}",
            f"intereses_generados={resultado.get('intereses_generados', 0)}",
            f"monto_intereses={resultado.get('monto_intereses', 0)}",
            f"saldos_aplicados={resultado.get('saldos_favor_aplicados', 0)}",
            f"monto_saldos={resultado.get('monto_saldos_favor', 0)}",
            f"año={año}",
            f"mes={mes}"
        ]
        
        return RedirectResponse(
            url=f"/admin/pagos/generar-cargos?{'&'.join(params)}",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/pagos/generar-cargos?error=excepcion&detalles={str(e)}",
            status_code=status.HTTP_302_FOUND
        )

@router.get("/admin/pagos/configuracion", response_class=HTMLResponse)
async def pagos_configuracion(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                             User: Annotated[Usuario, Depends(admin_required_web)],
                             año: Optional[int] = None):
    """Vista para configurar cuotas ordinarias por apartamento"""
    
    if not año:
        año = datetime.now().year
    
    # Obtener todos los apartamentos
    apartamentos = session.exec(select(Apartamento).order_by(Apartamento.identificador)).all()
    
    # Obtener configuraciones existentes para el año
    configuraciones = session.exec(
        select(CuotaConfiguracion)
        .where(CuotaConfiguracion.año == año)
        .order_by(CuotaConfiguracion.mes, CuotaConfiguracion.apartamento_id)
    ).all()
    
    # Organizar configuraciones por apartamento y mes
    config_dict = {}
    for config in configuraciones:
        if config.apartamento_id not in config_dict:
            config_dict[config.apartamento_id] = {}
        config_dict[config.apartamento_id][config.mes] = config
    
    return templates.TemplateResponse("admin/pagos_configuracion.html", {
        "request": request,
        "año_actual": año,
        "apartamentos": apartamentos,
        "configuraciones": config_dict,
        "meses": list(range(1, 13))
    })

@router.post("/admin/pagos/configuracion/guardar")
async def guardar_configuracion_pagos(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                                     User: Annotated[Usuario, Depends(admin_required_web)]):
    """Guardar configuración de cuotas ordinarias"""
    
    form_data = await request.form()
    año = int(form_data.get("año"))
    
    try:
        # Procesar cada campo del formulario
        for key, value in form_data.items():
            if key.startswith("cuota_"):
                # Formato: cuota_{apartamento_id}_{mes}
                _, apartamento_id_str, mes_str = key.split("_")
                apartamento_id = int(apartamento_id_str)
                mes = int(mes_str)
                monto = float(value) if value else 0.0
                
                # Buscar configuración existente
                config_existente = session.exec(
                    select(CuotaConfiguracion)
                    .where(CuotaConfiguracion.apartamento_id == apartamento_id)
                    .where(CuotaConfiguracion.mes == mes)
                    .where(CuotaConfiguracion.año == año)
                ).first()
                
                if config_existente:
                    config_existente.monto_cuota_ordinaria_mensual = monto
                else:
                    nueva_config = CuotaConfiguracion(
                        apartamento_id=apartamento_id,
                        mes=mes,
                        año=año,
                        monto_cuota_ordinaria_mensual=monto
                    )
                    session.add(nueva_config)
        
        session.commit()
        
        return RedirectResponse(
            url=f"/admin/pagos/configuracion?success=true&año={año}",
            status_code=303
        )
        
    except Exception as e:
        session.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"Error al guardar configuración: {str(e)}"
        )

@router.get("/admin/pagos/reportes", response_class=HTMLResponse)
async def pagos_reportes(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                        User: Annotated[Usuario, Depends(admin_required_web)],
                        mes: Optional[int] = None,
                        año: Optional[int] = None):
    """Vista de reportes de pagos"""
    
    if not mes:
        mes = datetime.now().month
    if not año:
        año = datetime.now().year
    
    # Obtener concepto de cuota ordinaria
    concepto_cuota = session.exec(
        select(Concepto).where(Concepto.nombre.ilike("%cuota%ordinaria%administr%"))
    ).first()
    
    # Obtener apartamentos
    apartamentos = session.exec(select(Apartamento).order_by(Apartamento.identificador)).all()
    
    # Obtener pagos del mes
    pagos_mes = []
    if concepto_cuota:
        pagos_mes = session.exec(
            select(RegistroFinancieroApartamento)
            .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
            .where(RegistroFinancieroApartamento.mes_aplicable == mes)
            .where(RegistroFinancieroApartamento.año_aplicable == año)
            .order_by(RegistroFinancieroApartamento.fecha_efectiva.desc())
        ).all()
    
    # Generar reporte por apartamento
    reporte_apartamentos = []
    for apartamento in apartamentos:
        pagos_apartamento = [p for p in pagos_mes if p.apartamento_id == apartamento.id]
        total_pagado = sum(p.monto for p in pagos_apartamento if p.tipo_movimiento == TipoMovimientoEnum.CREDITO)
        total_cargado = sum(p.monto for p in pagos_apartamento if p.tipo_movimiento == TipoMovimientoEnum.DEBITO)
        
        reporte_apartamentos.append({
            "apartamento": apartamento,
            "total_pagado": total_pagado,
            "total_cargado": total_cargado,
            "saldo": total_cargado - total_pagado,
            "pagos": pagos_apartamento
        })
    
    return templates.TemplateResponse("admin/pagos_reportes.html", {
        "request": request,
        "mes_actual": mes,
        "año_actual": año,
        "reporte_apartamentos": reporte_apartamentos,
        "total_pagado_general": sum(r["total_pagado"] for r in reporte_apartamentos),
        "total_cargado_general": sum(r["total_cargado"] for r in reporte_apartamentos),
        "meses": [
            {"numero": i, "nombre": ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", 
                                   "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"][i]}
            for i in range(1, 13)
        ],
        "años": list(range(2020, datetime.now().year + 2))
    })

@router.post("/propietarios/crear")
async def crear_propietario(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    nombre_completo: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(...),
    documento_identidad: str = Form(...),
    apartamento_id: Optional[int] = Form(None),
    username: str = Form(...),
    password: str = Form(...)
):
    """Crear nuevo propietario"""

    # Verificar que el username no exista
    usuario_existente = session.exec(
        select(Usuario).where(Usuario.username == username)
    ).first()
    
    if usuario_existente:
        return RedirectResponse(
            url="/admin/propietarios?error=username_exists",
            status_code=status.HTTP_302_FOUND
        )
    
    # Crear usuario
    nuevo_usuario = Usuario(
        username=username,
        password=password,
        nombre_completo=nombre_completo,
        email=email,
        rol=RolUsuarioEnum.PROPIETARIO
    )
    session.add(nuevo_usuario)
    session.commit()
    session.refresh(nuevo_usuario)
    
    # Crear propietario
    nuevo_propietario = Propietario(
        nombre_completo=nombre_completo,
        email=email,
        telefono=telefono,
        documento_identidad=documento_identidad,
        usuario_id=nuevo_usuario.id
    )
    session.add(nuevo_propietario)
    session.commit()
    session.refresh(nuevo_propietario)
    
    # Asignar apartamento si se especificó
    if apartamento_id:
        apartamento = session.get(Apartamento, apartamento_id)
        if apartamento and not apartamento.propietario_id:
            apartamento.propietario_id = nuevo_propietario.id
            session.add(apartamento)
            session.commit()
    
    return RedirectResponse(
        url="/admin/propietarios?success=1",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/propietarios/{propietario_id}/editar")
async def editar_propietario(
    propietario_id: int,
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    nombre_completo: str = Form(...),
    email: str = Form(...),
    telefono: str = Form(...),
    documento_identidad: str = Form(...),
    apartamento_id: Optional[int] = Form(None)
):
    """Editar propietario existente"""
    propietario = session.get(Propietario, propietario_id)
    if not propietario:
        raise HTTPException(status_code=404, detail="Propietario no encontrado")
    
    # Actualizar datos del propietario
    propietario.nombre_completo = nombre_completo
    propietario.email = email
    propietario.telefono = telefono
    propietario.documento_identidad = documento_identidad
    
    # Actualizar usuario asociado
    if propietario.usuario_id:
        usuario = session.get(Usuario, propietario.usuario_id)
        if usuario:
            usuario.nombre_completo = nombre_completo
            usuario.email = email
            session.add(usuario)
    
    # Manejar cambio de apartamento
    # Primero liberar apartamento anterior
    apartamento_anterior = session.exec(
        select(Apartamento).where(Apartamento.propietario_id == propietario_id)
    ).first()
    
    if apartamento_anterior:
        apartamento_anterior.propietario_id = None
        session.add(apartamento_anterior)
    
    # Asignar nuevo apartamento si se especificó
    if apartamento_id:
        apartamento = session.get(Apartamento, apartamento_id)
        if apartamento:
            apartamento.propietario_id = propietario_id
            session.add(apartamento)
    
    session.add(propietario)
    session.commit()
    
    return RedirectResponse(
        url="/admin/propietarios?updated=1",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/propietarios/{propietario_id}/eliminar")
async def eliminar_propietario(
    propietario_id: int, 
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Eliminar propietario"""

    propietario = session.get(Propietario, propietario_id)
    if not propietario:
        raise HTTPException(status_code=404, detail="Propietario no encontrado")
        
    # Verificar que no tenga registros financieros
    registros = session.exec(
        select(RegistroFinancieroApartamento)
        .join(Apartamento)
        .where(Apartamento.propietario_id == propietario_id)
    ).first()
        
    if registros:
        return RedirectResponse(
            url="/admin/propietarios?error=has_records",
            status_code=status.HTTP_302_FOUND
        )
        
    # Liberar apartamento
    apartamento = session.exec(
        select(Apartamento).where(Apartamento.propietario_id == propietario_id)
    ).first()
        
    if apartamento:
        apartamento.propietario_id = None
        session.add(apartamento)
        
    # Eliminar usuario asociado
    if propietario.usuario_id:
        usuario = session.get(Usuario, propietario.usuario_id)
        if usuario:
            session.delete(usuario)
        
    # Eliminar propietario
    session.delete(propietario)
    session.commit()
    
    return RedirectResponse(
        url="/admin/propietarios?deleted=1",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/admin/apartamentos/crear")
async def crear_apartamento(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    identificador: str = Form(...),
    coeficiente_copropiedad: float = Form(...),
    propietario_id: Optional[int] = Form(None)
):
    """Crear nuevo apartamento"""
    # Verificar que el identificador no exista
    apartamento_existente = session.exec(
        select(Apartamento).where(Apartamento.identificador == identificador)
    ).first()
    
    if apartamento_existente:
        return RedirectResponse(
            url="/admin/apartamentos?error=identificador_exists",
            status_code=status.HTTP_302_FOUND
        )
    
    # Validar que propietario_id sea válido si se proporciona
    if propietario_id and propietario_id != "":
        propietario = session.get(Propietario, propietario_id)
        if not propietario:
            return RedirectResponse(
                url="/admin/apartamentos?error=propietario_not_found",
                status_code=status.HTTP_302_FOUND
            )
    else:
        propietario_id = None
    
    # Crear apartamento
    nuevo_apartamento = Apartamento(
        identificador=identificador,
        coeficiente_copropiedad=coeficiente_copropiedad,
        propietario_id=propietario_id
    )
    session.add(nuevo_apartamento)
    session.commit()
    
    return RedirectResponse(
        url="/admin/apartamentos?success=created",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/admin/apartamentos/{apartamento_id}/editar")
async def editar_apartamento(
    apartamento_id: int,
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    identificador: str = Form(...),
    coeficiente_copropiedad: float = Form(...),
    propietario_id: Optional[int] = Form(None)
):
    """Editar apartamento existente"""
    apartamento = session.get(Apartamento, apartamento_id)
    if not apartamento:
        raise HTTPException(status_code=404, detail="Apartamento no encontrado")
    
    # Verificar que el identificador no exista en otro apartamento
    if identificador != apartamento.identificador:
        apartamento_existente = session.exec(
            select(Apartamento)
            .where(Apartamento.identificador == identificador)
            .where(Apartamento.id != apartamento_id)
        ).first()
        
        if apartamento_existente:
            return RedirectResponse(
                url="/admin/apartamentos?error=identificador_exists",
                status_code=status.HTTP_302_FOUND
            )
    
    # Validar que propietario_id sea válido si se proporciona
    if propietario_id and propietario_id != "":
        propietario = session.get(Propietario, propietario_id)
        if not propietario:
            return RedirectResponse(
                url="/admin/apartamentos?error=propietario_not_found",
                status_code=status.HTTP_302_FOUND
            )
    else:
        propietario_id = None
    
    # Actualizar datos
    apartamento.identificador = identificador
    apartamento.coeficiente_copropiedad = coeficiente_copropiedad
    apartamento.propietario_id = propietario_id
    
    session.add(apartamento)
    session.commit()
    
    return RedirectResponse(
        url="/admin/apartamentos?success=updated",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/admin/apartamentos/{apartamento_id}/eliminar")
async def eliminar_apartamento(
    apartamento_id: int, 
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Eliminar apartamento"""
    apartamento = session.get(Apartamento, apartamento_id)
    if not apartamento:
        raise HTTPException(status_code=404, detail="Apartamento no encontrado")
    
    # Verificar que no tenga registros financieros
    registros = session.exec(
        select(RegistroFinancieroApartamento)
        .where(RegistroFinancieroApartamento.apartamento_id == apartamento_id)
    ).first()
    
    if registros:
        return RedirectResponse(
            url="/admin/apartamentos?error=has_records",
            status_code=status.HTTP_302_FOUND
        )
    
    session.delete(apartamento)
    session.commit()
    
    return RedirectResponse(
        url="/admin/apartamentos?success=deleted",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/conceptos/crear")
async def crear_concepto(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    nombre: str = Form(...),
    es_ingreso_tipico: bool = Form(False)
):
    """Crear nuevo concepto"""
    nuevo_concepto = Concepto(
        nombre=nombre,
        es_ingreso_tipico=es_ingreso_tipico
    )
    session.add(nuevo_concepto)
    session.commit()
    
    return RedirectResponse(
        url="/admin/finanzas?success=1",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/conceptos/{concepto_id}/eliminar")
async def eliminar_concepto(
    concepto_id: int, 
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Eliminar concepto"""
    concepto = session.get(Concepto, concepto_id)
    if not concepto:
        raise HTTPException(status_code=404, detail="Concepto no encontrado")
        
    # Verificar que no tenga registros financieros
    registros = session.exec(
        select(RegistroFinancieroApartamento)
        .where(RegistroFinancieroApartamento.concepto_id == concepto_id)
    ).first()
    
    if registros:
        return RedirectResponse(
            url="/admin/finanzas?error=concepto_has_records",
            status_code=status.HTTP_302_FOUND
        )
    
    session.delete(concepto)
    session.commit()
    
    return RedirectResponse(
        url="/admin/finanzas?deleted=1",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/registros-financieros/{apartamento_id}", response_class=HTMLResponse)
async def ver_registros_apartamento(
    apartamento_id: int, 
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Ver registros financieros de un apartamento específico"""
    # Obtener apartamento
    apartamento = session.get(Apartamento, apartamento_id)
    if not apartamento:
        raise HTTPException(status_code=404, detail="Apartamento no encontrado")
    
    # Obtener registros financieros del apartamento
    registros = session.exec(
        select(RegistroFinancieroApartamento)
        .where(RegistroFinancieroApartamento.apartamento_id == apartamento_id)
        .order_by(RegistroFinancieroApartamento.fecha_efectiva.desc())
    ).all()
    
    # Obtener conceptos para el formulario
    conceptos = session.exec(select(Concepto)).all()
    
    # Calcular totales
    total_cargos = sum(
        r.monto for r in registros 
        if r.tipo_movimiento == TipoMovimientoEnum.DEBITO
    )
    total_abonos = sum(
        r.monto for r in registros 
        if r.tipo_movimiento == TipoMovimientoEnum.CREDITO
    )
    saldo = total_abonos - total_cargos
    
    return templates.TemplateResponse("admin/registros_financieros.html", {
        "request": request,
        "apartamento": apartamento,
        "registros": registros,
        "conceptos": conceptos,
        "total_cargos": total_cargos,
        "total_abonos": total_abonos,
        "saldo_total": saldo,
        "now": datetime.now()
    })

@router.post("/registros-financieros/crear")
async def crear_registro_financiero(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    apartamento_id: int = Form(...),
    concepto_id: int = Form(...),
    tipo_movimiento: TipoMovimientoEnum = Form(...),
    monto: float = Form(...),
    fecha_efectiva: date = Form(...),
    mes_aplicable: int = Form(...),
    año_aplicable: int = Form(...),
    referencia_pago: Optional[str] = Form(None),
    descripcion_adicional: Optional[str] = Form(None),
    documento_soporte: Optional[UploadFile] = File(None)
):
    """Crear nuevo registro financiero"""
    ruta_documento = None
    if documento_soporte and documento_soporte.filename:
        raise NotImplementedError("Esta funcionalidad aún no está implementada")
        #Por implementar: ruta_documento = guardar_documento(documento_soporte, "registros_financieros")
        
    nuevo_registro = RegistroFinancieroApartamento(
        apartamento_id=apartamento_id,
        concepto_id=concepto_id,
        tipo_movimiento=tipo_movimiento,
        monto=monto,
        fecha_efectiva=fecha_efectiva,
        mes_aplicable=mes_aplicable,
        año_aplicable=año_aplicable,
        referencia_pago=referencia_pago,
        descripcion_adicional=descripcion_adicional,
        ruta_documento_soporte=ruta_documento,
        fecha_creacion=datetime.now()
    )
    session.add(nuevo_registro)
    session.commit()
    
    return RedirectResponse(
        url=f"/admin/registros-financieros/{apartamento_id}?success=1",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/registros-financieros/{registro_id}/eliminar")
async def eliminar_registro_financiero(
    registro_id: int, 
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)]
):
    """Eliminar registro financiero"""
    registro = session.get(RegistroFinancieroApartamento, registro_id)
    if not registro:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    
    apartamento_id = registro.apartamento_id
    session.delete(registro)
    session.commit()
    
    return RedirectResponse(
        url=f"/admin/registros-financieros/{apartamento_id}?deleted=1",
        status_code=status.HTTP_302_FOUND
    )