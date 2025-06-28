from .auth import router as auth_router
from .admin import router as admin_router
from .admin_pagos import router as admin_pagos_router
from .propietario import router as propietario_router

__all__ = ["auth_router", "admin_router", "admin_pagos_router", "propietario_router"]