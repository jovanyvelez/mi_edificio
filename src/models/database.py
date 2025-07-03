from dotenv import load_dotenv
import os
from contextlib import contextmanager
from sqlmodel import Session, create_engine, SQLModel
from typing import Generator

from supabase import create_client, Client


# Cargar variables de entorno desde el archivo .env en la raíz del proyecto
load_dotenv()

DATABASE_URL = os.environ.get('DATABASE_URL')

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')
SUPABASE_BUCKET = os.getenv('SUPABASE_BUCKET')

if not all([SUPABASE_URL, SUPABASE_KEY, DATABASE_URL, SUPABASE_BUCKET]):
    raise EnvironmentError("One or more Supabase environment variables are missing.")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)




engine = create_engine(DATABASE_URL, echo=False)

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
