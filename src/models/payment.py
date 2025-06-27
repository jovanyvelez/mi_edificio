from typing import Optional, TYPE_CHECKING
from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from sqlmodel import SQLModel, Field, Relationship, Index

if TYPE_CHECKING:
    from .apartment import Apartamento


class TipoMovimientoEnum(str, Enum):
    DEBITO = "DEBITO"  # Para cargos/deudas del apartamento
    CREDITO = "CREDITO"  # Para pagos/abonos del apartamento


class TipoItemPresupuestoEnum(str, Enum):
    INGRESO = "INGRESO"
    GASTO = "GASTO"


class Concepto(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    nombre: str = Field(max_length=150)
    es_ingreso_tipico: bool = Field(default=False)
    es_recurrente_presupuesto: bool = Field(default=True)
    descripcion: Optional[str] = None
    
    # Relaciones
    registros_financieros: list["RegistroFinancieroApartamento"] = Relationship(back_populates="concepto")
    gastos_comunidad: list["GastoComunidad"] = Relationship(back_populates="concepto")
    items_presupuesto: list["ItemPresupuesto"] = Relationship(back_populates="concepto")


class RegistroFinancieroApartamento(SQLModel, table=True):
    __tablename__ = "registro_financiero_apartamento"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    apartamento_id: int = Field(foreign_key="apartamento.id")
    fecha_registro: datetime = Field(default_factory=datetime.now)
    fecha_efectiva: date
    concepto_id: int = Field(foreign_key="concepto.id")
    descripcion_adicional: Optional[str] = None
    monto: Decimal = Field(decimal_places=2, max_digits=12)
    mes_aplicable: Optional[int] = None
    año_aplicable: Optional[int] = None
    documento_soporte_path: Optional[str] = Field(default=None, max_length=512)
    referencia_pago: Optional[str] = Field(default=None, max_length=100)
    tipo_movimiento: str = Field(max_length=10)
    
    # Relaciones
    apartamento: "Apartamento" = Relationship(back_populates="registros_financieros")
    concepto: Concepto = Relationship(back_populates="registros_financieros")


class CuotaConfiguracion(SQLModel, table=True):
    __tablename__ = "cuota_configuracion"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    apartamento_id: int = Field(foreign_key="apartamento.id")
    año: int
    mes: int
    monto_cuota_ordinaria_mensual: Decimal = Field(decimal_places=2, max_digits=12)
    
    # Relaciones
    apartamento: "Apartamento" = Relationship(back_populates="cuotas_configuracion")


class TasaInteresMora(SQLModel, table=True):
    __tablename__ = "tasa_interes_mora"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    año: int
    mes: int
    tasa_interes_mensual: Decimal = Field(decimal_places=4, max_digits=5)


class ControlProcesamientoMensual(SQLModel, table=True):
    __tablename__ = "control_procesamiento_mensual"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    año: int
    mes: int
    tipo_procesamiento: str = Field(max_length=50)
    fecha_procesamiento: datetime
    registros_procesados: int
    monto_total_generado: Decimal = Field(decimal_places=2, max_digits=12)
    estado: str = Field(max_length=20)
    observaciones: Optional[str] = None

    # Índices para optimizar consultas
    __table_args__ = (
        Index('idx_control_año_mes_tipo', 'año', 'mes', 'tipo_procesamiento'),
        Index('idx_control_fecha', 'fecha_procesamiento'),
        # Constraint único para evitar duplicados
        {'extend_existing': True}
    )


class PresupuestoAnual(SQLModel, table=True):
    __tablename__ = "presupuesto_anual"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    año: int
    descripcion: Optional[str] = None
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    fecha_actualizacion: datetime = Field(default_factory=datetime.now)
    
    # Relaciones
    items_presupuesto: list["ItemPresupuesto"] = Relationship(back_populates="presupuesto_anual")
    gastos_comunidad: list["GastoComunidad"] = Relationship(back_populates="presupuesto_anual")


class ItemPresupuesto(SQLModel, table=True):
    __tablename__ = "item_presupuesto"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    presupuesto_anual_id: int = Field(foreign_key="presupuesto_anual.id")
    concepto_id: int = Field(foreign_key="concepto.id")
    mes: int
    monto_presupuestado: Decimal = Field(decimal_places=2, max_digits=12)
    tipo_item: str = Field(max_length=7)
    
    # Relaciones
    presupuesto_anual: PresupuestoAnual = Relationship(back_populates="items_presupuesto")
    concepto: Concepto = Relationship(back_populates="items_presupuesto")


class GastoComunidad(SQLModel, table=True):
    __tablename__ = "gasto_comunidad"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    fecha_gasto: date
    concepto_id: int = Field(foreign_key="concepto.id")
    descripcion_adicional: Optional[str] = None
    monto: Decimal = Field(decimal_places=2, max_digits=12)
    documento_soporte_path: Optional[str] = Field(default=None, max_length=512)
    presupuesto_anual_id: Optional[int] = Field(default=None, foreign_key="presupuesto_anual.id")
    mes_gasto: Optional[int] = None
    año_gasto: int
    
    # Relaciones
    concepto: Concepto = Relationship(back_populates="gastos_comunidad")
    presupuesto_anual: Optional[PresupuestoAnual] = Relationship(back_populates="gastos_comunidad")