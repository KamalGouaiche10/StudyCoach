"""
backend/api/main.py — Entry point FastAPI per Study Coach

Avvio:
    uvicorn backend.api.main:app --reload --port 8000

Docs interattive:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.auth import router as auth_router
from backend.api.exams import router as exams_router
from backend.api.sessions import router as sessions_router
from backend.db.models import init_db

# ---------------------------------------------------------------------------
# Inizializzazione app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inizializza risorse all'avvio dell'applicazione."""
    init_db()
    print("[StudyCoach API] Database inizializzato. Server pronto.")
    yield


app = FastAPI(
    title="Study Coach API",
    description=(
        "API per il tutor AI universitario basato su RAG + Gemini. "
        "Supporta autenticazione studenti, gestione esami, "
        "indicizzazione PDF, generazione quiz e loop socratico adattivo."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — permette al frontend Streamlit (localhost:8501) di chiamare l'API
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(exams_router)
app.include_router(sessions_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/health", tags=["system"], summary="Health check")
def health() -> dict:
    return {"status": "ok", "service": "Study Coach API"}