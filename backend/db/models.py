from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

Base = declarative_base()

def now_utc():
    return datetime.now(timezone.utc)

class Student(Base):
    __tablename__ = "students"
    id            = Column(Integer, primary_key=True)
    username      = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(128), nullable=False)
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

engine = create_engine("sqlite:///./data/study_coach.db", echo=False)

def init_db():
    Base.metadata.create_all(engine)

SessionLocal = sessionmaker(bind=engine)