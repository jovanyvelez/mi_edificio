from typing import Optional, TYPE_CHECKING
from datetime import datetime
from decimal import Decimal
from sqlmodel import SQLModel, Field, Relationship

if TYPE_CHECKING:
    from .user import Propietario
    from .payment import RegistroFinancieroApartamento, CuotaConfiguracion


class Apartamento(SQLModel, table=True):
    __tablename__ = "apartamento"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    identificador: str = Field(max_length=50)
    coeficiente_copropiedad: Decimal = Field(decimal_places=6, max_digits=8)
    propietario_id: Optional[int] = Field(default=None, foreign_key="propietario.id")
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    fecha_actualizacion: datetime = Field(default_factory=datetime.now)
    
    # Relaciones
    propietario: Optional["Propietario"] = Relationship(back_populates="apartamentos")
    registros_financieros: list["RegistroFinancieroApartamento"] = Relationship(back_populates="apartamento")
    cuotas_configuracion: list["CuotaConfiguracion"] = Relationship(back_populates="apartamento")
