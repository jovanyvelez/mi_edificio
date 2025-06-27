from dotenv import load_dotenv
import os
from contextlib import contextmanager
from sqlmodel import Session, create_engine, SQLModel
from typing import Generator


# Cargar variables de entorno desde el archivo .env en la raíz del proyecto
load_dotenv()

url_database = os.environ.get('DATABASE_URL')

if not url_database:
    raise ValueError("DATABASE_URL no está configurada en las variables de entorno")


engine = create_engine(url_database, echo=False)

class DatabaseManager:
    def __init__(self, engine):
        self.engine = engine

    # Para uso con FastAPI Depends
    def get_session(self) -> Generator[Session, None, None]:
        session = Session(self.engine)
        try:
            yield session
        finally:
            session.close()

    # Para uso manual con context manager
    @contextmanager
    def get_session_context(self):
        session = Session(self.engine)
        try:
            yield session
        finally:
            session.close()

    def get_engine(self):
        return self.engine

# Instancia global del manager de base de datos
db_manager = DatabaseManager(engine)

def create_db_and_tables():
    """
    Crea todas las tablas definidas en los modelos SQLModel
    """
    SQLModel.metadata.create_all(engine)
