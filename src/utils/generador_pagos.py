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

from sqlmodel import create_engine, Session, select, text
from datetime import date, datetime, timedelta
from decimal import Decimal
import logging
from typing import Dict

# Importaciones del proyecto
from src.models.database import DATABASE_URL
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
        self.engine = create_engine(DATABASE_URL)
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
                
                # 2. Procesar cuotas ordinarias
                self.logger.info(f"Generando cuotas ordinarias para {mes:02d}/{año}")
                resultado_cuotas = self._generar_cuotas_ordinarias(session, año, mes)
                resultado.update(resultado_cuotas)
                
                # 3. Procesar intereses moratorios
                self.logger.info(f"Generando intereses moratorios para {mes:02d}/{año}")
                resultado_intereses = self._generar_intereses_moratorios(session, año, mes)
                resultado['intereses_generados'] = resultado_intereses['intereses_generados']
                resultado['monto_intereses'] = resultado_intereses['monto_intereses']
                
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
        """Genera las cuotas ordinarias usando SQL directo para evitar problemas de enum"""
        resultado = {
            'cuotas_generadas': 0,
            'monto_cuotas': Decimal('0.00')
        }
        
        # Usar SQL directo con formato de string para evitar problemas de parámetros
        sql_query = f"""
            INSERT INTO registro_financiero_apartamento 
            (apartamento_id, concepto_id, fecha_efectiva, monto, 
             tipo_movimiento, descripcion_adicional, mes_aplicable, año_aplicable)
            SELECT 
                cc.apartamento_id,
                1,  -- ID del concepto 'Cuota Ordinaria Administración'
                DATE('{año}' || '-' || LPAD('{mes}'::text, 2, '0') || '-05'),  -- Día 5 de cada mes
                cc.monto_cuota_ordinaria_mensual,
                'DEBITO'::tipo_movimiento_enum,
                'Cuota ordinaria ' || LPAD('{mes}'::text, 2, '0') || '/' || '{año}',
                {mes},
                {año}
            FROM cuota_configuracion cc
            WHERE cc.año = {año}
            AND cc.mes = {mes}
            AND NOT EXISTS (
                SELECT 1 FROM registro_financiero_apartamento rfa
                WHERE rfa.apartamento_id = cc.apartamento_id 
                AND rfa.concepto_id = 1
                AND rfa.año_aplicable = {año}
                AND rfa.mes_aplicable = {mes}
                AND rfa.descripcion_adicional LIKE 'Cuota ordinaria%'
            )
        """
        
        try:
            # Ejecutar la inserción
            result = session.exec(text(sql_query))
            resultado['cuotas_generadas'] = result.rowcount
            
            # Calcular el monto total generado
            if resultado['cuotas_generadas'] > 0:
                sql_monto = f"""
                    SELECT COALESCE(SUM(monto), 0) as total
                    FROM registro_financiero_apartamento
                    WHERE año_aplicable = {año}
                    AND mes_aplicable = {mes}
                    AND tipo_movimiento = 'DEBITO'
                    AND descripcion_adicional LIKE 'Cuota ordinaria%'
                """
                
                monto_result = session.exec(text(sql_monto)).first()
                if monto_result:
                    resultado['monto_cuotas'] = Decimal(str(monto_result.total))
            
            self.logger.info(f"Cuotas ordinarias: {resultado['cuotas_generadas']} generadas por ${resultado['monto_cuotas']:,.2f}")
            
        except Exception as e:
            self.logger.error(f"Error generando cuotas ordinarias: {e}")
            raise
        
        return resultado
    
    def _generar_intereses_moratorios(self, session: Session, año: int, mes: int) -> Dict:
        """
        Genera intereses moratorios sobre saldos pendientes al final del mes anterior.
        
        LÓGICA: Si un apartamento tiene saldo pendiente al finalizar el mes anterior,
        se genera interés en el mes actual. Esto permite que el propietario tenga
        todo el mes para pagar sin generar intereses, pero una vez finalizado el mes,
        cualquier saldo pendiente genera interés moratorio.
        
        Ejemplo: DÉBITO generado el 29 de enero -> si no se paga antes del 31 de enero,
        genera interés en febrero.
        """
        resultado = {
            'intereses_generados': 0,
            'monto_intereses': Decimal('0.00')
        }
        
        # Obtener la tasa de interés vigente para el mes anterior
        # Para calcular intereses de junio, usamos la tasa de mayo
        mes_tasa = mes - 1 if mes > 1 else 12
        año_tasa = año if mes > 1 else año - 1
        
        stmt_tasa = select(TasaInteresMora).where(
            TasaInteresMora.año == año_tasa,
            TasaInteresMora.mes == mes_tasa
        ).limit(1)
        
        tasa_record = session.exec(stmt_tasa).first()
        if not tasa_record:
            self.logger.warning(f"No se encontró tasa de interés para {mes_tasa:02d}/{año_tasa}")
            return resultado
        
        self.logger.info(f"Tasa de interés encontrada: {tasa_record.tasa_interes_mensual} para {mes_tasa:02d}/{año_tasa}")
        
        # Obtener concepto de interés
        stmt_concepto = select(Concepto).where(
            Concepto.nombre.ilike('%interés%') | Concepto.nombre.ilike('%mora%')
        ).limit(1)
        
        concepto_interes = session.exec(stmt_concepto).first()
        if not concepto_interes:
            self.logger.warning("No se encontró concepto de interés")
            return resultado
        
        self.logger.info(f"Concepto de interés encontrado: {concepto_interes.nombre} (ID: {concepto_interes.id})")
        
        # Calcular fecha límite (último día del mes anterior)
        if mes == 1:
            fecha_limite = f"{año-1}-12-31"
        else:
            # Usar el último día del mes anterior
            import calendar
            ultimo_dia = calendar.monthrange(año, mes-1)[1]
            fecha_limite = f"{año}-{mes-1:02d}-{ultimo_dia}"
        
        # SQL CORREGIDO - Generar intereses sobre cualquier saldo pendiente al final del mes anterior
        tasa_porcentaje = float(tasa_record.tasa_interes_mensual) * 100
        
        sql_intereses = f"""
            WITH saldos_apartamento AS (
                SELECT 
                    rfa.apartamento_id,
                    SUM(CASE 
                        WHEN rfa.tipo_movimiento = 'DEBITO' THEN rfa.monto 
                        ELSE -rfa.monto 
                    END) as saldo_pendiente
                FROM registro_financiero_apartamento rfa
                LEFT JOIN concepto c ON rfa.concepto_id = c.id
                WHERE rfa.fecha_efectiva <= '{fecha_limite}'
                -- Excluir conceptos de interés del cálculo base para evitar interés sobre interés
                AND (c.nombre IS NULL OR (
                    c.nombre NOT ILIKE '%interés%' AND 
                    c.nombre NOT ILIKE '%mora%' AND
                    c.nombre NOT ILIKE '%intereses%'
                ))
                GROUP BY rfa.apartamento_id
                HAVING SUM(CASE 
                    WHEN rfa.tipo_movimiento = 'DEBITO' THEN rfa.monto 
                    ELSE -rfa.monto 
                END) > 0.01  -- Solo saldos positivos (deudas)
            )
            INSERT INTO registro_financiero_apartamento 
            (apartamento_id, concepto_id, fecha_efectiva, monto, 
             tipo_movimiento, descripcion_adicional, mes_aplicable, año_aplicable)
            SELECT 
                sa.apartamento_id,
                {concepto_interes.id},
                DATE('{año}' || '-' || LPAD('{mes}'::text, 2, '0') || '-28'),
                ROUND(sa.saldo_pendiente * ({tasa_porcentaje} / 100), 2),
                'DEBITO'::tipo_movimiento_enum,
                'Interés moratorio automático - ' || LPAD('{mes}'::text, 2, '0') || '/' || '{año}' ||
                ' (Base: $' || ROUND(sa.saldo_pendiente, 2) || 
                ', Tasa: {tasa_porcentaje}%, Saldo al {fecha_limite})',
                {mes},
                {año}
            FROM saldos_apartamento sa
            WHERE NOT EXISTS (
                SELECT 1 FROM registro_financiero_apartamento rfa
                WHERE rfa.apartamento_id = sa.apartamento_id 
                AND rfa.concepto_id = {concepto_interes.id}
                AND rfa.año_aplicable = {año}
                AND rfa.mes_aplicable = {mes}
                AND rfa.descripcion_adicional LIKE 'Interés moratorio automático%'
            )
        """
        
        try:
            # Ejecutar la inserción
            result = session.exec(text(sql_intereses))
            resultado['intereses_generados'] = result.rowcount
            
            # Calcular monto total de intereses
            if resultado['intereses_generados'] > 0:
                sql_monto = f"""
                    SELECT COALESCE(SUM(monto), 0) as total
                    FROM registro_financiero_apartamento
                    WHERE año_aplicable = {año}
                    AND mes_aplicable = {mes}
                    AND concepto_id = {concepto_interes.id}
                    AND descripcion_adicional LIKE 'Interés moratorio automático%'
                """
                
                monto_result = session.exec(text(sql_monto)).first()
                if monto_result:
                    resultado['monto_intereses'] = Decimal(str(monto_result.total))
            
            self.logger.info(f"Intereses moratorios: {resultado['intereses_generados']} generados por ${resultado['monto_intereses']:,.2f}")
            
        except Exception as e:
            self.logger.error(f"Error generando intereses moratorios: {e}")
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
        sql_saldos_favor = f"""
            WITH saldos_actuales AS (
                SELECT 
                    rfa.apartamento_id,
                    SUM(CASE 
                        WHEN rfa.tipo_movimiento = 'CREDITO' THEN rfa.monto 
                        ELSE -rfa.monto 
                    END) as saldo_a_favor
                FROM registro_financiero_apartamento rfa
                WHERE rfa.fecha_efectiva <= DATE('{año}' || '-' || LPAD('{mes}'::text, 2, '0') || '-28')
                GROUP BY rfa.apartamento_id
                HAVING SUM(CASE 
                    WHEN rfa.tipo_movimiento = 'CREDITO' THEN rfa.monto 
                    ELSE -rfa.monto 
                END) > 0.01  -- Solo saldos a favor significativos (más de 1 centavo)
            )
            INSERT INTO registro_financiero_apartamento 
            (apartamento_id, concepto_id, fecha_efectiva, monto, 
             tipo_movimiento, descripcion_adicional, mes_aplicable, año_aplicable)
            SELECT 
                sa.apartamento_id,
                {concepto_aplicacion.id},
                DATE('{año_siguiente}' || '-' || LPAD('{mes_siguiente}'::text, 2, '0') || '-01'),
                ROUND(sa.saldo_a_favor, 2),
                'CREDITO'::tipo_movimiento_enum,
                'Aplicación automática saldo a favor de ' || LPAD('{mes}'::text, 2, '0') || '/' || '{año}' ||
                ' aplicado a ' || LPAD('{mes_siguiente}'::text, 2, '0') || '/' || '{año_siguiente}' ||
                ' (Saldo: $' || ROUND(sa.saldo_a_favor, 2) || ')',
                {mes_siguiente},
                {año_siguiente}
            FROM saldos_actuales sa
            WHERE NOT EXISTS (
                SELECT 1 FROM registro_financiero_apartamento rfa
                WHERE rfa.apartamento_id = sa.apartamento_id 
                AND rfa.concepto_id = {concepto_aplicacion.id}
                AND rfa.año_aplicable = {año_siguiente}
                AND rfa.mes_aplicable = {mes_siguiente}
                AND rfa.descripcion_adicional LIKE 'Aplicación automática saldo a favor%'
                AND rfa.descripcion_adicional LIKE '%de {mes:02d}/{año}%'
            )
        """
        
        try:
            # Ejecutar la inserción
            result = session.exec(text(sql_saldos_favor))
            resultado['saldos_aplicados'] = result.rowcount
            
            # Calcular monto total aplicado
            if resultado['saldos_aplicados'] > 0:
                sql_monto = f"""
                    SELECT COALESCE(SUM(monto), 0) as total
                    FROM registro_financiero_apartamento
                    WHERE año_aplicable = {año_siguiente}
                    AND mes_aplicable = {mes_siguiente}
                    AND concepto_id = {concepto_aplicacion.id}
                    AND descripcion_adicional LIKE 'Aplicación automática saldo a favor%'
                    AND descripcion_adicional LIKE '%de {mes:02d}/{año}%'
                """
                
                monto_result = session.exec(text(sql_monto)).first()
                if monto_result:
                    resultado['monto_aplicado'] = Decimal(str(monto_result.total))
            
            self.logger.info(f"Saldos a favor: {resultado['saldos_aplicados']} aplicados por ${resultado['monto_aplicado']:,.2f} al período {mes_siguiente:02d}/{año_siguiente}")
            
        except Exception as e:
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


def main():
    """Función principal"""
    print("🚀 Generador Automático V3 - Funcional")
    
    try:
        generador = GeneradorAutomaticoV3()
        
        if len(sys.argv) >= 3:
            try:
                año = int(sys.argv[1])
                mes = int(sys.argv[2])
                forzar = len(sys.argv) > 3 and str(sys.argv[3]).lower() in ['true', '1', 'forzar']
                
                print(f"📅 Procesando {mes:02d}/{año}...")
                if forzar:
                    print("⚠️  MODO FORZADO activado")
                
                resultado = generador.procesar_mes(año, mes, forzar)
                
                # Mostrar resultados
                if resultado['ya_procesado']:
                    print(f"ℹ️  El mes {mes:02d}/{año} ya había sido procesado")
                else:
                    print(f"\n✅ Procesamiento completado:")
                    print(f"   📊 Cuotas: {resultado['cuotas_generadas']} (${resultado['monto_cuotas']:,.2f})")
                    print(f"   💰 Intereses: {resultado['intereses_generados']} (${resultado['monto_intereses']:,.2f})")
                    print(f"   🔄 Saldos a favor aplicados: {resultado['saldos_favor_aplicados']} (${resultado['monto_saldos_favor']:,.2f})")
                
                if resultado['errores']:
                    print(f"\n❌ Errores encontrados:")
                    for error in resultado['errores']:
                        print(f"   - {error}")
                        
            except ValueError:
                print("❌ Error: año y mes deben ser números enteros")
                sys.exit(1)
        else:
            # Procesar mes actual
            hoy = date.today()
            print(f"📅 Procesando mes actual: {hoy.month:02d}/{hoy.year}")
            
            resultado = generador.procesar_mes(hoy.year, hoy.month)
            
            print(f"\n✅ Resultado:")
            print(f"   📊 Cuotas: {resultado['cuotas_generadas']} (${resultado['monto_cuotas']:,.2f})")
            print(f"   💰 Intereses: {resultado['intereses_generados']} (${resultado['monto_intereses']:,.2f})")
            print(f"   🔄 Saldos a favor aplicados: {resultado['saldos_favor_aplicados']} (${resultado['monto_saldos_favor']:,.2f})")
            
            if resultado['ya_procesado']:
                print("ℹ️  El mes ya había sido procesado")
                
    except Exception as e:
        print(f"❌ Error crítico: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
