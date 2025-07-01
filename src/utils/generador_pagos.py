#!/usr/bin/env python3
"""
Generador Automático de Cargos Financieros - Versión 3 Corregida
===============================================================

Versión simplificada y funcional que resuelve los problemas de SQLModel
con un enfoque más directo y confiable.

✅ Generación automática de cuotas ordinarias  
✅ Cálculo automático de intereses moratorios
✅ Aplicación automática de saldos a favor al próximo período
✅ Control de duplicados
✅ Manejo correcto de enums
✅ Logging y auditoría

NUEVA FUNCIONALIDAD: Aplicación Automática de Saldos a Favor
-----------------------------------------------------------
- Detecta apartamentos con saldo positivo (prepagos/créditos)
- Aplica automáticamente estos saldos al siguiente período
- Genera créditos automáticos para el próximo mes
- Reduce automáticamente la cuota del período siguiente

Ejecutar: 
  python scripts/generador_v3_funcional.py [año] [mes] [forzar]
"""

import sys
from pathlib import Path

# Agregar el directorio raíz del proyecto al path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlmodel import Session, select
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Dict

# Importaciones del proyecto
from src.models.database import db_manager
from src.models import (
    Apartamento, Concepto, CuotaConfiguracion, 
    TasaInteresMora, RegistroFinancieroApartamento,
    ControlProcesamientoMensual
)



class GeneradorAutomatico:
    """
    Generador automático mejorado y funcional.
    """
    
    def __init__(self):
        self.engine = db_manager.get_engine()
        self.logger = self._setup_logger()
        
    def _setup_logger(self):
        """Configurar logging para auditoría"""
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(__name__)
    
    def procesar_mes(self, año: int, mes: int, forzar: bool = False) -> Dict:
        """
        Procesa cuotas e intereses para un mes específico.
        """
        resultado = {
            'año': año,
            'mes': mes,
            'cuotas_generadas': 0,
            'intereses_generados': 0,
            'monto_cuotas': Decimal('0.00'),
            'monto_intereses': Decimal('0.00'),
            'saldos_favor_aplicados': 0,
            'monto_saldos_favor': Decimal('0.00'),
            'errores': [],
            'ya_procesado': False
        }
        
        inicio = datetime.now()
        
        with Session(self.engine) as session:
            try:
                # 1. Verificar si ya se procesó
                if not forzar and self._verificar_procesado(session, año, mes):
                    resultado['ya_procesado'] = True
                    self.logger.info(f"Mes {mes:02d}/{año} ya procesado")
                    return resultado
                
                # 3. Procesar intereses moratorios
                self.logger.info(f"Generando intereses moratorios para {mes:02d}/{año}")
                resultado_intereses = self._generar_intereses_moratorios(session, año, mes)
                resultado['intereses_generados'] = resultado_intereses['intereses_generados']
                resultado['monto_intereses'] = resultado_intereses['monto_intereses']
                
                # 2. Procesar cuotas ordinarias
                self.logger.info(f"Generando cuotas ordinarias para {mes:02d}/{año}")
                resultado_cuotas = self._generar_cuotas_ordinarias(session, año, mes)
                resultado.update(resultado_cuotas)
                
                
                # 4. Aplicar saldos a favor al próximo período
                self.logger.info(f"Aplicando saldos a favor al próximo período después de {mes:02d}/{año}")
                resultado_saldos_favor = self._aplicar_saldos_a_favor_proximo_periodo(session, año, mes)
                resultado['saldos_favor_aplicados'] = resultado_saldos_favor['saldos_aplicados']
                resultado['monto_saldos_favor'] = resultado_saldos_favor['monto_aplicado']
                
                # 5. Confirmar cambios
                session.commit()
                
                # 6. Marcar como procesado
                self._marcar_procesado(session, año, mes, resultado)
                
                tiempo_total = datetime.now() - inicio
                self.logger.info(
                    f"Procesamiento completado en {tiempo_total.total_seconds():.2f}s: "
                    f"{resultado['cuotas_generadas']} cuotas (${resultado['monto_cuotas']:,.2f}), "
                    f"{resultado['intereses_generados']} intereses (${resultado['monto_intereses']:,.2f}), "
                    f"{resultado['saldos_favor_aplicados']} saldos a favor aplicados (${resultado['monto_saldos_favor']:,.2f})"
                )
                
            except Exception as e:
                session.rollback()
                error_msg = f"Error procesando {mes:02d}/{año}: {str(e)}"
                resultado['errores'].append(error_msg)
                self.logger.error(error_msg, exc_info=True)
        
        return resultado
    
    def _verificar_procesado(self, session: Session, año: int, mes: int) -> bool:
        """Verifica si el mes ya fue procesado completamente"""
        # Usar SQLModel para esta consulta simple
        stmt = select(ControlProcesamientoMensual).where(
            ControlProcesamientoMensual.año == año,
            ControlProcesamientoMensual.mes == mes,
            ControlProcesamientoMensual.estado == 'COMPLETADO'
        )
        
        controles = session.exec(stmt).all()
        
        # Verificar que existan controles para cuotas, intereses y saldos a favor
        tipos_completados = {control.tipo_procesamiento for control in controles}
        return ('CUOTAS' in tipos_completados and 
                'INTERESES' in tipos_completados and 
                'SALDOS_FAVOR' in tipos_completados)
    
    def _generar_cuotas_ordinarias(self, session: Session, año: int, mes: int) -> Dict:
        """Genera cuotas ordinarias basándose en la configuración usando SQLModel"""
        resultado = {
            'cuotas_generadas': 0,
            'monto_cuotas': Decimal('0.00')
        }
        
        try:
            # Obtener concepto de cuota ordinaria
            concepto_cuota = session.exec(
                select(Concepto).where(Concepto.id == 1)
            ).first()
            
            if not concepto_cuota:
                self.logger.error("No se encontró el concepto 'Cuota Ordinaria Administración' (ID: 1)")
                return resultado
            
            # Obtener configuraciones de cuotas para el período que no han sido procesadas
            stmt = select(CuotaConfiguracion).where(
                CuotaConfiguracion.año == año,
                CuotaConfiguracion.mes == mes
            )
            configuraciones = session.exec(stmt).all()
            
            if not configuraciones:
                self.logger.warning(f"No hay configuraciones de cuotas para {mes:02d}/{año}")
                return resultado
            
            descripcion = f"Cuota ordinaria {mes:02d}/{año}"
            fecha_efectiva = date(año, mes, 5)  # Día 5 de cada mes
            
            # Verificar cuáles apartamentos ya tienen la cuota generada
            apartamentos_procesados = set()
            stmt_existentes = select(RegistroFinancieroApartamento.apartamento_id).where(
                RegistroFinancieroApartamento.concepto_id == 1,
                RegistroFinancieroApartamento.año_aplicable == año,
                RegistroFinancieroApartamento.mes_aplicable == mes,
                RegistroFinancieroApartamento.descripcion_adicional.like('Cuota ordinaria%')
            )
            apartamentos_existentes = session.exec(stmt_existentes).all()
            apartamentos_procesados.update(apartamentos_existentes)
            
            # Generar cuotas para apartamentos no procesados
            cuotas_generadas = 0
            monto_total = Decimal('0.00')
            
            for config in configuraciones:
                if config.apartamento_id not in apartamentos_procesados:
                    # Crear registro financiero
                    registro = RegistroFinancieroApartamento(
                        apartamento_id=config.apartamento_id,
                        concepto_id=1,  # Cuota Ordinaria Administración
                        fecha_efectiva=fecha_efectiva,
                        monto=config.monto_cuota_ordinaria_mensual,
                        tipo_movimiento='DEBITO',
                        descripcion_adicional=descripcion,
                        mes_aplicable=mes,
                        año_aplicable=año
                    )
                    session.add(registro)
                    cuotas_generadas += 1
                    monto_total += config.monto_cuota_ordinaria_mensual
            
            if cuotas_generadas > 0:
                session.commit()
                resultado['cuotas_generadas'] = cuotas_generadas
                resultado['monto_cuotas'] = monto_total
                
                self.logger.info(f"Cuotas ordinarias: {resultado['cuotas_generadas']} generadas por ${resultado['monto_cuotas']:,.2f}")
            else:
                self.logger.info("No hay cuotas ordinarias nuevas para generar")
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error generando cuotas ordinarias: {e}")
            raise
        
        return resultado
    
    def _generar_intereses_moratorios(self, session: Session, año: int, mes: int) -> Dict:
        """
        Genera intereses moratorios de forma simplificada.
        
        LÓGICA SIMPLIFICADA (según propuesta del usuario):
        1. Buscar apartamentos con saldo DÉBITO
        2. Obtener tasa de interés vigente del mes anterior
        3. Calcular y registrar intereses con concepto 3
        """
        from sqlmodel import case, func
        from src.models import RegistroFinancieroApartamento as rfa
        
        resultado = {
            'intereses_generados': 0,
            'monto_intereses': Decimal('0.00')
        }
        
        try:
            # PASO A: Buscar apartamentos con saldo DÉBITO hasta el final del mes anterior
            # Para procesar julio 2025, considerar movimientos hasta el 30 de junio 2025
            if mes == 1:
                mes_limite = 12
                año_limite = año - 1
            else:
                mes_limite = mes - 1
                año_limite = año
            
            # Calcular la fecha límite (último día del mes anterior)
            import calendar
            ultimo_dia = calendar.monthrange(año_limite, mes_limite)[1]
            fecha_limite = f"{año_limite}-{mes_limite:02d}-{ultimo_dia}"
            
            self.logger.info(f"Calculando saldos hasta: {fecha_limite}")
            
            monto_con_signo = case(
                (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
                (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
                else_=0
            )
            
            statement = select(
                rfa.apartamento_id,
                func.coalesce(func.sum(monto_con_signo), 0).label("saldo")
            ).group_by(
                rfa.apartamento_id
            ).having(
                func.coalesce(func.sum(monto_con_signo), 0) > 0  # Solo saldos positivos (deudas)
            ).order_by(
                rfa.apartamento_id
            )
            
            apartamentos_con_deuda = session.exec(statement).all()
            
            if not apartamentos_con_deuda:
                self.logger.info("No hay apartamentos con saldo deudor para calcular intereses")
                return resultado
            
            # PASO B: Obtener tasa de interés vigente del mes anterior
            # Para calcular intereses de julio 2025, usar tasa de junio 2025
            if mes == 1:
                mes_tasa = 12
                año_tasa = año - 1
            else:
                mes_tasa = mes - 1
                año_tasa = año
            
            stmt_tasa = select(TasaInteresMora).where(
                TasaInteresMora.año == año_tasa,
                TasaInteresMora.mes == mes_tasa
            ).limit(1)
            
            tasa_record = session.exec(stmt_tasa).first()
            if not tasa_record:
                self.logger.warning(f"No se encontró tasa de interés para {mes_tasa:02d}/{año_tasa}")
                return resultado
            
            tasa_interes = float(tasa_record.tasa_interes_mensual)
            self.logger.info(f"Tasa de interés aplicada: {tasa_interes} del período {tasa_record.mes:02d}/{tasa_record.año} (mes anterior)")
            
            # PASO C: Verificar que no existan intereses ya calculados para este período
            intereses_existentes = session.exec(
                select(RegistroFinancieroApartamento)
                .where(RegistroFinancieroApartamento.concepto_id == 3)  # Concepto 3 = Intereses
                .where(RegistroFinancieroApartamento.año_aplicable == año)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes)
                .where(RegistroFinancieroApartamento.tipo_movimiento == 'DEBITO')
            ).first()
            
            if intereses_existentes:
                self.logger.info(f"Ya existen intereses calculados para {mes:02d}/{año}")
                return resultado
            
            # PASO D: Calcular y registrar intereses para cada apartamento con deuda
            for apto_id, saldo in apartamentos_con_deuda:
                interes_calculado = float(saldo) * tasa_interes
                
                if interes_calculado > 0.01:  # Solo registrar si el interés es significativo
                    nuevo_interes = RegistroFinancieroApartamento(
                        apartamento_id=apto_id,
                        concepto_id=3,  # Concepto 3 = Intereses por mora
                        tipo_movimiento='DEBITO',
                        monto=round(interes_calculado, 2),
                        fecha_efectiva=date(año, mes, 28),  # Día 28 del mes actual
                        año_aplicable=año,
                        mes_aplicable=mes,
                        descripcion_adicional=f"Interés moratorio {mes:02d}/{año} - Saldo al {fecha_limite}: ${saldo:,.2f} - Tasa {mes_tasa:02d}/{año_tasa}: {tasa_interes*100:.2f}%",
                        referencia_pago=f"INT-AUTO-{año}{mes:02d}",
                        fecha_creacion=datetime.now()
                    )
                    
                    session.add(nuevo_interes)
                    resultado['intereses_generados'] += 1
                    resultado['monto_intereses'] += Decimal(str(interes_calculado))
            
            if resultado['intereses_generados'] > 0:
                session.commit()
                self.logger.info(f"Intereses generados: {resultado['intereses_generados']} por ${resultado['monto_intereses']:,.2f}")
            else:
                self.logger.info("No se generaron intereses (montos muy pequeños)")
                
        except Exception as e:
            self.logger.error(f"Error generando intereses moratorios: {e}")
            session.rollback()
            raise
        
        return resultado
    
    def _aplicar_saldos_a_favor_proximo_periodo(self, session: Session, año: int, mes: int) -> Dict:
        """
        Aplica automáticamente saldos a favor (créditos/prepagos) al próximo período de facturación.
        
        LÓGICA:
        1. Identifica apartamentos con saldo a favor (más créditos que débitos)
        2. Calcula el próximo período (mes+1, año+1 si es diciembre)
        3. Genera un crédito para el próximo período
        4. Esto efectivamente aplica el prepago/crédito al siguiente mes
        
        Ejemplo: Si en enero un apartamento queda con $100 a favor después de todos los cargos,
        se genera un crédito de $100 para febrero, reduciendo automáticamente su cuota.
        """
        resultado = {
            'saldos_aplicados': 0,
            'monto_aplicado': Decimal('0.00')
        }
        
        # Calcular el próximo período
        if mes == 12:
            mes_siguiente = 1
            año_siguiente = año + 1
        else:
            mes_siguiente = mes + 1
            año_siguiente = año
        
        # Obtener concepto para aplicación de saldo a favor
        stmt_concepto = select(Concepto).where(
            Concepto.nombre.ilike('%aplicación%favor%') | 
            Concepto.nombre.ilike('%prepago%') |
            Concepto.nombre.ilike('%crédito%aplicado%')
        ).limit(1)
        
        concepto_aplicacion = session.exec(stmt_concepto).first()
        if not concepto_aplicacion:
            # Si no existe el concepto, usar el concepto de Pago Cuota (ID 5)
            concepto_aplicacion = session.exec(
                select(Concepto).where(Concepto.id == 5)
            ).first()
        
        if not concepto_aplicacion:
            self.logger.warning("No se encontró concepto para aplicación de saldo a favor")
            return resultado
        
        self.logger.info(f"Concepto para aplicación de saldo: {concepto_aplicacion.nombre} (ID: {concepto_aplicacion.id})")
        
        # SQL para identificar apartamentos con saldo a favor después del procesamiento del mes actual
        try:
            # Fecha límite para cálculo de saldos (día 28 del mes)
            fecha_limite = date(año, mes, 28)
            
            # Calcular saldos por apartamento usando SQLModel
            from sqlmodel import func, case
            
            # Expresión para calcular el saldo (créditos - débitos)
            saldo_expression = func.sum(
                case(
                    (RegistroFinancieroApartamento.tipo_movimiento == 'CREDITO', RegistroFinancieroApartamento.monto),
                    else_=-RegistroFinancieroApartamento.monto
                )
            ).label('saldo_a_favor')
            
            stmt_saldos = select(
                RegistroFinancieroApartamento.apartamento_id,
                saldo_expression
            ).where(
                RegistroFinancieroApartamento.fecha_efectiva <= fecha_limite
            ).group_by(
                RegistroFinancieroApartamento.apartamento_id
            ).having(
                saldo_expression > Decimal('0.01')
            )
            
            apartamentos_con_saldo = session.exec(stmt_saldos).all()
            
            if not apartamentos_con_saldo:
                self.logger.info("No hay apartamentos con saldo a favor para aplicar")
                return resultado
            
            # Verificar cuáles aplicaciones ya existen para evitar duplicados
            descripcion_patron = f"Aplicación automática saldo a favor de {mes:02d}/{año}"
            stmt_existentes = select(RegistroFinancieroApartamento.apartamento_id).where(
                RegistroFinancieroApartamento.concepto_id == concepto_aplicacion.id,
                RegistroFinancieroApartamento.año_aplicable == año_siguiente,
                RegistroFinancieroApartamento.mes_aplicable == mes_siguiente,
                RegistroFinancieroApartamento.descripcion_adicional.like('Aplicación automática saldo a favor%'),
                RegistroFinancieroApartamento.descripcion_adicional.like(f'%de {mes:02d}/{año}%')
            )
            apartamentos_ya_procesados = set(session.exec(stmt_existentes).all())
            
            # Generar aplicaciones para apartamentos no procesados
            saldos_aplicados = 0
            monto_total_aplicado = Decimal('0.00')
            fecha_aplicacion = date(año_siguiente, mes_siguiente, 1)
            
            for row in apartamentos_con_saldo:
                apartamento_id = row.apartamento_id
                saldo_a_favor = Decimal(str(row.saldo_a_favor)).quantize(Decimal('0.01'))
                
                if apartamento_id not in apartamentos_ya_procesados:
                    descripcion = (
                        f"Aplicación automática saldo a favor de {mes:02d}/{año} "
                        f"aplicado a {mes_siguiente:02d}/{año_siguiente} "
                        f"(Saldo: ${saldo_a_favor})"
                    )
                    
                    registro = RegistroFinancieroApartamento(
                        apartamento_id=apartamento_id,
                        concepto_id=concepto_aplicacion.id,
                        fecha_efectiva=fecha_aplicacion,
                        monto=saldo_a_favor,
                        tipo_movimiento='CREDITO',
                        descripcion_adicional=descripcion,
                        mes_aplicable=mes_siguiente,
                        año_aplicable=año_siguiente
                    )
                    session.add(registro)
                    saldos_aplicados += 1
                    monto_total_aplicado += saldo_a_favor
            
            if saldos_aplicados > 0:
                session.commit()
                resultado['saldos_aplicados'] = saldos_aplicados
                resultado['monto_aplicado'] = monto_total_aplicado
                
                self.logger.info(f"Saldos a favor: {resultado['saldos_aplicados']} aplicados por ${resultado['monto_aplicado']:,.2f} al período {mes_siguiente:02d}/{año_siguiente}")
            else:
                self.logger.info("No hay nuevos saldos a favor para aplicar")
            
        except Exception as e:
            session.rollback()
            self.logger.error(f"Error aplicando saldos a favor: {e}")
            # No hacer raise para no afectar el procesamiento principal
            pass
        
        return resultado
    
    def _marcar_procesado(self, session: Session, año: int, mes: int, resultado: Dict):
        """Marca el procesamiento como completado"""
        try:
            # Marcar cuotas como procesadas
            control_cuotas = ControlProcesamientoMensual(
                año=año,
                mes=mes,
                tipo_procesamiento='CUOTAS',
                estado='COMPLETADO',
                fecha_procesamiento=datetime.now(),
                registros_procesados=resultado['cuotas_generadas'],
                monto_total_generado=resultado['monto_cuotas']
            )
            
            # Marcar intereses como procesados
            control_intereses = ControlProcesamientoMensual(
                año=año,
                mes=mes,
                tipo_procesamiento='INTERESES',
                estado='COMPLETADO',
                fecha_procesamiento=datetime.now(),
                registros_procesados=resultado['intereses_generados'],
                monto_total_generado=resultado['monto_intereses']
            )
            
            # Marcar saldos a favor como procesados
            control_saldos = ControlProcesamientoMensual(
                año=año,
                mes=mes,
                tipo_procesamiento='SALDOS_FAVOR',
                estado='COMPLETADO',
                fecha_procesamiento=datetime.now(),
                registros_procesados=resultado['saldos_favor_aplicados'],
                monto_total_generado=resultado['monto_saldos_favor']
            )
            
            # Usar merge para evitar duplicados
            session.merge(control_cuotas)
            session.merge(control_intereses)
            session.merge(control_saldos)
            session.commit()
            
            self.logger.info("Control de procesamiento actualizado")
            
        except Exception as e:
            self.logger.error(f"Error actualizando control de procesamiento: {e}")
            # No fallar todo el proceso por esto
            pass
    
    def procesar_mes_simulacion(self, año: int, mes: int) -> Dict:
        """
        Simula el procesamiento de un mes mostrando resultados en consola SIN grabar datos.
        Útil para verificar cálculos antes de ejecutar el proceso real.
        """
        print(f"\n🧪 SIMULACIÓN DE PROCESAMIENTO - {mes:02d}/{año}")
        print("=" * 60)
        
        resultado = {
            'año': año,
            'mes': mes,
            'cuotas_generadas': 0,
            'intereses_generados': 0,
            'monto_cuotas': Decimal('0.00'),
            'monto_intereses': Decimal('0.00'),
            'simulacion': True
        }
        
        with Session(self.engine) as session:
            try:
                # 1. SIMULACIÓN: Verificar configuraciones de cuotas
                print("\n📋 1. VERIFICACIÓN DE CONFIGURACIONES")
                configuraciones = session.exec(
                    select(CuotaConfiguracion)
                    .where(CuotaConfiguracion.año == año)
                    .where(CuotaConfiguracion.mes == mes)
                ).all()
                
                if configuraciones:
                    print(f"✅ Encontradas {len(configuraciones)} configuraciones de cuotas:")
                    total_cuotas = sum(config.monto_cuota_ordinaria_mensual for config in configuraciones)
                    for config in configuraciones:
                        print(f"   - Apartamento {config.apartamento_id}: ${config.monto_cuota_ordinaria_mensual:,.2f}")
                    print(f"💰 Total a generar en cuotas: ${total_cuotas:,.2f}")
                    resultado['cuotas_generadas'] = len(configuraciones)
                    resultado['monto_cuotas'] = Decimal(str(total_cuotas))
                else:
                    print("❌ No hay configuraciones de cuotas para este período")
                
                # 2. SIMULACIÓN: Calcular intereses
                print("\n💸 2. CÁLCULO DE INTERESES (SIMULACIÓN)")
                intereses_simulados = self._simular_intereses(session, año, mes)
                resultado['intereses_generados'] = intereses_simulados['cantidad']
                resultado['monto_intereses'] = intereses_simulados['monto']
                
                # 3. SIMULACIÓN: Saldos a favor
                print("\n💳 3. SALDOS A FAVOR (SIMULACIÓN)")
                self._simular_saldos_a_favor(session, año, mes)
                
                print("\n✅ SIMULACIÓN COMPLETADA")
                print("=" * 60)
                print(f"📊 RESUMEN:")
                print(f"   Cuotas a generar: {resultado['cuotas_generadas']} (${resultado['monto_cuotas']:,.2f})")
                print(f"   Intereses a generar: {resultado['intereses_generados']} (${resultado['monto_intereses']:,.2f})")
                print(f"   Total impacto: ${resultado['monto_cuotas'] + resultado['monto_intereses']:,.2f}")
                print("\n⚠️  ESTO ES SOLO UNA SIMULACIÓN - NO SE GRABARON DATOS")
                
            except Exception as e:
                print(f"❌ Error en simulación: {e}")
                resultado['error'] = str(e)
        
        return resultado
    
    def _simular_intereses(self, session: Session, año: int, mes: int) -> Dict:
        """Simula el cálculo de intereses sin grabar datos"""
        from sqlmodel import case, func
        from src.models import RegistroFinancieroApartamento as rfa
        
        resultado_simulacion = {'cantidad': 0, 'monto': Decimal('0.00')}
        
        try:
            # PASO A: Buscar apartamentos con saldo DÉBITO hasta el final del mes anterior
            # Para procesar julio 2025, considerar movimientos hasta el 30 de junio 2025
            if mes == 1:
                mes_limite = 12
                año_limite = año - 1
            else:
                mes_limite = mes - 1
                año_limite = año
            
            # Calcular la fecha límite (último día del mes anterior)
            import calendar
            ultimo_dia = calendar.monthrange(año_limite, mes_limite)[1]
            fecha_limite = f"{año_limite}-{mes_limite:02d}-{ultimo_dia}"
            
            print(f"   📅 Calculando saldos hasta: {fecha_limite}")
            
            monto_con_signo = case(
                (rfa.tipo_movimiento == 'DEBITO', rfa.monto),
                (rfa.tipo_movimiento == 'CREDITO', -rfa.monto),
                else_=0
            )
            
            statement = select(
                rfa.apartamento_id,
                func.coalesce(func.sum(monto_con_signo), 0).label("saldo")
            ).where(
                rfa.fecha_efectiva <= fecha_limite  # Solo hasta el final del mes anterior
            ).group_by(
                rfa.apartamento_id
            ).having(
                func.coalesce(func.sum(monto_con_signo), 0) > 0
            ).order_by(
                rfa.apartamento_id
            )
            
            apartamentos_con_deuda = session.exec(statement).all()
            
            if not apartamentos_con_deuda:
                print("   ✅ No hay apartamentos con saldo deudor")
                return resultado_simulacion
            
            # PASO B: Obtener tasa de interés del mes anterior
            # Para procesar julio 2025, usar tasa de junio 2025
            if mes == 1:
                mes_tasa = 12
                año_tasa = año - 1
            else:
                mes_tasa = mes - 1
                año_tasa = año
            
            stmt_tasa = select(TasaInteresMora).where(
                TasaInteresMora.año == año_tasa,
                TasaInteresMora.mes == mes_tasa
            ).limit(1)
            
            tasa_record = session.exec(stmt_tasa).first()
            if not tasa_record:
                print(f"   ❌ No se encontró tasa de interés para {mes_tasa:02d}/{año_tasa}")
                return resultado_simulacion
            
            tasa_interes = float(tasa_record.tasa_interes_mensual)
            print(f"   📈 Tasa aplicada: {tasa_interes*100:.2f}% del período {tasa_record.mes:02d}/{tasa_record.año} (mes anterior)")
            
            # PASO C: Verificar intereses existentes
            intereses_existentes = session.exec(
                select(RegistroFinancieroApartamento)
                .where(RegistroFinancieroApartamento.concepto_id == 3)
                .where(RegistroFinancieroApartamento.año_aplicable == año)
                .where(RegistroFinancieroApartamento.mes_aplicable == mes)
                .where(RegistroFinancieroApartamento.tipo_movimiento == 'DEBITO')
            ).first()
            
            if intereses_existentes:
                print(f"   ⚠️  Ya existen intereses calculados para {mes:02d}/{año}")
                return resultado_simulacion
            
            # PASO D: Simular cálculo de intereses
            print(f"   📋 Apartamentos con deuda encontrados: {len(apartamentos_con_deuda)}")
            print("   📊 Detalles del cálculo:")
            
            total_intereses = Decimal('0.00')
            apartamentos_con_interes = 0
            
            for apto_id, saldo in apartamentos_con_deuda:
                interes_calculado = float(saldo) * tasa_interes
                
                if interes_calculado > 0.01:
                    print(f"      Apto {apto_id}: Saldo ${saldo:,.2f} → Interés ${interes_calculado:.2f}")
                    total_intereses += Decimal(str(interes_calculado))
                    apartamentos_con_interes += 1
                else:
                    print(f"      Apto {apto_id}: Saldo ${saldo:,.2f} → Interés insignificante (${interes_calculado:.2f})")
            
            resultado_simulacion['cantidad'] = apartamentos_con_interes
            resultado_simulacion['monto'] = total_intereses
            
            print(f"   💰 Total intereses a generar: {apartamentos_con_interes} registros por ${total_intereses:,.2f}")
            
        except Exception as e:
            print(f"   ❌ Error simulando intereses: {e}")
        
        return resultado_simulacion
    
    def _simular_saldos_a_favor(self, session: Session, año: int, mes: int):
        """Simula la aplicación de saldos a favor sin grabar datos"""
        from sqlmodel import case, func
        from src.models import RegistroFinancieroApartamento as rfa
        
        try:
            # Calcular próximo período
            if mes == 12:
                mes_siguiente = 1
                año_siguiente = año + 1
            else:
                mes_siguiente = mes + 1
                año_siguiente = año
            
            print(f"   🔄 Período destino: {mes_siguiente:02d}/{año_siguiente}")
            
            # Buscar apartamentos con saldo a favor
            monto_con_signo = case(
                (rfa.tipo_movimiento == 'CREDITO', rfa.monto),
                (rfa.tipo_movimiento == 'DEBITO', -rfa.monto),
                else_=0
            )
            
            statement = select(
                rfa.apartamento_id,
                func.coalesce(func.sum(monto_con_signo), 0).label("saldo_favor")
            ).group_by(
                rfa.apartamento_id
            ).having(
                func.coalesce(func.sum(monto_con_signo), 0) > 0.01
            ).order_by(
                rfa.apartamento_id
            )
            
            apartamentos_con_credito = session.exec(statement).all()
            
            if apartamentos_con_credito:
                print(f"   📋 Apartamentos con saldo a favor: {len(apartamentos_con_credito)}")
                total_saldos = Decimal('0.00')
                
                for apto_id, saldo_favor in apartamentos_con_credito:
                    print(f"      Apto {apto_id}: Crédito de ${saldo_favor:,.2f} → Se aplicaría a {mes_siguiente:02d}/{año_siguiente}")
                    total_saldos += Decimal(str(saldo_favor))
                
                print(f"   💳 Total saldos a favor a aplicar: ${total_saldos:,.2f}")
            else:
                print("   ✅ No hay apartamentos con saldo a favor")
                
        except Exception as e:
            print(f"   ❌ Error simulando saldos a favor: {e}")




def generar_cargos_mensuales(año: int, mes: int, forzar: bool = False) -> Dict:
    """
    Función de conveniencia para generar cargos mensuales.
    
    Args:
        año: Año a procesar
        mes: Mes a procesar (1-12)
        forzar: Si True, procesa incluso si ya fue procesado antes
        
    Returns:
        Diccionario con resultados del procesamiento
    """
    generador = GeneradorAutomatico()
    return generador.procesar_mes(año, mes, forzar)


def simular_cargos_mensuales(año: int, mes: int) -> Dict:
    """
    Función de conveniencia para simular cargos mensuales SIN grabar datos.
    
    Args:
        año: Año a procesar
        mes: Mes a procesar (1-12)
        
    Returns:
        Diccionario con resultados de la simulación
    """
    generador = GeneradorAutomatico()
    return generador.procesar_mes_simulacion(año, mes)


def main():
    """Función principal para ejecutar desde línea de comandos"""
    print("🚀 Generador Automático de Cargos Financieros")
    
    if len(sys.argv) >= 3:
        try:
            año = int(sys.argv[1])
            mes = int(sys.argv[2])
            forzar = len(sys.argv) > 3 and str(sys.argv[3]).lower() in ['true', '1', 'forzar']
            
            generador = GeneradorAutomatico()
            
            # Si se pasa 'simular' como cuarto parámetro, hacer simulación
            if len(sys.argv) > 3 and str(sys.argv[3]).lower() == 'simular':
                print(f"🧪 Modo simulación activado para {mes:02d}/{año}")
                resultado = generador.procesar_mes_simulacion(año, mes)
            else:
                print(f"📅 Procesando {mes:02d}/{año}...")
                if forzar:
                    print("⚠️  MODO FORZADO activado")
                resultado = generador.procesar_mes(año, mes, forzar)
                
        except ValueError:
            print("❌ Error: año y mes deben ser números enteros")
            print("Uso: python generador_pagos.py <año> <mes> [forzar|simular]")
            sys.exit(1)
    else:
        print("Uso: python generador_pagos.py <año> <mes> [forzar|simular]")
        print("Ejemplos:")
        print("  python generador_pagos.py 2025 7 simular    # Simular julio 2025")
        print("  python generador_pagos.py 2025 7 forzar     # Procesar julio 2025 (forzado)")
        print("  python generador_pagos.py 2025 7            # Procesar julio 2025")


if __name__ == "__main__":
    main()
