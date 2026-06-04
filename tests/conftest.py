"""
conftest.py — Pytest configuration for Study Coach

Fixture comuni per i test e setup di test environment.
"""

import pytest
import sys
from pathlib import Path

# Aggiungi la root del progetto al path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def mock_student_data():
    """Fixture: dati mock di uno studente."""
    return {
        "id": 1,
        "username": "test_student",
        "email": "test@example.com",
    }


@pytest.fixture
def mock_exam_data():
    """Fixture: dati mock di un esame."""
    return {
        "id": 1,
        "name": "Programmazione AI",
        "student_id": 1,
    }


@pytest.fixture
def mock_question_data():
    """Fixture: dati mock di una domanda."""
    return {
        "id": 1,
        "text": "Che cos'è l'attenzione nei Transformer?",
        "difficulty": "intermedia",
        "topic_hint": "Attention Mechanism",
    }

