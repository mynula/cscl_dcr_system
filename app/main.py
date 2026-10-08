from contextlib import asynccontextmanager
import logging
from typing import Optional
from fastapi import FastAPI, Depends, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, Base, ensure_table_columns, get_db
import app.models  # Ensure all models are registered with Base.metadata
from app.models.user import User
from app.models.dcr import FactDCR
from app.services.auth_service import get_current_user_optional
from app.services.seed_data import seed_database_defaults

from app.routers.auth import router as auth_router
from app.routers.dcr import router as dcr_router
from app.routers.dashboard import router as dashboard_router
from app.routers.admin import router as admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("cscl_dcr_system")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Create tables and seed initial master data
    logger.info("Initializing CSCL DCR System database schema...")
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("All database tables verified / generated.")
        ensure_table_columns(FactDCR.__table__)
        
        if settings.APP_ENV.lower() != "production":
            with Session(engine) as session:
                seed_database_defaults(session)
        else:
            logger.info("Skipping development seed data in production.")
    except Exception as e:
        logger.error("Database initialization failed (%s).", type(e).__name__)
        if settings.APP_ENV.lower() == "production":
            raise RuntimeError("Production database initialization failed.") from None

    yield

    # Shutdown
    logger.info("Shutting down CSCL DCR System...")


app = FastAPI(
    title=settings.APP_NAME,
    description="CSCL Daily Call Report (DCR) System - Pharmaceutical & Field Force Automation",
    version="1.0.0",
    debug=settings.debug_enabled,
    lifespan=lifespan
)

# Mount static assets
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Register feature routers
app.include_router(auth_router)
app.include_router(dcr_router)
app.include_router(dashboard_router)
app.include_router(admin_router)


@app.get("/")
async def root(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Root redirector: sends logged in users to Dashboard, else to Login."""
    if current_user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return RedirectResponse(url="/auth/login", status_code=302)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
