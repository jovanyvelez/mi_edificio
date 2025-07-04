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
    TasaInteresMora, GastoComunidad, PresupuestoAnual, supabase, SUPABASE_BUCKET, SUPABASE_URL
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

# Rutas para gestión de tasas de interés
@router.get("/admin/tasas-interes", response_class=HTMLResponse)
async def vista_tasas_interes(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                             User: Annotated[Usuario, Depends(admin_required_web)]):
    """Vista para gestionar tasas de interés mensuales"""
    
    # Obtener todas las tasas registradas
    tasas_existentes = session.exec(
        select(TasaInteresMora)
        .order_by(TasaInteresMora.año.desc(), TasaInteresMora.mes.desc())
    ).all()
    
    # Calcular el siguiente período a registrar
    siguiente_año = datetime.now().year
    siguiente_mes = datetime.now().month
    
    if tasas_existentes:
        ultima_tasa = tasas_existentes[0]
        siguiente_año = ultima_tasa.año
        siguiente_mes = ultima_tasa.mes + 1
        
        if siguiente_mes > 12:
            siguiente_mes = 1
            siguiente_año += 1
    
    # Nombres de meses para mostrar
    nombres_meses = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    
    return templates.TemplateResponse("admin/tasas_interes.html", {
        "request": request,
        "tasas_existentes": tasas_existentes,
        "siguiente_año": siguiente_año,
        "siguiente_mes": siguiente_mes,
        "siguiente_mes_nombre": nombres_meses[siguiente_mes],
        "nombres_meses": nombres_meses
    })

@router.post("/admin/tasas-interes", response_class=HTMLResponse)
async def crear_tasa_interes(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                            User: Annotated[Usuario, Depends(admin_required_web)],
                            tasa_anual: float = Form(...)):
    """Crear nueva tasa de interés mensual"""
    
    try:
        # Validar que la tasa anual sea positiva y razonable
        if tasa_anual <= 0 or tasa_anual > 200:  # Máximo 200% anual
            return RedirectResponse(
                url="/admin/tasas-interes?error=invalid_rate",
                status_code=status.HTTP_302_FOUND
            )
        
        # Obtener la última tasa registrada para calcular el siguiente período
        ultima_tasa = session.exec(
            select(TasaInteresMora)
            .order_by(TasaInteresMora.año.desc(), TasaInteresMora.mes.desc())
        ).first()
        
        siguiente_año = datetime.now().year
        siguiente_mes = datetime.now().month
        
        if ultima_tasa:
            siguiente_año = ultima_tasa.año
            siguiente_mes = ultima_tasa.mes + 1
            
            if siguiente_mes > 12:
                siguiente_mes = 1
                siguiente_año += 1
        
        print(f"🔍 Calculando tasa para período: {siguiente_mes:02d}/{siguiente_año}")
        
        # Verificar que no existe ya una tasa para este período
        tasa_existente = session.exec(
            select(TasaInteresMora)
            .where(TasaInteresMora.año == siguiente_año)
            .where(TasaInteresMora.mes == siguiente_mes)
        ).first()
        
        if tasa_existente:
            print(f"❌ Ya existe tasa para {siguiente_mes:02d}/{siguiente_año}")
            return RedirectResponse(
                url="/admin/tasas-interes?error=period_exists",
                status_code=status.HTTP_302_FOUND
            )
        
        # Convertir tasa anual a tasa efectiva mensual
        # Fórmula: tasa_mensual = (1 + tasa_anual/100)^(1/12) - 1
        from decimal import Decimal, ROUND_HALF_UP
        
        tasa_anual_decimal = tasa_anual / 100
        tasa_mensual_efectiva = (1 + tasa_anual_decimal) ** (1/12) - 1
        
        print(f"📊 Tasa anual: {tasa_anual}% -> Tasa mensual: {tasa_mensual_efectiva * 100:.6f}%")
        
        # Convertir a Decimal con 4 decimales de precisión
        # Validar que el valor no exceda los límites del campo (max_digits=5, decimal_places=4)
        if tasa_mensual_efectiva >= 0.1:  # Si es >= 10% mensual, no cabe en el campo
            print(f"❌ Tasa mensual demasiado alta: {tasa_mensual_efectiva * 100:.6f}%")
            return RedirectResponse(
                url="/admin/tasas-interes?error=rate_too_high",
                status_code=status.HTTP_302_FOUND
            )
        
        tasa_mensual_decimal = Decimal(str(tasa_mensual_efectiva)).quantize(
            Decimal('0.0001'), rounding=ROUND_HALF_UP
        )
        
        print(f"💾 Guardando tasa mensual: {tasa_mensual_decimal}")
        
        # Crear nuevo registro
        nueva_tasa = TasaInteresMora(
            año=siguiente_año,
            mes=siguiente_mes,
            tasa_interes_mensual=tasa_mensual_decimal
        )
        
        session.add(nueva_tasa)
        session.flush()  # Hacer flush antes del commit para capturar errores de BD
        session.commit()
        
        print(f"✅ Tasa creada exitosamente: {siguiente_mes:02d}/{siguiente_año} con ID {nueva_tasa.id}")
        
        return RedirectResponse(
            url="/admin/tasas-interes?success=1",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        session.rollback()  # Importante hacer rollback en caso de error
        error_type = type(e).__name__
        error_msg = str(e)
        
        print(f"❌ Error creando tasa de interés: {error_type}: {error_msg}")
        
        # Manejo específico para errores de secuencia
        if "UniqueViolation" in error_type or "duplicate key value" in error_msg:
            print("🔧 Detectado problema de secuencia. Intentando reparar...")
            try:
                # Reparar secuencia automáticamente
                from sqlmodel import text
                max_id_result = session.exec(text('SELECT MAX(id) FROM tasa_interes_mora')).first()
                max_id = max_id_result[0] if max_id_result[0] else 0
                new_seq_val = max_id + 1
                
                session.exec(text(f"SELECT setval('tasa_interes_mora_id_seq', {new_seq_val})"))
                session.commit()
                
                print(f"✅ Secuencia reparada. Nuevo valor: {new_seq_val}")
                
                return RedirectResponse(
                    url="/admin/tasas-interes?error=sequence_repaired",
                    status_code=status.HTTP_302_FOUND
                )
            except Exception as repair_error:
                print(f"❌ Error reparando secuencia: {repair_error}")
        
        import traceback
        traceback.print_exc()
        
        return RedirectResponse(
            url="/admin/tasas-interes?error=database",
            status_code=status.HTTP_302_FOUND
        )

# Rutas para gestión de gastos de la comunidad
@router.get("/admin/gastos", response_class=HTMLResponse)
async def vista_gastos_comunidad(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                                User: Annotated[Usuario, Depends(admin_required_web)],
                                año: Optional[int] = None,
                                mes: Optional[int] = None):
    """Vista principal para gestionar gastos de la comunidad"""
    
    # Usar año y mes actual si no se especifican
    if not año:
        año = datetime.now().year
    if not mes:
        mes = datetime.now().month
    
    # Obtener gastos del mes actual
    gastos_mes = session.exec(
        select(GastoComunidad)
        .where(GastoComunidad.año_gasto == año)
        .where(GastoComunidad.mes_gasto == mes)
        .order_by(GastoComunidad.fecha_gasto.desc())
    ).all()
    
    # Obtener todos los conceptos para el formulario
    conceptos = session.exec(
        select(Concepto)
        .where(Concepto.es_ingreso_tipico == False)  # Filtrar conceptos de gastos
        .order_by(Concepto.nombre)
    ).all()
    
    # Obtener presupuestos anuales disponibles
    presupuestos = session.exec(
        select(PresupuestoAnual)
        .order_by(PresupuestoAnual.año.desc())
    ).all()
    
    # Calcular totales del mes
    total_gastos_mes = sum(gasto.monto for gasto in gastos_mes)
    
    # Obtener gastos recientes (últimos 10 independiente del filtro)
    gastos_recientes = session.exec(
        select(GastoComunidad)
        .order_by(GastoComunidad.fecha_gasto.desc())
        .limit(10)
    ).all()
    
    # Estadísticas del año
    gastos_año = session.exec(
        select(func.sum(GastoComunidad.monto))
        .where(GastoComunidad.año_gasto == año)
    ).first() or 0
    
    cantidad_gastos_año = session.exec(
        select(func.count(GastoComunidad.id))
        .where(GastoComunidad.año_gasto == año)
    ).first() or 0
    
    # Nombres de meses para el selector
    nombres_meses = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    
    return templates.TemplateResponse("admin/gastos_comunidad.html", {
        "request": request,
        "gastos_mes": gastos_mes,
        "gastos_recientes": gastos_recientes,
        "conceptos": conceptos,
        "presupuestos": presupuestos,
        "año_actual": año,
        "mes_actual": mes,
        "total_gastos_mes": total_gastos_mes,
        "gastos_año": gastos_año,
        "cantidad_gastos_año": cantidad_gastos_año,
        "nombres_meses": nombres_meses,
        "años_disponibles": list(range(2020, datetime.now().year + 2)),
        "fecha_hoy": datetime.now().strftime('%Y-%m-%d')
    })

@router.post("/admin/gastos/crear")
async def crear_gasto_comunidad(
    request: Request, 
    session: Annotated[Session, Depends(db_manager.get_session)],
    user: Annotated[Usuario, Depends(admin_required_web)],
    fecha_gasto: date = Form(...),
    concepto_id: int = Form(...),
    monto: float = Form(...),
    descripcion_adicional: Optional[str] = Form(None),
    presupuesto_anual_id: Optional[int] = Form(None),
    documento_soporte: Optional[UploadFile] = File(None)
):
    """Crear nuevo gasto de la comunidad (versión refactorizada)"""
    
    # 1. Validaciones iniciales
    if monto <= 0:
        return RedirectResponse(url="/admin/gastos?error=invalid_amount", status_code=status.HTTP_302_FOUND)
    
    if not session.get(Concepto, concepto_id):
        return RedirectResponse(url="/admin/gastos?error=concepto_not_found", status_code=status.HTTP_302_FOUND)

    # 2. Preparar datos del gasto
    from decimal import Decimal
    
    documento_path = None
    file_content = None
    mime_type = None

    # 3. Procesar el documento si existe
    if documento_soporte and documento_soporte.filename:
        # Validar tipo de archivo
        allowed_mime_types = {
            "pdf": "application/pdf", "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "webp": "image/webp", "heic": "image/heic",
            "heif": "image/heif", "gif": "image/gif"
        }
        file_extension = documento_soporte.filename.split(".")[-1].lower()
        mime_type = allowed_mime_types.get(file_extension)

        if not mime_type:
            return RedirectResponse(url="/admin/gastos?error=invalid_file_type", status_code=status.HTTP_302_FOUND)
        
        # Leer el contenido del archivo para subirlo después
        file_content = await documento_soporte.read()
        # El path se definirá después de tener el ID del gasto
        documento_path = f"gastos/{file_extension}" # Path temporal

    # 4. Crear y guardar el gasto en una transacción
    try:
        # Validar presupuesto (solo si se proporciona)
        if presupuesto_anual_id and not session.get(PresupuestoAnual, presupuesto_anual_id):
            presupuesto_anual_id = None

        nuevo_gasto = GastoComunidad(
            fecha_gasto=fecha_gasto,
            concepto_id=concepto_id,
            descripcion_adicional=descripcion_adicional,
            monto=Decimal(str(monto)),
            documento_soporte_path=documento_path, # Path aún no final
            presupuesto_anual_id=presupuesto_anual_id,
            mes_gasto=fecha_gasto.month,
            año_gasto=fecha_gasto.year
        )
        session.add(nuevo_gasto)
        session.commit()
        session.refresh(nuevo_gasto)

        # 5. Subir el archivo a Supabase (si existe)
        if file_content:
            # Definir el nombre final del archivo usando el ID del gasto
            final_file_name = f"gastos/{nuevo_gasto.id}_{datetime.now().strftime('%Y%m%d')}.{file_extension}"
            
            # Subir a Supabase
            supabase.storage.from_(SUPABASE_BUCKET).upload(
                file=file_content,
                path=final_file_name,
                file_options={"cache-control": "3600", "content-type": mime_type}
            )
            
            # Actualizar el path en la base de datos con la ruta final
            nuevo_gasto.documento_soporte_path = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{final_file_name}"
            session.add(nuevo_gasto)
            session.commit()

    except Exception as e:
        session.rollback()
        print(f"Error creando gasto: {e}")
        # Si la subida falla, el rollback deshace la creación del gasto
        return RedirectResponse(url="/admin/gastos?error=database_or_upload_failed", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(
        url=f"/admin/gastos?success=created&año={nuevo_gasto.año_gasto}&mes={nuevo_gasto.mes_gasto}",
        status_code=status.HTTP_302_FOUND
    )

@router.post("/admin/gastos/{gasto_id}/editar")
async def editar_gasto_comunidad(gasto_id: int,
                                 request: Request, 
                                 session: Annotated[Session, Depends(db_manager.get_session)],
                                 User: Annotated[Usuario, Depends(admin_required_web)],
                                 fecha_gasto: date = Form(...),
                                 concepto_id: int = Form(...),
                                 monto: float = Form(...),
                                 descripcion_adicional: Optional[str] = Form(None),
                                 presupuesto_anual_id: Optional[int] = Form(None)):
    """Editar gasto existente de la comunidad"""
    
    try:
        # Buscar el gasto
        gasto = session.get(GastoComunidad, gasto_id)
        if not gasto:
            return RedirectResponse(
                url="/admin/gastos?error=gasto_not_found",
                status_code=status.HTTP_302_FOUND
            )
        
        # Validar que el monto sea positivo
        if monto <= 0:
            return RedirectResponse(
                url="/admin/gastos?error=invalid_amount",
                status_code=status.HTTP_302_FOUND
            )
        
        # Validar que el concepto existe
        concepto = session.get(Concepto, concepto_id)
        if not concepto:
            return RedirectResponse(
                url="/admin/gastos?error=concepto_not_found",
                status_code=status.HTTP_302_FOUND
            )
        
        # Actualizar campos
        from decimal import Decimal
        gasto.fecha_gasto = fecha_gasto
        gasto.concepto_id = concepto_id
        gasto.monto = Decimal(str(monto))
        gasto.descripcion_adicional = descripcion_adicional
        gasto.mes_gasto = fecha_gasto.month
        gasto.año_gasto = fecha_gasto.year
        
        # Validar presupuesto si se especificó
        if presupuesto_anual_id and presupuesto_anual_id != "":
            presupuesto = session.get(PresupuestoAnual, presupuesto_anual_id)
            if presupuesto:
                gasto.presupuesto_anual_id = presupuesto_anual_id
        else:
            gasto.presupuesto_anual_id = None
        
        session.add(gasto)
        session.commit()
        
        return RedirectResponse(
            url=f"/admin/gastos?success=updated&año={gasto.año_gasto}&mes={gasto.mes_gasto}",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        session.rollback()
        print(f"Error editando gasto: {e}")
        return RedirectResponse(
            url="/admin/gastos?error=database",
            status_code=status.HTTP_302_FOUND
        )

@router.post("/admin/gastos/{gasto_id}/eliminar")
async def eliminar_gasto_comunidad(gasto_id: int,
                                   request: Request,
                                   session: Annotated[Session, Depends(db_manager.get_session)],
                                   User: Annotated[Usuario, Depends(admin_required_web)]):
    """Eliminar gasto de la comunidad"""
    
    try:
        # Buscar el gasto
        gasto = session.get(GastoComunidad, gasto_id)
        if not gasto:
            return RedirectResponse(
                url="/admin/gastos?error=gasto_not_found",
                status_code=status.HTTP_302_FOUND
            )
        
        # Guardar año y mes para la redirección
        año_gasto = gasto.año_gasto
        mes_gasto = gasto.mes_gasto
        
        # Eliminar el gasto
        session.delete(gasto)
        session.commit()
        
        return RedirectResponse(
            url=f"/admin/gastos?success=deleted&año={año_gasto}&mes={mes_gasto}",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        session.rollback()
        print(f"Error eliminando gasto: {e}")
        return RedirectResponse(
            url="/admin/gastos?error=database",
            status_code=status.HTTP_302_FOUND
        )

@router.get("/admin/gastos/reportes", response_class=HTMLResponse)
async def reportes_gastos_comunidad(request: Request, session: Annotated[Session, Depends(db_manager.get_session)],
                                   User: Annotated[Usuario, Depends(admin_required_web)],
                                   año: Optional[int] = None):
    """Vista de reportes de gastos de la comunidad"""
    
    if not año:
        año = datetime.now().year
    
    # Obtener gastos del año agrupados por mes
    gastos_año = session.exec(
        select(GastoComunidad)
        .where(GastoComunidad.año_gasto == año)
        .order_by(GastoComunidad.mes_gasto, GastoComunidad.fecha_gasto.desc())
    ).all()
    
    # Organizar gastos por mes
    gastos_por_mes = {}
    for gasto in gastos_año:
        mes = gasto.mes_gasto or 0
        if mes not in gastos_por_mes:
            gastos_por_mes[mes] = []
        gastos_por_mes[mes].append(gasto)
    
    # Calcular totales por mes
    totales_mes = {}
    for mes, gastos in gastos_por_mes.items():
        totales_mes[mes] = sum(gasto.monto for gasto in gastos)
    
    # Obtener gastos agrupados por concepto
    from sqlmodel import text
    gastos_por_concepto = session.exec(
        text("""
            SELECT c.nombre, 
                   COUNT(gc.id) as cantidad,
                   SUM(gc.monto) as total_monto
            FROM gasto_comunidad gc
            JOIN concepto c ON gc.concepto_id = c.id
            WHERE gc.año_gasto = :año
            GROUP BY c.id, c.nombre
            ORDER BY total_monto DESC
        """),
        {"año": año}
    ).all()
    
    # Total general del año
    total_año = sum(gasto.monto for gasto in gastos_año)
    
    # Nombres de meses
    nombres_meses = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    
    return templates.TemplateResponse("admin/gastos_reportes.html", {
        "request": request,
        "año_actual": año,
        "gastos_por_mes": gastos_por_mes,
        "totales_mes": totales_mes,
        "gastos_por_concepto": gastos_por_concepto,
        "total_año": total_año,
        "nombres_meses": nombres_meses,
        "años_disponibles": list(range(2020, datetime.now().year + 2))
    })