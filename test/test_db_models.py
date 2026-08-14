"""Unit/integration test — backend/db/models.py."""

from backend.db.models import Exam, Material, SessionLocal, Session as DbSession, Student, init_db


def test_init_db_is_idempotent():
    init_db()
    init_db()  # non deve sollevare eccezioni ne' duplicare tabelle


def test_create_student_and_exam_relationship():
    db = SessionLocal()
    try:
        student = Student(username="mario", password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)

        exam = Exam(student_id=student.id, name="Analisi 1")
        db.add(exam)
        db.commit()
        db.refresh(student)

        assert len(student.exams) == 1
        assert student.exams[0].name == "Analisi 1"
    finally:
        db.close()


def test_deleting_student_cascades_to_exams():
    db = SessionLocal()
    try:
        student = Student(username="mario", password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)

        exam = Exam(student_id=student.id, name="Analisi 1")
        db.add(exam)
        db.commit()
        exam_id = exam.id

        db.delete(student)
        db.commit()

        assert db.query(Exam).filter(Exam.id == exam_id).first() is None
    finally:
        db.close()


def test_deleting_exam_cascades_to_sessions_and_materials():
    db = SessionLocal()
    try:
        student = Student(username="mario", password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)

        exam = Exam(student_id=student.id, name="Analisi 1")
        db.add(exam)
        db.commit()
        db.refresh(exam)

        sess = DbSession(exam_id=exam.id)
        material = Material(exam_id=exam.id, filename="a.pdf", stored_path="/tmp/a.pdf")
        db.add_all([sess, material])
        db.commit()
        sess_id, material_id = sess.id, material.id

        db.delete(exam)
        db.commit()

        assert db.query(DbSession).filter(DbSession.id == sess_id).first() is None
        assert db.query(Material).filter(Material.id == material_id).first() is None
    finally:
        db.close()


def test_student_username_unique_constraint():
    db = SessionLocal()
    try:
        db.add(Student(username="mario", password_hash="h1"))
        db.commit()

        db.add(Student(username="mario", password_hash="h2"))
        try:
            db.commit()
            assert False, "doveva sollevare un errore di integrita'"
        except Exception:
            db.rollback()
    finally:
        db.close()


def test_session_defaults_and_optional_fields():
    db = SessionLocal()
    try:
        student = Student(username="mario", password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)

        exam = Exam(student_id=student.id, name="Analisi 1")
        db.add(exam)
        db.commit()
        db.refresh(exam)

        sess = DbSession(exam_id=exam.id)
        db.add(sess)
        db.commit()
        db.refresh(sess)

        assert sess.started_at is not None
        assert sess.ended_at is None
        assert sess.score_total is None
        assert sess.qa_log is None
    finally:
        db.close()
