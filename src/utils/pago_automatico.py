"""
Servicio para procesamiento automático de pagos
Aplica lógica de distribución inteligente de pagos
"""
from datetime import datetime, date
from typing import List, Dict, Tuple, Optional
from sqlmodel import Session, select
from decimal import Decimal, ROUND_HALF_UP
from src.models import (
    RegistroFinancieroApartamento, Apartamento, Concepto,
    TipoMovimientoEnum, db_manager
)

class PagoAutomaticoService:
    """Servicio para procesar pagos automáticamente con lógica de distribución"""
    
    def __init__(self):
        self.concepto_cuota_id = 1  # Cuota Ordinaria Administración
        self.concepto_pago_cuota_id = 5  # Pago de Cuota
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
        """Obtiene los registros pendientes de pago ordenados por prioridad"""
        
        # Obtener todos los registros del apartamento
        registros = session.exec(
            select(RegistroFinancieroApartamento)
            .where(RegistroFinancieroApartamento.apartamento_id == apartamento_id)
            .order_by(
                RegistroFinancieroApartamento.año_aplicable,
                RegistroFinancieroApartamento.mes_aplicable,
                RegistroFinancieroApartamento.concepto_id
            )
        ).all()
        
        # Agrupar por año/mes/concepto para calcular saldos
        saldos_por_periodo = {}
        
        for registro in registros:
            key = (registro.año_aplicable, registro.mes_aplicable, registro.concepto_id)
            
            if key not in saldos_por_periodo:
                saldos_por_periodo[key] = {
                    'año': registro.año_aplicable,
                    'mes': registro.mes_aplicable,
                    'concepto_id': registro.concepto_id,
                    'debitos': 0.0,
                    'creditos': 0.0,
                    'saldo': 0.0
                }
            
            if registro.tipo_movimiento == TipoMovimientoEnum.DEBITO.value:
                saldos_por_periodo[key]['debitos'] += float(registro.monto)
            else:  # CREDITO
                saldos_por_periodo[key]['creditos'] += float(registro.monto)
            
            saldos_por_periodo[key]['saldo'] = (
                saldos_por_periodo[key]['debitos'] - saldos_por_periodo[key]['creditos']
            )
        
        # Filtrar solo los que tienen saldo pendiente > 0
        pendientes = []
        for key, saldo_info in saldos_por_periodo.items():
            if saldo_info['saldo'] > 0:
                pendientes.append(saldo_info)
        
        # Ordenar por prioridad: año, mes, tipo (intereses primero, luego cuotas)
        def prioridad_concepto(concepto_id):
            if concepto_id == self.concepto_interes_id:  # Intereses
                return 1
            elif concepto_id == self.concepto_cuota_id:  # Cuotas
                return 2
            else:
                return 3
        
        pendientes.sort(key=lambda x: (x['año'], x['mes'], prioridad_concepto(x['concepto_id'])))
        
        return pendientes
    
    def _distribuir_pago(self, session: Session, apartamento_id: int, monto_disponible: float,
                        fecha_pago: date, referencia: str, registros_pendientes: List[Dict]) -> Dict:
        """Distribuye el pago entre los registros pendientes"""
        
        resultado = {
            "success": True,
            "monto_original": monto_disponible,
            "monto_procesado": 0.0,
            "monto_restante": monto_disponible,
            "pagos_realizados": [],
            "mensaje": ""
        }
        
        for registro_pendiente in registros_pendientes:
            if monto_disponible <= 0:
                break
                
            # Convertir saldo_pendiente a float para cálculos
            saldo_pendiente = float(registro_pendiente['saldo'])
            monto_a_pagar = min(monto_disponible, saldo_pendiente)
            
            # Determinar el concepto de pago
            concepto_pago_id = self._obtener_concepto_pago(registro_pendiente['concepto_id'])
            
            # Crear registro de pago - convertir monto a Decimal para la BD
            nuevo_pago = RegistroFinancieroApartamento(
                apartamento_id=apartamento_id,
                concepto_id=concepto_pago_id,
                tipo_movimiento=TipoMovimientoEnum.CREDITO,
                monto=self._to_decimal(monto_a_pagar),
                fecha_efectiva=date(registro_pendiente['año'], registro_pendiente['mes'], 15),
                mes_aplicable=registro_pendiente['mes'],
                año_aplicable=registro_pendiente['año'],
                referencia_pago=referencia,
                descripcion_adicional=f"Pago automático {registro_pendiente['mes']:02d}/{registro_pendiente['año']}",
                fecha_registro=datetime.now()
            )
            
            session.add(nuevo_pago)
            
            # Actualizar montos (asegurándonos de que sean float)
            monto_disponible -= float(monto_a_pagar)
            resultado["monto_procesado"] += float(monto_a_pagar)
            
            # Registrar el pago realizado
            resultado["pagos_realizados"].append({
                "concepto_id": concepto_pago_id,
                "periodo": f"{registro_pendiente['mes']:02d}/{registro_pendiente['año']}",
                "monto": float(monto_a_pagar),
                "tipo": "Interés" if registro_pendiente['concepto_id'] == self.concepto_interes_id else "Cuota"
            })
        
        resultado["monto_restante"] = monto_disponible
        
        # Si queda dinero, registrar como pago en exceso
        if monto_disponible > 0:
            exceso_result = self._registrar_pago_exceso(session, apartamento_id, monto_disponible,
                                                      fecha_pago, referencia)
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
        
        pago_exceso = RegistroFinancieroApartamento(
            apartamento_id=apartamento_id,
            concepto_id=self.concepto_exceso_id,
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
        intereses = [p for p in pagos if p["tipo"] == "Interés"]
        cuotas = [p for p in pagos if p["tipo"] == "Cuota"]
        excesos = [p for p in pagos if p["tipo"] == "Exceso"]
        
        if intereses:
            total_intereses = sum(p["monto"] for p in intereses)
            mensaje_parts.append(f"Intereses: ${total_intereses:,.2f} ({len(intereses)} períodos)")
        
        if cuotas:
            total_cuotas = sum(p["monto"] for p in cuotas)
            mensaje_parts.append(f"Cuotas: ${total_cuotas:,.2f} ({len(cuotas)} períodos)")
        
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
                "total_intereses": 0.0,
                "total_cuotas": 0.0,
                "periodos_pendientes": 0,
                "detalle": []
            }
        
        # Convertir a float para evitar problemas con Decimal
        total_intereses = float(sum(r['saldo'] for r in registros_pendientes 
                                   if r['concepto_id'] == self.concepto_interes_id))
        total_cuotas = float(sum(r['saldo'] for r in registros_pendientes 
                                if r['concepto_id'] == self.concepto_cuota_id))
        
        return {
            "total_deuda": total_intereses + total_cuotas,
            "total_intereses": total_intereses,
            "total_cuotas": total_cuotas,
            "periodos_pendientes": len(registros_pendientes),
            "detalle": registros_pendientes
        }
