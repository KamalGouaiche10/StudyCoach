from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

def now_utc():
    return datetime.now(timezone.utc)

class Student(Base):
    """Rappresenta uno studente registrato nel sistema Study Coach.

    Attributi:
        id: Identificativo univoco dello studente.
        username: Nome utente univoco.
        password_hash: Hash della password memorizzata in modo sicuro.
        created_at: Data e ora di creazione del record.
        exams: Collezione degli esami associati allo studente.
    """
    __tablename__ = "students"
    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
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
    """
    __tablename__ = "exams"
    id         = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    name       = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)
    student    = relationship("Student", back_populates="exams")
    sessions   = relationship("Session", back_populates="exam", cascade="all, delete")

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

engine = create_engine("sqlite:///./data/study_coach.db", echo=False)

def init_db():
    Base.metadata.create_all(engine)

SessionLocal = sessionmaker(bind=engine)