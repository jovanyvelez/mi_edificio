from typing import Optional, TYPE_CHECKING
from datetime import datetime
from sqlmodel import SQLModel, Field, Relationship
from enum import Enum

if TYPE_CHECKING:
    from .apartment import Apartamento


class RolUsuarioEnum(str, Enum):
    ADMIN = "ADMIN"
    PROPIETARIO = "PROPIETARIO"


class Usuario(SQLModel, table=True):
    __tablename__ = "usuario"

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(max_length=100)
    email: str = Field(max_length=255)
    hashed_password: str = Field(max_length=255)
    nombre_completo: Optional[str] = Field(default=None, max_length=255)
    rol: str = Field(max_length=20)
    is_active: bool = Field(default=True)
    propietario_id: Optional[int] = Field(default=None, foreign_key="propietario.id")
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    fecha_actualizacion: datetime = Field(default_factory=datetime.now)

    # Relación con propietario (un usuario puede estar asociado a un propietario)
    propietario: Optional["Propietario"] = Relationship(back_populates="usuario")


class Propietario(SQLModel, table=True):
    __tablename__ = "propietario"

    id: Optional[int] = Field(default=None, primary_key=True)
    nombre_completo: str = Field(max_length=255)
    documento_identidad: str = Field(max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    telefono: Optional[str] = Field(default=None, max_length=50)
    datos_adicionales: Optional[str] = None
    fecha_creacion: datetime = Field(default_factory=datetime.now)
    fecha_actualizacion: datetime = Field(default_factory=datetime.now)
    
    # Relaciones
    apartamentos: list["Apartamento"] = Relationship(back_populates="propietario")
    usuario: Optional["Usuario"] = Relationship(back_populates="propietario")
