
import hashlib

from fastapi import APIRouter, HTTPException, status

from backend.db.models import SessionLocal, Student, init_db
from backend.models.schemas import AuthResponse, LoginRequest, RegisterRequest

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash_password(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()


def _get_student_by_username(username: str) -> Student | None:
    db = SessionLocal()
    try:
        return db.query(Student).filter(Student.username == username).first()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registra un nuovo studente",
)
def register(payload: RegisterRequest) -> AuthResponse:
    """
    Crea un nuovo account studente.
    - Username deve essere unico e lungo almeno 3 caratteri.
    - Password deve essere lunga almeno 6 caratteri.
    """
    init_db()
    existing = _get_student_by_username(payload.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' già in uso.",
        )

    db = SessionLocal()
    try:
        student = Student(
            username=payload.username,
            password_hash=_hash_password(payload.password),
        )
        db.add(student)
        db.commit()
        db.refresh(student)
        return AuthResponse(
            student_id=student.id,
            username=student.username,
            message="Account creato con successo.",
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Errore database durante la registrazione: {exc}",
        ) from exc
    finally:
        db.close()


@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Login studente",
)
def login(payload: LoginRequest) -> AuthResponse:
    """
    Verifica le credenziali e restituisce l'ID studente.

    Nota: questa API non emette JWT. L'autenticazione viene gestita
    lato Streamlit tramite session_state. Per un deploy con frontend
    separato aggiungere un middleware JWT (es. python-jose).
    """
    student = _get_student_by_username(payload.username.strip())
    if not student:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide.",
        )
    if student.password_hash != _hash_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenziali non valide.",
        )
    return AuthResponse(
        student_id=student.id,
        username=student.username,
        message="Login effettuato con successo.",
    )


@router.post(
    "/logout",
    summary="Logout (stateless — nessuna azione server)",
)
def logout() -> dict:
    return {"message": "Logout effettuato. Pulisci il token lato client."}