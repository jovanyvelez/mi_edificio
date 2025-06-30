"""
Utilidades para propietarios - Cálculo de saldos y estado de cuenta
"""
from typing import List, Dict, Any
from sqlmodel import Session, select, func, case
from datetime import datetime, date
from src.models import (
    db_manager, 
    RegistroFinancieroApartamento as rfa, 
    Apartamento, 
    Propietario,
    Concepto,
    Usuario,
    TipoMovimientoEnum
)


async def get_saldo_apartamento(apartamento_id: int) -> List[Dict[str, Any]]:
    """
    Calcula el saldo para un apartamento específico sumando los créditos
    y restando los débitos, agrupado por mes/año.
    """
    # 1. Define la expresión CASE para asignar signo al monto
    monto_con_signo = case(
        (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
        (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
        else_=0
    )

    # 2. Construye la consulta completa
    statement = select(
        rfa.año_aplicable,
        rfa.mes_aplicable,
        func.coalesce(
            func.sum(monto_con_signo),
            0
        ).label("saldo")
    ).where(rfa.apartamento_id == apartamento_id).group_by(
        rfa.año_aplicable, rfa.mes_aplicable
    ).order_by(rfa.año_aplicable, rfa.mes_aplicable)     

    # 3. Ejecuta la consulta y obtén el resultado
    with db_manager.get_session_context() as session:
        results = session.exec(statement).all()
    
    # 4. Convertir resultados a lista de diccionarios
    saldos = []
    saldo_acumulado = 0.0
    print(apartamento_id)
    for dato in results:
        año, mes, saldo = dato
        print(f"Año: {año}, Mes: {mes}, Saldo: {saldo}")
 


    for result in results:
        saldo_periodo = float(result.saldo)
        saldo_acumulado += saldo_periodo
        
        saldos.append({
            'año': result.año_aplicable,
            'mes': result.mes_aplicable,
            'saldo_periodo': saldo_periodo,
            'saldo_acumulado': saldo_acumulado,
            'nombre_mes': [
                '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
            ][result.mes_aplicable]
        })
    return saldos


async def get_estado_cuenta_completo(propietario_id: int) -> Dict[str, Any]:
    """
    Obtiene el estado de cuenta completo de un propietario con todos sus apartamentos
    """
    with db_manager.get_session_context() as session:
        # Obtener propietario
        propietario = session.get(Propietario, propietario_id)
        if not propietario:
            return {"error": "Propietario no encontrado"}
        
        # Obtener apartamentos del propietario
        apartamentos = session.exec(
            select(Apartamento).where(Apartamento.propietario_id == propietario_id)
        ).all()
        
        if not apartamentos:
            return {
                "propietario": propietario,
                "apartamentos": [],
                "resumen": {
                    "total_apartamentos": 0,
                    "saldo_total": 0.0,
                    "apartamentos_al_dia": 0,
                    "apartamentos_en_mora": 0
                }
            }
        
        # Calcular estado para cada apartamento
        apartamentos_detalle = []
        saldo_total_general = 0.0
        apartamentos_al_dia = 0
        apartamentos_en_mora = 0
        
        for apartamento in apartamentos:
            # Obtener saldos del apartamento
            saldos = await get_saldo_apartamento(apartamento.id)
            
            # Calcular saldo actual
            saldo_actual = saldos[-1]["saldo_acumulado"] if saldos else 0.0
            saldo_total_general += saldo_actual
            
            # Determinar estado (al día o en mora)
            if saldo_actual <= 0:  # Saldo negativo o cero = está al día
                apartamentos_al_dia += 1
                estado = "al_dia"
            else:
                apartamentos_en_mora += 1
                estado = "en_mora"
            
            # Obtener últimos movimientos
            ultimos_movimientos = session.exec(
                select(rfa, Concepto)
                .join(Concepto, rfa.concepto_id == Concepto.id)
                .where(rfa.apartamento_id == apartamento.id)
                .order_by(rfa.año_aplicable.desc(), rfa.mes_aplicable.desc())
                .limit(5)
            ).all()
            
            apartamentos_detalle.append({
                "apartamento": apartamento,
                "saldo_actual": saldo_actual,
                "estado": estado,
                "saldos_historicos": saldos,
                "ultimos_movimientos": [
                    {
                        "registro": mov[0],
                        "concepto": mov[1]
                    } for mov in ultimos_movimientos
                ]
            })
        
        return {
            "propietario": propietario,
            "apartamentos": apartamentos_detalle,
            "resumen": {
                "total_apartamentos": len(apartamentos),
                "saldo_total": saldo_total_general,
                "apartamentos_al_dia": apartamentos_al_dia,
                "apartamentos_en_mora": apartamentos_en_mora
            }
        }


async def get_saldo_apartamento_sin_concepto_actual(apartamento_id: int, concepto_excluir: int, año_actual: int, mes_actual: int) -> List[Dict[str, Any]]:
    """
    Calcula el saldo para un apartamento específico excluyendo DÉBITOS de un concepto específico
    para el año y mes actual al momento de la consulta.
    """
    # 1. Define la expresión CASE para asignar signo al monto
    # Excluir DÉBITOS del concepto especificado para el año/mes actual
    monto_con_signo = case(
        # Si es DÉBITO del concepto a excluir en año/mes actual, no contarlo (0)
        (
            (rfa.tipo_movimiento == 'DEBITO') & 
            (rfa.concepto_id == concepto_excluir) &
            (rfa.año_aplicable == año_actual) &
            (rfa.mes_aplicable == mes_actual),
            0
        ),
        # Si es otro DÉBITO, sumarlo normalmente
        (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
        # Si es CRÉDITO, restarlo
        (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
        else_=0
    )

    # 2. Construye la consulta completa
    statement = select(
        rfa.año_aplicable,
        rfa.mes_aplicable,
        func.coalesce(
            func.sum(monto_con_signo),
            0
        ).label("saldo")
    ).where(rfa.apartamento_id == apartamento_id).group_by(
        rfa.año_aplicable, rfa.mes_aplicable
    ).order_by(rfa.año_aplicable, rfa.mes_aplicable)     

    # 3. Ejecuta la consulta y obtén el resultado
    with db_manager.get_session_context() as session:
        results = session.exec(statement).all()
    
    # 4. Convertir resultados a lista de diccionarios
    saldos = []
    saldo_acumulado = 0.0
    
    for dato in results:
        saldo_acumulado += float(dato.saldo)
        saldos.append({
            "año": dato.año_aplicable,
            "mes": dato.mes_aplicable,
            "saldo_mes": float(dato.saldo),
            "saldo_acumulado": saldo_acumulado
        })
    
    return saldos


async def get_cartera_morosa() -> List[Dict[str, Any]]:
    """
    Obtiene información de la cartera morosa de todo el edificio
    Excluye DÉBITOS del concepto "1" para el año y mes actual al momento de la consulta.
    
    Esta exclusión permite que la cartera morosa no muestre como deuda los cargos
    del concepto 1 (generalmente cuota de administración) del mes actual,
    dando tiempo a los propietarios para realizar el pago antes de ser considerados morosos.
    """
    # Obtener fecha actual
    fecha_actual = datetime.now()
    año_actual = fecha_actual.year
    mes_actual = fecha_actual.month
    
    with db_manager.get_session_context() as session:
        # Obtener todos los apartamentos con sus propietarios
        apartamentos = session.exec(
            select(Apartamento, Propietario)
            .join(Propietario, isouter=True)  # LEFT JOIN
            .order_by(Apartamento.identificador)
        ).all()
        
        cartera_morosa = []
        
        for apartamento_row, propietario_row in apartamentos:
            if apartamento_row.id:
                # Calcular saldo del apartamento excluyendo débitos del concepto 1 para año/mes actual
                saldos = await get_saldo_apartamento_sin_concepto_actual(
                    apartamento_row.id, 
                    concepto_excluir=1, 
                    año_actual=año_actual, 
                    mes_actual=mes_actual
                )
                saldo_actual = saldos[-1]["saldo_acumulado"] if saldos else 0.0
                
                # Solo incluir si tiene saldo pendiente (mora)
                if saldo_actual > 0:
                    cartera_morosa.append({
                        "apartamento": apartamento_row,
                        "propietario": propietario_row,
                        "saldo_pendiente": saldo_actual,
                        "meses_mora": len([s for s in saldos if s["saldo_acumulado"] > 0])
                    })
        
        # Ordenar por saldo pendiente descendente
        cartera_morosa.sort(key=lambda x: x["saldo_pendiente"], reverse=True)
        
        return cartera_morosa


async def get_apartamentos_propietario(usuario_email: str) -> List[int]:
    """
    Obtiene los IDs de apartamentos que pertenecen a un propietario basado en su email de usuario
    """
    with db_manager.get_session_context() as session:
        # Buscar el propietario asociado al usuario
        resultado = session.exec(
            select(Apartamento.id)
            .join(Propietario, Apartamento.propietario_id == Propietario.id)
            .join(Usuario, Usuario.propietario_id == Propietario.id)
            .where(Usuario.email == usuario_email)
        ).all()
        
        return list(resultado)
