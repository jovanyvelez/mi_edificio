from fastapi import APIRouter, Request, Form, HTTPException, status, Depends, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select, func
from typing import Optional, List, Annotated
from datetime import datetime, date
from src.models import (
    db_manager, Apartamento, Concepto, TipoMovimientoEnum,
    RegistroFinancieroApartamento, CuotaConfiguracion,
    TasaInteresMora, ControlProcesamientoMensual, Usuario,
    supabase, SUPABASE_BUCKET, SUPABASE_URL
)
from src.auth_dependencies import admin_required_web
from src.settings import settings
from fastapi.templating import Jinja2Templates

# Configurar plantillas
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)

router = APIRouter()

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_pagos_avanzado(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    user: Annotated[Usuario, Depends(admin_required_web)],
    mes: Optional[int] = None,
    año: Optional[int] = None
):
    """Dashboard principal del sistema de pagos"""
    # Usar mes y año actuales si no se especifican
    if not mes:
        mes = datetime.now().month
    if not año:
        año = datetime.now().year
    
    # Obtener el concepto de cuota ordinaria
    concepto_cuota = session.exec(
        select(Concepto).where(Concepto.nombre.ilike("%cuota%ordinaria%administr%"))
    ).first()
    
    if not concepto_cuota:
        # Si no existe, crear el concepto
        concepto_cuota = Concepto(
            nombre="Cuota Ordinaria Administración",
            es_ingreso_tipico=True
        )
        session.add(concepto_cuota)
        session.commit()
        session.refresh(concepto_cuota)
    
    # Obtener todos los apartamentos
        apartamentos = session.exec(select(Apartamento)).all()
        total_apartamentos = len(apartamentos)
        
        # Calcular total a recaudar basado en configuraciones
        total_a_recaudar = 0
        configuraciones_mes = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes)
            .where(CuotaConfiguracion.año == año)
        ).all()
        
        # Si hay configuraciones específicas, usar esos montos
        if configuraciones_mes:
            total_a_recaudar = sum(config.monto_cuota_ordinaria_mensual for config in configuraciones_mes)
        else:
            # Si no hay configuraciones, usar un monto por defecto o buscar en meses anteriores
            config_anterior = session.exec(
                select(CuotaConfiguracion)
                .order_by(CuotaConfiguracion.año.desc(), CuotaConfiguracion.mes.desc())
                .limit(1)
            ).first()
            
            if config_anterior:
                # Usar el último monto configurado para todos los apartamentos
                total_a_recaudar = config_anterior.monto_cuota_ordinaria_mensual * total_apartamentos
            else:
                # Valor por defecto si no hay configuraciones
                total_a_recaudar = 100000.0 * total_apartamentos  # Monto por defecto por apartamento
        
        # Obtener pagos realizados este mes
        pagos_mes = []
        total_recaudado = 0
        apartamentos_pagados = 0
        apartamentos_pendientes = []
        
        if concepto_cuota:
            # Pagos realizados este mes
            pagos_mes = session.exec(
                select(RegistroFinancieroApartamento)
                .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
                .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.CREDITO.value)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes)
                .where(RegistroFinancieroApartamento.año_aplicable == año)
            ).all()
            
            total_recaudado = sum(pago.monto for pago in pagos_mes)
            apartamentos_pagados = len(set(pago.apartamento_id for pago in pagos_mes))
            
            # Apartamentos que han pagado este mes
            apartamentos_ids_pagados = {pago.apartamento_id for pago in pagos_mes}
            
            # Apartamentos pendientes de pago
            apartamentos_pendientes = [
                apt for apt in apartamentos 
                if apt.id not in apartamentos_ids_pagados
            ]
        
        # Generar datos para el gráfico
        meses_labels = []
        recaudacion_data = []
        
        for i in range(6):  # Últimos 6 meses
            mes_calc = mes - i
            año_calc = año
            if mes_calc <= 0:
                mes_calc += 12
                año_calc -= 1
            
            meses_labels.insert(0, f"{mes_calc:02d}/{año_calc}")
            
            recaudado_mes = session.exec(
                select(func.sum(RegistroFinancieroApartamento.monto))
                .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
                .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.CREDITO.value)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes_calc)
                .where(RegistroFinancieroApartamento.año_aplicable == año_calc)
            ).first() or 0
            
            recaudacion_data.insert(0, float(recaudado_mes))
        
        # Calcular porcentaje de recaudo basado en monto, no en número de apartamentos
        porcentaje_recaudado = round((total_recaudado / total_a_recaudar * 100) if total_a_recaudar > 0 else 0, 1)
        
        # Obtener información del procesamiento automático V3
        control_v3 = session.exec(
            select(ControlProcesamientoMensual)
            .where(ControlProcesamientoMensual.año == año)
            .where(ControlProcesamientoMensual.mes == mes)
            .where(ControlProcesamientoMensual.tipo_procesamiento == "CUOTAS_INTERESES")
        ).first()
        
        return templates.TemplateResponse(
            "admin/pagos.html",
            {
                "request": request,
                "mes_actual": mes,
                "año_actual": año,
                "total_apartamentos": total_apartamentos,
                "apartamentos_pagados": apartamentos_pagados,
                "apartamentos_pendientes": len(apartamentos_pendientes),
                "total_recaudado": total_recaudado,
                "total_a_recaudar": total_a_recaudar,
                "porcentaje_recaudacion": round((apartamentos_pagados / total_apartamentos * 100) if total_apartamentos > 0 else 0, 1),
                "porcentaje_recaudado": porcentaje_recaudado,
                "apartamentos_pendientes_lista": apartamentos_pendientes,
                "pagos_mes": pagos_mes,
                "meses_labels": meses_labels,
                "recaudacion_data": recaudacion_data,
                "apartamentos_configurados": len(configuraciones_mes),
                "apartamentos_con_cargo": len(configuraciones_mes),
                "concepto_cuota": concepto_cuota,
                "control_v3": control_v3
            }
        )

@router.get("/configuracion", response_class=HTMLResponse)
async def admin_pagos_configuracion(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)],
    mes: Optional[int] = None,
    año: Optional[int] = None
):
    """Configuración de cuotas mensuales"""
    # Usar mes y año actuales si no se especifican
    if not mes:
        mes = datetime.now().month
    if not año:
        año = datetime.now().year
    
    with db_manager.get_session_context() as session:
        # Obtener todos los apartamentos con sus configuraciones
        apartamentos = session.exec(select(Apartamento)).all()
        
        # Obtener configuraciones existentes para el mes/año
        configuraciones = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes)
            .where(CuotaConfiguracion.año == año)
        ).all()
        
        # Crear diccionario para acceso rápido
        config_dict = {config.apartamento_id: config for config in configuraciones}
        
        return templates.TemplateResponse(
            "admin/pagos_configuracion.html",
            {
                "request": request,
                "apartamentos": apartamentos,
                "configuraciones": config_dict,
                "mes_actual": mes,
                "año_actual": año,
                "meses": [
                    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
                ]
            }
        )

@router.post("/configuracion/guardar")
async def guardar_configuracion_cuotas(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)],
    mes: int = Form(...),
    año: int = Form(...),
    montos: List[float] = Form(...)
):
    """Guardar configuración de cuotas para el mes"""
    with db_manager.get_session_context() as session:
        # Obtener todos los apartamentos
        apartamentos = session.exec(select(Apartamento)).all()
        
        if len(montos) != len(apartamentos):
            return RedirectResponse(
                url="/admin/pagos/configuracion?error=data_mismatch",
                status_code=status.HTTP_302_FOUND
            )
        
        # Eliminar configuraciones existentes para el mes/año
        configuraciones_existentes = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes)
            .where(CuotaConfiguracion.año == año)
        ).all()
        
        for config in configuraciones_existentes:
            session.delete(config)
        
        # Crear nuevas configuraciones
        for i, apartamento in enumerate(apartamentos):
            if i < len(montos) and montos[i] > 0:
                nueva_config = CuotaConfiguracion(
                    apartamento_id=apartamento.id,
                    mes=mes,
                    año=año,
                    monto_cuota_ordinaria_mensual=montos[i]
                )
                session.add(nueva_config)
        
        session.commit()
    
    return RedirectResponse(
        url="/admin/pagos/configuracion?success=1",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/generar-cargos", response_class=HTMLResponse)
async def admin_pagos_generar_cargos(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """Página para generar cargos automáticos"""
    mes_actual = datetime.now().month
    año_actual = datetime.now().year
    
    with db_manager.get_session_context() as session:
        # Verificar si existen configuraciones para el mes actual
        configuraciones = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes_actual)
            .where(CuotaConfiguracion.año == año_actual)
        ).all()
        
        # Obtener conceptos relacionados con cuotas
        conceptos_cuota = session.exec(
            select(Concepto).where(
                Concepto.nombre.ilike("%cuota%") | 
                Concepto.nombre.ilike("%administr%")
            )
        ).all()
        
        return templates.TemplateResponse(
            "admin/pagos_generar_cargos.html",
            {
                "request": request,
                "mes_actual": mes_actual,
                "año_actual": año_actual,
                "configuraciones_disponibles": len(configuraciones),
                "conceptos_cuota": conceptos_cuota
            }
        )

@router.post("/generar-cargos")
async def generar_cargos_automaticos(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)],
    mes: int = Form(...),
    año: int = Form(...),
    concepto_id: int = Form(...),
    forzar: bool = Form(False)
):
    print(f"Generando cargos para {mes}/{año} con concepto ID {concepto_id} (forzar={forzar})")

    """Generar cargos automáticos basados en la configuración"""
    with db_manager.get_session_context() as session:
        # Obtener el concepto de cuota ordinaria
        concepto_cuota = session.exec(
            select(Concepto).where(Concepto.id == concepto_id)  # Usar ID del concepto seleccionado
        ).first()
        
        if not concepto_cuota:
            return RedirectResponse(
                url="/admin/pagos/generar-cargos?error=no_concept",
                status_code=status.HTTP_302_FOUND
            )
        
        # Obtener configuraciones para el mes/año
        configuraciones = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes)
            .where(CuotaConfiguracion.año == año)
        ).all()
        
        if not configuraciones:
            return RedirectResponse(
                url="/admin/pagos/generar-cargos?error=no_config",
                status_code=status.HTTP_302_FOUND
            )
        print(f"Generando {len(configuraciones)} cargos para {mes}/{año}")
        # Verificar si ya existen cargos para este mes/año
        cargos_existentes = session.exec(
            select(RegistroFinancieroApartamento)
            .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
            .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.DEBITO.value)
            .where(RegistroFinancieroApartamento.mes_aplicable == mes)
            .where(RegistroFinancieroApartamento.año_aplicable == año)  # Excluir apartamento 3
        ).first()


        if cargos_existentes:
            return RedirectResponse(
                url="/admin/pagos/generar-cargos?error=already_exists",
                status_code=status.HTTP_302_FOUND
            )
        
        # Generar cargos
        cargos_creados = 0
        fecha_cargo = date(año, mes, 1)  # Primer día del mes
        for config in configuraciones:
            nuevo_cargo = RegistroFinancieroApartamento(
            apartamento_id=config.apartamento_id,
            concepto_id=concepto_cuota.id,
            tipo_movimiento="DEBITO",
            monto=config.monto_cuota_ordinaria_mensual,
            fecha_efectiva=fecha_cargo,
            mes_aplicable=mes,
            año_aplicable=año,
            referencia_pago=f"CARGO-AUTO-{mes:02d}/{año}",
            descripcion_adicional=f"Cuota ordinaria de administración - {mes:02d}/{año}",
            fecha_creacion=datetime.now()
            )
            session.add(nuevo_cargo)
            cargos_creados += 1
            session.commit()
    
    return RedirectResponse(
        url=f"/admin/pagos/generar-cargos?success={cargos_creados}",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/procesar", response_class=HTMLResponse)
async def admin_pagos_procesar(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """Página para procesar pagos individuales"""
    with db_manager.get_session_context() as session:
        # Obtener apartamentos y concepto de cuota
        apartamentos = session.exec(select(Apartamento)).all()
        concepto_cuota = session.exec(
            select(Concepto).where(Concepto.nombre.ilike("%cuota%ordinaria%administr%"))
        ).first()
        
        # Calcular saldos para cada apartamento
        apartamentos_con_saldo = []
        for apartamento in apartamentos:
            # Obtener registros financieros del apartamento
            registros = session.exec(
                select(RegistroFinancieroApartamento)
                .where(RegistroFinancieroApartamento.apartamento_id == apartamento.id)
            ).all()
            
            # Calcular totales
            total_cargos = sum([reg.monto for reg in registros if reg.tipo_movimiento == TipoMovimientoEnum.DEBITO])
            total_abonos = sum([reg.monto for reg in registros if reg.tipo_movimiento == TipoMovimientoEnum.CREDITO])
            saldo_total = total_cargos - total_abonos
            
            # Solo incluir apartamentos con saldo pendiente
            if saldo_total > 0:
                # Obtener cargos pendientes (débitos sin abonos correspondientes)
                cargos_pendientes = []
                cargos_debitos = [reg for reg in registros if reg.tipo_movimiento == TipoMovimientoEnum.DEBITO]
                
                for cargo in cargos_debitos:
                    # Verificar si hay abono correspondiente para este cargo
                    abono_correspondiente = any(
                        reg.tipo_movimiento == TipoMovimientoEnum.CREDITO and
                        reg.mes_aplicable == cargo.mes_aplicable and
                        reg.año_aplicable == cargo.año_aplicable
                        for reg in registros
                    )
                    if not abono_correspondiente:
                        cargos_pendientes.append(cargo)
                
                # Agregar información del apartamento con saldo
                apartamento_info = {
                    'apartamento': apartamento,  # Objeto completo del apartamento
                    'saldo_total': saldo_total,
                    'total_cargos': total_cargos,
                    'total_abonos': total_abonos,
                    'cargos_pendientes': sorted(cargos_pendientes, key=lambda x: (x.año_aplicable, x.mes_aplicable))
                }
                apartamentos_con_saldo.append(apartamento_info)
        
        # Ordenar por saldo descendente
        apartamentos_con_saldo.sort(key=lambda x: x['saldo_total'], reverse=True)


        return templates.TemplateResponse(
            "admin/pagos_procesar.html",
            {
                "request": request,
                "apartamentos": apartamentos,
                "concepto_cuota": concepto_cuota,
                "apartamentos_con_saldo": apartamentos_con_saldo,
                "now": datetime.now
            }
        )

@router.post("/procesar")
async def procesar_pago_individual(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)],
    apartamento_id: int = Form(...),
    monto_pago: float = Form(...),
    fecha_pago: date = Form(...),
    mes_aplicable: int = Form(...),
    año_aplicable: int = Form(...),
    referencia_pago: Optional[str] = Form(None),
    observaciones: Optional[str] = Form(None)
):
    """Procesar pago individual"""
    with db_manager.get_session_context() as session:
        # Obtener el concepto de Pago Cuota
        concepto_cuota = session.exec(
            select(Concepto).where(Concepto.id == 5)  # ID del concepto de Pago Cuota
        ).first()
        
        if not concepto_cuota:
            return RedirectResponse(
                url="/admin/pagos/procesar?error=no_concept",
                status_code=status.HTTP_302_FOUND
            )
        
        # Construir fecha_efectiva usando el año y mes del formulario
        # Esto permite registrar pagos históricos con la fecha correcta del período
        from datetime import date as date_class
        fecha_efectiva_calculada = date_class(año_aplicable, mes_aplicable, 15)  # Día 15 del mes especificado
        
        # Crear registro de pago
        nuevo_pago = RegistroFinancieroApartamento(
            apartamento_id=apartamento_id,
            concepto_id=concepto_cuota.id,
            tipo_movimiento=TipoMovimientoEnum.CREDITO.value,
            monto=monto_pago,
            fecha_efectiva=fecha_efectiva_calculada,  # Usar fecha calculada del período
            mes_aplicable=mes_aplicable,
            año_aplicable=año_aplicable,
            referencia_pago=referencia_pago or f"PAGO-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            descripcion_adicional=observaciones or f"Pago histórico {mes_aplicable:02d}/{año_aplicable}",
            fecha_creacion=datetime.now()
        )
        
        session.add(nuevo_pago)
        session.commit()
    
    return RedirectResponse(
        url="/admin/pagos/procesar?success=1",
        status_code=status.HTTP_302_FOUND
    )

@router.get("/reportes", response_class=HTMLResponse)
async def admin_pagos_reportes(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """Reportes del sistema de pagos"""
    # Usar mes y año actuales si no se especifican
    if not mes:
        mes = datetime.now().month
    if not año:
        año = datetime.now().year
    
    with db_manager.get_session_context() as session:
        # Obtener el concepto de cuota ordinaria
        concepto_cuota = session.exec(
            select(Concepto).where(Concepto.nombre.ilike("%cuota%ordinaria%administr%"))
        ).first()
        
        # Obtener todos los apartamentos con sus pagos
        apartamentos = session.exec(select(Apartamento)).all()
        
        reporte_apartamentos = []
        total_cargado = 0
        total_pagado = 0
        
        for apartamento in apartamentos:
            # Cargos del mes
            cargos = session.exec(
                select(func.sum(RegistroFinancieroApartamento.monto))
                .where(RegistroFinancieroApartamento.apartamento_id == apartamento.id)
                .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
                .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.DEBITO.value)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes)
                .where(RegistroFinancieroApartamento.año_aplicable == año)
            ).first() or 0
            
            # Pagos del mes
            pagos = session.exec(
                select(func.sum(RegistroFinancieroApartamento.monto))
                .where(RegistroFinancieroApartamento.apartamento_id == apartamento.id)
                .where(RegistroFinancieroApartamento.concepto_id == concepto_cuota.id)
                .where(RegistroFinancieroApartamento.tipo_movimiento == TipoMovimientoEnum.CREDITO.value)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes)
                .where(RegistroFinancieroApartamento.año_aplicable == año)
            ).first() or 0
            
            saldo = float(pagos) - float(cargos)
            estado = "Pagado" if saldo >= 0 else "Pendiente"
            
            reporte_apartamentos.append({
                "apartamento": apartamento,
                "cargos": float(cargos),
                "pagos": float(pagos),
                "saldo": saldo,
                "estado": estado
            })
            
            total_cargado += float(cargos)
            total_pagado += float(pagos)
        
        return templates.TemplateResponse(
            "admin/pagos_reportes.html",
            {
                "request": request,
                "mes_actual": mes,
                "año_actual": año,
                "reporte_apartamentos": reporte_apartamentos,
                "total_cargado": total_cargado,
                "total_pagado": total_pagado,
                "total_pendiente": total_cargado - total_pagado,
                "porcentaje_recaudacion": round((total_pagado / total_cargado * 100) if total_cargado > 0 else 0, 1)
            }
        )

@router.get("/generar-automatico", response_class=HTMLResponse)
async def admin_pagos_generar_automatico(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """Página para generación automática integrada (V3) - Cuotas + Intereses"""
    mes_actual = datetime.now().month
    año_actual = datetime.now().year
    
    with db_manager.get_session_context() as session:
        # Obtener información de procesamiento del mes actual
        control_actual = session.exec(
            select(ControlProcesamientoMensual)
            .where(ControlProcesamientoMensual.año == año_actual)
            .where(ControlProcesamientoMensual.mes == mes_actual)
            .where(ControlProcesamientoMensual.tipo_procesamiento == "CUOTAS_INTERESES")
        ).first()
        
        # Obtener historial de procesamientos recientes (últimos 6 meses)
        historial = []
        for i in range(6):
            mes_hist = mes_actual - i
            año_hist = año_actual
            if mes_hist <= 0:
                mes_hist += 12
                año_hist -= 1
            
            control_hist = session.exec(
                select(ControlProcesamientoMensual)
                .where(ControlProcesamientoMensual.año == año_hist)
                .where(ControlProcesamientoMensual.mes == mes_hist)
                .where(ControlProcesamientoMensual.tipo_procesamiento == "CUOTAS_INTERESES")
            ).first()
            
            historial.append({
                'mes': mes_hist,
                'año': año_hist,
                'procesado': control_hist is not None,
                'fecha_procesamiento': control_hist.fecha_procesamiento if control_hist else None,
                'cuotas_generadas': control_hist.cuotas_generadas if control_hist else 0,
                'intereses_generados': control_hist.intereses_generados if control_hist else 0,
                'monto_cuotas': control_hist.monto_cuotas if control_hist else 0,
                'monto_intereses': control_hist.monto_intereses if control_hist else 0
            })
        
        # Verificar configuraciones disponibles
        configuraciones = session.exec(
            select(CuotaConfiguracion)
            .where(CuotaConfiguracion.mes == mes_actual)
            .where(CuotaConfiguracion.año == año_actual)
        ).all()
        
        # Obtener última tasa de interés configurada
        tasa_interes = session.exec(
            select(TasaInteresMora)
            .order_by(TasaInteresMora.año.desc(), TasaInteresMora.mes.desc())
            .limit(1)
        ).first()
        
        return templates.TemplateResponse(
            "admin/pagos_generar_automatico.html",
            {
                "request": request,
                "mes_actual": mes_actual,
                "año_actual": año_actual,
                "control_actual": control_actual,
                "historial": historial,
                "configuraciones_disponibles": len(configuraciones),
                "tasa_interes": tasa_interes,
                "ya_procesado": control_actual is not None
            }
        )

@router.post("/generar-automatico")
async def generar_automatico(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)],
    mes: int = Form(...),
    año: int = Form(...)
):
    """Ejecutar generación automática V3 integrada"""
    from src.utils.generador_pagos import generar_cargos_mensuales
    
    try:
        # Ejecutar procesamiento usando nuestro generador existente
        resultado = generar_cargos_mensuales(año, mes)
        
        if resultado:
            return RedirectResponse(
                url=f"/admin/pagos/generar-automatico?info=already_processed&mes={mes}&año={año}",
                status_code=status.HTTP_302_FOUND
            )
        
        # Construir parámetros de respuesta
        params = [
            f"success=1",
            f"mes={mes}",
            f"año={año}",
            f"cuotas={resultado['cuotas_generadas']}",
            f"intereses={resultado['intereses_generados']}",
            f"monto_cuotas={resultado['monto_cuotas']}",
            f"monto_intereses={resultado['monto_intereses']}"
        ]
        
        if resultado['errores']:
            params.append(f"errores={len(resultado['errores'])}")
        
        return RedirectResponse(
            url=f"/admin/pagos/generar-automatico?{'&'.join(params)}",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/pagos/generar-automatico?error=processing&details={str(e)[:100]}",
            status_code=status.HTTP_302_FOUND
        )

@router.get("/status-procesamiento", response_class=HTMLResponse)
async def admin_pagos_status_procesamiento(
    request: Request,
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """Página de estado de procesamiento automático"""
    with db_manager.get_session_context() as session:
        # Obtener todos los procesamientos ordenados por fecha
        procesamientos = session.exec(
            select(ControlProcesamientoMensual)
            .where(ControlProcesamientoMensual.tipo_procesamiento == "CUOTAS_INTERESES")
            .order_by(ControlProcesamientoMensual.año.desc(), ControlProcesamientoMensual.mes.desc())
            .limit(24)  # Últimos 24 meses
        ).all()
        
        # Estadísticas generales
        total_cuotas = sum(p.cuotas_generadas for p in procesamientos)
        total_intereses = sum(p.intereses_generados for p in procesamientos)
        total_monto = sum(p.monto_cuotas + p.monto_intereses for p in procesamientos)
        meses_procesados = len(procesamientos)
        
        # Último procesamiento
        ultimo_procesamiento = procesamientos[0] if procesamientos else None
        
        return templates.TemplateResponse(
            "admin/pagos_status_procesamiento.html",
            {
                "request": request,
                "procesamientos": procesamientos,
                "total_cuotas": total_cuotas,
                "total_intereses": total_intereses,
                "total_monto": total_monto,
                "meses_procesados": meses_procesados,
                "ultimo_procesamiento": ultimo_procesamiento
            }
        )

@router.post("/pago-automatico")
async def procesar_pago_automatico(
    request: Request,
    session: Annotated[Session, Depends(db_manager.get_session)],
    user: Annotated[Usuario, Depends(admin_required_web)],
    apartamento_id: int = Form(...),
    monto_pago: float = Form(...),
    referencia_pago: Optional[str] = Form(None),
    documento_soporte: UploadFile = File(...)
):
    """Procesar pago automático con distribución inteligente"""
    from src.utils.pago_automatico import PagoAutomaticoService
    
    try:
        # Validar monto
        if monto_pago <= 0:
            return RedirectResponse(
                url="/admin/pagos/procesar?error=invalid_amount",
                status_code=status.HTTP_302_FOUND
            )
        
        # Validar archivo obligatorio
        if not documento_soporte or documento_soporte.size == 0:
            return RedirectResponse(
                url="/admin/pagos/procesar?error=no_file",
                status_code=status.HTTP_302_FOUND
            )
        
        # Validar tipo de archivo
        allowed_types = {
            'application/pdf': '.pdf',
            'image/jpeg': '.jpg',
            'image/png': '.png',
            'image/gif': '.gif',
            'image/webp': '.webp'
        }
        
        if documento_soporte.content_type not in allowed_types:
            return RedirectResponse(
                url="/admin/pagos/procesar?error=invalid_file_type",
                status_code=status.HTTP_302_FOUND
            )
        
        # Validar tamaño (5MB máximo)
        if documento_soporte.size > 5 * 1024 * 1024:
            return RedirectResponse(
                url="/admin/pagos/procesar?error=file_too_large",
                status_code=status.HTTP_302_FOUND
            )
        
        try:
            # Leer contenido del archivo y obtener extensión
            file_content = await documento_soporte.read()
            file_extension = allowed_types[documento_soporte.content_type]
            
        except Exception as e:
            print(f"Error leyendo archivo: {str(e)}")
            return RedirectResponse(
                url="/admin/pagos/procesar?error=upload_failed",
                status_code=status.HTTP_302_FOUND
            )
        
        # Procesar pago automático primero sin documento
        servicio_pago = PagoAutomaticoService()
        resultado = servicio_pago.procesar_pago_automatico(
            session=session,
            apartamento_id=apartamento_id,
            monto_pago=monto_pago,
            referencia=referencia_pago,
            documento_soporte_url=None  # Por ahora None, lo actualizaremos después
        )
        
        if resultado.get("error"):
            return RedirectResponse(
                url=f"/admin/pagos/procesar?error=processing&details={resultado['error']}",
                status_code=status.HTTP_302_FOUND
            )
        
        # Subir archivo con el ID del registro creado
        try:
            # Generar nombre del archivo con los datos del registro
            registro_id = resultado['registro_id']
            mes_aplicable = resultado['mes_aplicable']
            año_aplicable = resultado['año_aplicable']
            
            file_name = f"{registro_id}_{apartamento_id}_{año_aplicable}{mes_aplicable:02d}{file_extension}"
            file_path = f"ingresos/{file_name}"
            
            # Subir a Supabase
            response = supabase.storage.from_(SUPABASE_BUCKET).upload(
                file_path,
                file_content,
                file_options={"content-type": documento_soporte.content_type}
            )
            
            if hasattr(response, 'error') and response.error:
                print(f"Error subiendo archivo: {response.error}")
                # No retornamos error aquí porque el pago ya se procesó exitosamente
                print(f"Pago procesado exitosamente pero no se pudo subir el documento")
            else:
                # Generar URL pública y actualizar el registro
                documento_url = f"{SUPABASE_URL}/storage/v1/object/public/{SUPABASE_BUCKET}/{file_path}"
                
                # Actualizar el registro con la URL del documento
                registro_pago = session.get(RegistroFinancieroApartamento, registro_id)
                if registro_pago:
                    registro_pago.documento_soporte_path = documento_url
                    session.add(registro_pago)
                    session.commit()
            
        except Exception as e:
            print(f"Error subiendo archivo: {str(e)}")
            # No retornamos error aquí porque el pago ya se procesó exitosamente
        
        # Construir parámetros de respuesta
        params = [
            "success=1",
            "auto_payment=1",
            f"monto_procesado={resultado['monto_procesado']}",
            f"pagos_realizados={len(resultado['pagos_realizados'])}",
            f"apartamento_id={apartamento_id}"
        ]
        
        return RedirectResponse(
            url=f"/admin/pagos/procesar?{'&'.join(params)}",
            status_code=status.HTTP_302_FOUND
        )
        
    except Exception as e:
        return RedirectResponse(
            url=f"/admin/pagos/procesar?error=processing&details={str(e)[:100]}",
            status_code=status.HTTP_302_FOUND
        )

@router.get("/resumen-deuda/{apartamento_id}")
async def obtener_resumen_deuda(
    apartamento_id: int,
    session: Annotated[Session, Depends(db_manager.get_session)],
    user: Annotated[Usuario, Depends(admin_required_web)]
):
    """API endpoint para obtener resumen de deuda de un apartamento"""
    from src.utils.pago_automatico import PagoAutomaticoService
    
    try:
        servicio_pago = PagoAutomaticoService()
        resumen = servicio_pago.obtener_resumen_deuda(session, apartamento_id)
        return resumen
    except Exception as e:
        return {"error": str(e)}
