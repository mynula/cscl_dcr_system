from app.routers.auth import router as auth_router
from app.routers.dcr import router as dcr_router
from app.routers.dashboard import router as dashboard_router
from app.routers.admin import router as admin_router

__all__ = [
    "auth_router",
    "dcr_router",
    "dashboard_router",
    "admin_router"
]
