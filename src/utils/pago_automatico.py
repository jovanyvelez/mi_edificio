"""
Servicio para procesamiento automático de pagos
Aplica lógica de distribución inteligente de pagos
"""
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from sqlmodel import Session, select
from sqlalchemy import func, case
from decimal import Decimal, ROUND_HALF_UP
from src.models import (
    RegistroFinancieroApartamento as rfa, Apartamento, Concepto,
    TipoMovimientoEnum, db_manager
)


class PagoAutomaticoService:
    """Servicio para procesar pagos automáticamente con lógica de distribución"""
    
    def __init__(self):
        self.concepto_cuota_id = 1  # Cuota Ordinaria Administración
        self.concepto_pago_cuota_id = 5  # Pago de Cuota (abono)
        self.concepto_exceso_id = 15  # Pago en Exceso
        self.concepto_interes_id = 3  # Interés por Mora
        self.concepto_pago_interes_id = 4  # Pago de intereses por mora
        self.concepto_exceso_id = 15  # Pago en Exceso
    
    def _to_decimal(self, value: float) -> Decimal:
        """Convierte un float a Decimal con la precisión correcta para la BD"""
        if isinstance(value, Decimal):
            return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return Decimal(str(round(value, 2))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def procesar_pago_automatico(self, session: Session, apartamento_id: int, monto_pago: float, 
                                fecha_pago: date = None, referencia: str = None) -> Dict:
        """
        Procesa un pago automáticamente distribuyendo el dinero según prioridades
        
        Args:
            session: Sesión de base de datos
            apartamento_id: ID del apartamento
            monto_pago: Monto total del pago
            fecha_pago: Fecha del pago (opcional, usa fecha actual si no se especifica)
            referencia: Referencia del pago (opcional)
            
        Returns:
            Dict con el resultado del procesamiento
        """
        if fecha_pago is None:
            fecha_pago = date.today()
            
        if referencia is None:
            referencia = f"PAGO-AUTO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Obtener apartamento
        apartamento = session.get(Apartamento, apartamento_id)
        if not apartamento:
            return {"error": "Apartamento no encontrado"}
        
        # Obtener todos los registros pendientes del apartamento
        registros_pendientes = self._obtener_registros_pendientes(session, apartamento_id)
        
        if not registros_pendientes:
            # No hay registros pendientes, el pago es exceso
            return self._registrar_pago_exceso(session, apartamento_id, monto_pago, 
                                             fecha_pago, referencia)
        
        # Procesar distribución del pago
        resultado = self._distribuir_pago(session, apartamento_id, monto_pago, 
                                        fecha_pago, referencia, registros_pendientes)
        
        return resultado
    
    def _obtener_registros_pendientes(self, session: Session, apartamento_id: int) -> List[Dict]:
        """
        Obtiene períodos con saldo pendiente usando consulta SQL eficiente
        Retorna lista de diccionarios con año, mes, saldo y registro_referencia
        """
        try:
            # Statement SQL eficiente para obtener saldos por período
            monto_con_signo = case(
                (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
                (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
                else_=0
            )

            # 2. Construye la consulta completa
            stmt = select(
                rfa.año_aplicable.label("anio"),
                rfa.mes_aplicable.label("mes"),
                func.coalesce(
                    func.sum(monto_con_signo),
                    0
                ).label("saldo"),
                func.min(rfa.id).label('registro_referencia')  # Referencia del registro
                ).where(
                    rfa.apartamento_id == apartamento_id
                ).group_by(
                    rfa.año_aplicable, rfa.mes_aplicable
                ).having(
                    func.coalesce(func.sum(monto_con_signo), 0) > 0  # Solo saldos positivos
                ).order_by(
                    rfa.año_aplicable, rfa.mes_aplicable
                )
            

            result = session.exec(stmt).all()
            
            # Convertir a lista de diccionarios
            periodos = []
            for row in result:
                periodos.append({
                    'año': int(row.anio),
                    'mes': int(row.mes),
                    'saldo': float(row.saldo),
                    'registro_referencia': row.registro_referencia
                })
            
            return periodos
            
        except Exception as e:
            print(f"❌ Error obteniendo períodos con saldo pendiente: {e}")
            return []
    
    def _distribuir_pago(self, session: Session, apartamento_id: int, monto_disponible: float,
                        fecha_pago: date, referencia: str, registros_pendientes: List[Dict]) -> Dict:
        """
        Distribuye el pago entre los períodos pendientes creando registros de abono (concepto 5)
        para cada período con saldo, hasta agotar el monto pagado
        """
        
        resultado = {
            "success": True,
            "monto_original": monto_disponible,
            "monto_procesado": 0.0,
            "monto_restante": monto_disponible,
            "pagos_realizados": [],
            "mensaje": ""
        }
        
        # Procesar cada período pendiente en orden cronológico
        for periodo in registros_pendientes:
            if monto_disponible <= 0:
                break
                
            saldo_pendiente = float(periodo['saldo'])
            monto_a_pagar = min(monto_disponible, saldo_pendiente)
            
            # Crear registro de abono (concepto 5) para este período específico
            nuevo_pago = rfa(
                apartamento_id=apartamento_id,
                concepto_id=self.concepto_pago_cuota_id,  # Concepto 5: Pago de Cuota (abono)
                tipo_movimiento=TipoMovimientoEnum.CREDITO,
                monto=self._to_decimal(monto_a_pagar),
                fecha_efectiva=fecha_pago,  # Fecha real del pago
                mes_aplicable=periodo['mes'],    # Mes al que se aplica el abono
                año_aplicable=periodo['año'],    # Año al que se aplica el abono
                referencia_pago=referencia,
                descripcion_adicional=f"Abono período {periodo['mes']:02d}/{periodo['año']} - Pago automático",
                fecha_registro=datetime.now()
            )
            
            session.add(nuevo_pago)
            
            # Actualizar montos disponibles
            monto_disponible -= monto_a_pagar
            resultado["monto_procesado"] += monto_a_pagar
            
            # Registrar el pago realizado para el resultado
            resultado["pagos_realizados"].append({
                "concepto_id": self.concepto_pago_cuota_id,
                "periodo": f"{periodo['mes']:02d}/{periodo['año']}",
                "monto": monto_a_pagar,
                "tipo": "Abono Cuota",
                "saldo_anterior": saldo_pendiente,
                "saldo_restante": saldo_pendiente - monto_a_pagar
            })
        
        resultado["monto_restante"] = monto_disponible
        
        # Si queda dinero después de abonar a todos los períodos pendientes, registrar como pago en exceso
        if monto_disponible > 0:
            pago_exceso = rfa(
                apartamento_id=apartamento_id,
                concepto_id=self.concepto_exceso_id,  # Concepto 15: Pago en Exceso
                tipo_movimiento=TipoMovimientoEnum.CREDITO,
                monto=self._to_decimal(monto_disponible),
                fecha_efectiva=fecha_pago,
                mes_aplicable=fecha_pago.month,
                año_aplicable=fecha_pago.year,
                referencia_pago=referencia,
                descripcion_adicional=f"Pago en exceso - sobra tras abonar períodos pendientes",
                fecha_registro=datetime.now()
            )
            
            session.add(pago_exceso)
            
            resultado["pagos_realizados"].append({
                "concepto_id": self.concepto_exceso_id,
                "periodo": f"{fecha_pago.month:02d}/{fecha_pago.year}",
                "monto": monto_disponible,
                "tipo": "Exceso"
            })
            resultado["monto_procesado"] += monto_disponible
            resultado["monto_restante"] = 0
        
        # Crear mensaje descriptivo
        resultado["mensaje"] = self._crear_mensaje_resultado(resultado)
        
        session.commit()
        return resultado
    
    def _obtener_concepto_pago(self, concepto_cargo_id: int) -> int:
        """Obtiene el concepto de pago correspondiente al concepto de cargo"""
        if concepto_cargo_id == self.concepto_cuota_id:  # Cuota
            return self.concepto_pago_cuota_id
        elif concepto_cargo_id == self.concepto_interes_id:  # Interés
            return self.concepto_pago_interes_id
        else:
            return self.concepto_pago_cuota_id  # Por defecto
    
    def _registrar_pago_exceso(self, session: Session, apartamento_id: int, monto: float,
                              fecha_pago: date, referencia: str) -> Dict:
        """Registra un pago en exceso"""
        
        pago_exceso = rfa(
            apartamento_id=apartamento_id,
            concepto_id=self.concepto_exceso_id,  # Concepto 15: Pago en Exceso
            tipo_movimiento=TipoMovimientoEnum.CREDITO,
            monto=self._to_decimal(monto),
            fecha_efectiva=fecha_pago,
            mes_aplicable=fecha_pago.month,
            año_aplicable=fecha_pago.year,
            referencia_pago=referencia,
            descripcion_adicional=f"Pago en exceso",
            fecha_registro=datetime.now()
        )
        
        session.add(pago_exceso)
        session.commit()
        
        return {
            "success": True,
            "monto_original": monto,
            "monto_procesado": monto,
            "monto_restante": 0,
            "pagos_realizados": [{
                "concepto_id": self.concepto_exceso_id,
                "periodo": f"{fecha_pago.month:02d}/{fecha_pago.year}",
                "monto": monto,
                "tipo": "Exceso"
            }],
            "mensaje": f"Pago registrado como exceso: ${monto:,.2f}"
        }
    
    def _crear_mensaje_resultado(self, resultado: Dict) -> str:
        """Crea un mensaje descriptivo del resultado"""
        pagos = resultado["pagos_realizados"]
        
        if not pagos:
            return "No se realizaron pagos"
        
        mensaje_parts = []
        abonos = [p for p in pagos if p["tipo"] == "Abono Cuota"]
        excesos = [p for p in pagos if p["tipo"] == "Exceso"]
        
        if abonos:
            total_abonos = sum(p["monto"] for p in abonos)
            mensaje_parts.append(f"Abonos: ${total_abonos:,.2f} ({len(abonos)} períodos)")
        
        if excesos:
            total_excesos = sum(p["monto"] for p in excesos)
            mensaje_parts.append(f"Exceso: ${total_excesos:,.2f}")
        
        return " | ".join(mensaje_parts)
    
    def obtener_resumen_deuda(self, session: Session, apartamento_id: int) -> Dict:
        """Obtiene un resumen de la deuda del apartamento"""
        registros_pendientes = self._obtener_registros_pendientes(session, apartamento_id)
        
        if not registros_pendientes:
            return {
                "total_deuda": 0.0,
                "periodos_pendientes": 0,
                "detalle": []
            }
        
        # Calcular total de deuda de todos los períodos pendientes
        total_deuda = sum(r['saldo'] for r in registros_pendientes)
        
        return {
            "total_deuda": float(total_deuda),
            "periodos_pendientes": len(registros_pendientes),
            "detalle": registros_pendientes
        }
