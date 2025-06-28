from fastapi import FastAPI

# Importar configuración.
from src.settings import settings
from src.routes import auth_router, admin_router, admin_pagos_router, propietario_router

#Crear la aplicación FastAPI
app = FastAPI(
    title=settings.APP_TITLE,
    description=settings.APP_DESCRIPTION,
    version=settings.APP_VERSION,
)


app.include_router(auth_router)
app.include_router(admin_router, prefix="")
app.include_router(admin_pagos_router, prefix="/admin/pagos")
app.include_router(propietario_router, prefix="/propietario")