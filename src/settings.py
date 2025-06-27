from pydantic import BaseModel

class Settings(BaseModel):
    """Configuración de la aplicación"""
    
    # Información de la aplicación
    APP_TITLE: str = "Sistema de Gestión Edificio Mirador de Altavista"
    APP_DESCRIPTION: str = "Sistema para la administración de zonas comunes de edificios residenciales"
    APP_VERSION: str = "0.1.0"
    
    # Directorios
    STATIC_DIR: str = "static"
    TEMPLATES_DIR: str = "templates"
    


settings = Settings()