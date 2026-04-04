from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Import all route modules
from app.routes.contracts import router as contracts_router
from app.routes.auth import router as auth_router
from app.routes.ai import router as ai_router
from app.routes.dashboard import router as dashboard_router
from app.routes.workflows import router as workflows_router
from app.routes.approvals import router as approvals_router
from app.routes.templates import router as templates_router
from app.routes.notifications import router as notifications_router
from app.routes.audit import router as audit_router
from app.routes.calendar import router as calendar_router
from app.routes.admin import router as admin_router
from app.routes.documents import router as documents_router

app = FastAPI(
    title="CLAUSE - Contract Lifecycle Management System",
    description="AI-powered CLM system for small and medium scale IT enterprises",
    version="1.0.0",
)

# CORS middleware - allows the React frontend to communicate with the backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",  # Vite dev server
        "http://localhost:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register all routers
app.include_router(auth_router)
app.include_router(contracts_router)
app.include_router(workflows_router)
app.include_router(approvals_router)
app.include_router(templates_router)
app.include_router(ai_router)
app.include_router(dashboard_router)
app.include_router(notifications_router)
app.include_router(audit_router)
app.include_router(calendar_router)
app.include_router(admin_router)
app.include_router(documents_router)


@app.get("/")
def root():
    return {"message": "CLAUSE CLM Backend is running"}


@app.get("/health")
def health_check():
    from app.config import client
    try:
        client.admin.command("ping")
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return {
        "status": "healthy",
        "service": "clause-backend",
        "version": "1.0.0",
        "database": db_status,
    }
