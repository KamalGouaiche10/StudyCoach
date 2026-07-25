from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

# path assoluto basato sulla posizione del file ─────────────────────
# Con un path relativo ("./data/study_coach.db") SQLite dipende dalla
# working directory di chi avvia lo script. Quando si esegue app/main.py
# direttamente (non con `streamlit run`) la cwd non è la root del progetto
# e la cartella data/ non viene trovata → OperationalError.
# Usando Path(__file__) il path è sempre relativo al file models.py,
# indipendentemente da dove viene lanciato il processo.
_DB_DIR = Path(__file__).parent.parent.parent / "data"
_DB_DIR.mkdir(parents=True, exist_ok=True)

def now_utc():
    return datetime.now(timezone.utc)

class Student(Base):
    """Rappresenta uno studente registrato nel sistema Study Coach.

    Attributi:
        id: Identificativo univoco dello studente.
        username: Nome utente univoco.
        password_hash: Hash della password memorizzata in modo sicuro.
        session_token: Token persistente per il login automatico via cookie
            (vedi backend/session_cookie.py). None se non ha mai effettuato
            un login "ricordami" o dopo un logout esplicito.
        created_at: Data e ora di creazione del record.
        exams: Collezione degli esami associati allo studente.
    """
    __tablename__ = "students"
    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    session_token = Column(String(64), unique=True, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=now_utc)
    exams         = relationship("Exam", back_populates="student", cascade="all, delete")

class Exam(Base):
    """Rappresenta un esame associato a uno studente.

    Attributi:
        id: Identificativo univoco dell'esame.
        student_id: Chiave esterna verso lo studente proprietario.
        name: Nome dell'esame.
        created_at: Data e ora di creazione del record.
        student: Riferimento allo studente associato.
        sessions: Collezione delle sessioni di studio legate all'esame.
        materials: Collezione dei materiali (PDF) caricati per l'esame.
    """
    __tablename__ = "exams"
    id         = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    name       = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)
    student    = relationship("Student", back_populates="exams")
    sessions   = relationship("Session", back_populates="exam", cascade="all, delete")
    materials  = relationship("Material", back_populates="exam", cascade="all, delete")

class Material(Base):
    """Rappresenta un materiale (PDF) caricato per uno studio.

    Attributi:
        id: Identificativo univoco del materiale.
        exam_id: Chiave esterna verso l'esame associato.
        filename: Nome del file originale.
        stored_path: Percorso del file salvato nel filesystem.
        chunks_count: Numero di chunk indicizzati.
        pages_count: Numero di pagine nel PDF.
        uploaded_at: Data e ora di caricamento.
        exam: Riferimento all'esame associato.
    """
    __tablename__ = "materials"
    id           = Column(Integer, primary_key=True)
    exam_id      = Column(Integer, ForeignKey("exams.id"), nullable=False)
    filename     = Column(String(255), nullable=False)
    stored_path  = Column(String(500), nullable=False)
    chunks_count = Column(Integer, default=0)
    pages_count  = Column(Integer, default=0)
    uploaded_at  = Column(DateTime(timezone=True), default=now_utc)
    exam         = relationship("Exam", back_populates="materials")

class Session(Base):
    """Rappresenta una sessione di studio o interrogazione per un esame.

    Attributi:
        id: Identificativo univoco della sessione.
        exam_id: Chiave esterna verso l'esame associato.
        started_at: Data e ora di inizio sessione.
        ended_at: Data e ora di fine sessione, se presente.
        score_total: Punteggio complessivo ottenuto nella sessione.
        qa_log: Log JSON serializzato delle domande e risposte.
        report_path: Percorso del report generato per la sessione.
        exam: Riferimento all'esame associato.
    """
    __tablename__ = "sessions"
    id          = Column(Integer, primary_key=True)
    exam_id     = Column(Integer, ForeignKey("exams.id"), nullable=False)
    started_at  = Column(DateTime(timezone=True), default=now_utc)
    ended_at    = Column(DateTime(timezone=True), nullable=True)
    score_total = Column(Float, nullable=True)
    qa_log      = Column(Text, nullable=True)   # JSON serializzato
    report_path = Column(String(200), nullable=True)
    exam        = relationship("Exam", back_populates="sessions")

engine = create_engine(f"sqlite:///{_DB_DIR / 'study_coach.db'}", echo=False)

def init_db():
    Base.metadata.create_all(engine)
    _ensure_session_token_column()


def _ensure_session_token_column():
    """
    Migrazione leggera per DB creati prima dell'introduzione del login
    persistente: aggiunge la colonna session_token se mancante.
    Nota: SQLite non permette di aggiungere un vincolo UNIQUE con ALTER
    TABLE; la colonna aggiunta in questo modo non ha quindi un vincolo
    UNIQUE a livello di DB (i token restano comunque generati con
    secrets.token_urlsafe(32), quindi la probabilità di collisione è
    trascurabile). Sui DB creati da zero il vincolo UNIQUE è presente
    normalmente perché definito nel modello ORM.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "students" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("students")]
    if "session_token" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE students ADD COLUMN session_token VARCHAR(64)"))

SessionLocal = sessionmaker(bind=engine)