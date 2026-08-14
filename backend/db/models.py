from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

_DB_DIR = Path(__file__).parent.parent.parent / "data"
_DB_DIR.mkdir(parents=True, exist_ok=True)

def now_utc():
    return datetime.now(timezone.utc)

class Student(Base):
    __tablename__ = "students"
    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
    session_token = Column(String(64), unique=True, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=now_utc)
    exams         = relationship("Exam", back_populates="student", cascade="all, delete")

class Exam(Base):
    __tablename__ = "exams"
    id         = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    name       = Column(String(100), nullable=False)
    created_at = Column(DateTime(timezone=True), default=now_utc)
    student    = relationship("Student", back_populates="exams")
    sessions   = relationship("Session", back_populates="exam", cascade="all, delete")
    materials  = relationship("Material", back_populates="exam", cascade="all, delete")

class Material(Base):
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
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "students" not in inspector.get_table_names():
        return
    columns = [c["name"] for c in inspector.get_columns("students")]
    if "session_token" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE students ADD COLUMN session_token VARCHAR(64)"))

SessionLocal = sessionmaker(bind=engine)