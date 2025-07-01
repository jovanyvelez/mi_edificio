"""
Servicio para procesamiento automático de pagos - Versión Simplificada
Registra pagos directamente sin distribución compleja
"""
from datetime import datetime, date
from typing import Dict
from sqlmodel import Session
from decimal import Decimal, ROUND_HALF_UP
from src.models import (
    RegistroFinancieroApartamento as rfa, Apartamento,
    TipoMovimientoEnum
)


class PagoAutomaticoService:
    """Servicio simplificado para registrar pagos automáticamente"""
    
    def __init__(self):
        self.concepto_pago_cuota_id = 5  # Pago de Cuota (concepto estándar para pagos)
    
    def _to_decimal(self, value: float) -> Decimal:
        """Convierte un float a Decimal con la precisión correcta para la BD"""
        if isinstance(value, Decimal):
            return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return Decimal(str(round(value, 2))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    
    def procesar_pago_automatico(self, session: Session, apartamento_id: int, monto_pago: float, 
                                fecha_pago: date = None, referencia: str = None) -> Dict:
        """
        Registra un pago automáticamente de forma simple
        
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
        
        # Verificar que el apartamento existe
        apartamento = session.get(Apartamento, apartamento_id)
        if not apartamento:
            return {
                "error": "Apartamento no encontrado", 
                "success": False,
                "pagos_realizados": []
            }
        
        try:
            # Crear registro de pago simple
            nuevo_pago = rfa(
                apartamento_id=apartamento_id,
                concepto_id=self.concepto_pago_cuota_id,  # Concepto 5: Pago de Cuota
                tipo_movimiento=TipoMovimientoEnum.CREDITO,
                monto=self._to_decimal(monto_pago),
                fecha_efectiva=fecha_pago,
                mes_aplicable=fecha_pago.month,    # Mes actual de la fecha de pago
                año_aplicable=fecha_pago.year,     # Año actual de la fecha de pago
                referencia_pago=referencia,
                descripcion_adicional=f"Pago automático ${monto_pago:,.2f}",
                fecha_registro=datetime.now()
            )
            
            session.add(nuevo_pago)
            session.commit()
            
            return {
                "success": True,
                "monto_procesado": monto_pago,
                "fecha_pago": fecha_pago.strftime('%Y-%m-%d'),
                "mes_aplicable": fecha_pago.month,
                "año_aplicable": fecha_pago.year,
                "referencia": referencia,
                "mensaje": f"Pago registrado exitosamente: ${monto_pago:,.2f}",
                "pagos_realizados": [{
                    "concepto_id": self.concepto_pago_cuota_id,
                    "periodo": f"{fecha_pago.month:02d}/{fecha_pago.year}",
                    "monto": monto_pago,
                    "tipo": "Pago",
                    "descripcion": f"Pago automático ${monto_pago:,.2f}"
                }]
            }
            
        except Exception as e:
            session.rollback()
            return {
                "error": f"Error al registrar el pago: {str(e)}",
                "success": False,
                "pagos_realizados": []
            }
