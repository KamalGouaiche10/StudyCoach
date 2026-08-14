"""Unit/integration test — backend/session_cookie.py (token persistente)."""

from backend.db.models import SessionLocal, Student
from backend.session_cookie import get_or_create_token, invalidate_token, verify_token


def _create_student(username="mario") -> int:
    db = SessionLocal()
    try:
        student = Student(username=username, password_hash="hash")
        db.add(student)
        db.commit()
        db.refresh(student)
        return student.id
    finally:
        db.close()


def test_get_or_create_token_generates_new_token():
    student_id = _create_student()
    token = get_or_create_token(student_id)
    assert token
    assert len(token) > 20


def test_get_or_create_token_is_stable_across_calls():
    student_id = _create_student()
    token1 = get_or_create_token(student_id)
    token2 = get_or_create_token(student_id)
    assert token1 == token2


def test_get_or_create_token_returns_none_for_unknown_student():
    assert get_or_create_token(999999) is None


def test_verify_token_returns_matching_student():
    student_id = _create_student("giulia")
    token = get_or_create_token(student_id)

    student = verify_token(token)
    assert student is not None
    assert student.id == student_id
    assert student.username == "giulia"


def test_verify_token_returns_none_for_invalid_token():
    assert verify_token("token-inesistente") is None


def test_verify_token_returns_none_for_empty_token():
    assert verify_token("") is None


def test_invalidate_token_clears_it():
    student_id = _create_student()
    token = get_or_create_token(student_id)
    assert verify_token(token) is not None

    invalidate_token(student_id)

    assert verify_token(token) is None


def test_invalidate_token_noop_for_falsy_id():
    invalidate_token(None)  # non deve sollevare eccezioni
