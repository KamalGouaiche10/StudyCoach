"""
test_sanity.py — Smoke test per verificare la struttura del progetto

Verifica che i moduli principali possano essere importati senza errori.
"""

import pytest


class TestImports:
    """Test: verificazione import moduli principali."""

    def test_import_backend_models(self):
        """Verifica import backend.db.models."""
        try:
            from backend.db.models import Student, Exam, Session as DbSession, init_db
            assert Student is not None
            assert Exam is not None
            assert DbSession is not None
            assert init_db is not None
        except ImportError as e:
            pytest.fail(f"Fallito import backend.db.models: {e}")

    def test_import_backend_schemas(self):
        """Verifica import backend.models.schemas."""
        try:
            from backend.models.schemas import (
                RegisterRequest, LoginRequest, ExamCreate, QuizGenerateRequest,
                SessionCreate, TutorStartRequest,
            )
            assert RegisterRequest is not None
            assert LoginRequest is not None
            assert ExamCreate is not None
            assert QuizGenerateRequest is not None
            assert SessionCreate is not None
            assert TutorStartRequest is not None
        except ImportError as e:
            pytest.fail(f"Fallito import backend.models.schemas: {e}")

    def test_import_agents(self):
        """Verifica import agenti principali."""
        try:
            from backend.agents.ingestor import ingest_pdf, retrieve_chunks
            from backend.agents.quiz_generator import generate_quiz
            from backend.agents.socratic_tutor import SocraticTutor
            from backend.agents.adaptive_engine import AdaptiveEngine
            from backend.agents.report_generator import generate_markdown, generate_pdf
            assert ingest_pdf is not None
            assert retrieve_chunks is not None
            assert generate_quiz is not None
            assert SocraticTutor is not None
            assert AdaptiveEngine is not None
            assert generate_markdown is not None
            assert generate_pdf is not None
        except ImportError as e:
            pytest.fail(f"Fallito import agenti: {e}")

    def test_import_api_routers(self):
        """Verifica import API routers."""
        try:
            from backend.api.auth import router as auth_router
            from backend.api.exams import router as exams_router
            from backend.api.sessions import router as sessions_router
            assert auth_router is not None
            assert exams_router is not None
            assert sessions_router is not None
        except ImportError as e:
            pytest.fail(f"Fallito import API routers: {e}")

    def test_import_fastapi_app(self):
        """Verifica import applicazione FastAPI."""
        try:
            from backend.api.main import app
            assert app is not None
        except ImportError as e:
            pytest.fail(f"Fallito import backend.api.main: {e}")


class TestStructure:
    """Test: verificazione struttura file/directory."""

    def test_data_directories_exist(self):
        """Verifica che le directory di data esistono."""
        from pathlib import Path
        assert Path("data").exists()
        assert Path("data/uploads").exists()
        assert Path("data/chroma").exists()
        assert Path("reports").exists()

    def test_backend_structure(self):
        """Verifica struttura backend."""
        from pathlib import Path
        assert Path("backend").is_dir()
        assert Path("backend/api").is_dir()
        assert Path("backend/agents").is_dir()
        assert Path("backend/db").is_dir()
        assert Path("backend/models").is_dir()

    def test_app_structure(self):
        """Verifica struttura app."""
        from pathlib import Path
        assert Path("app").is_dir()
        assert Path("app/pages").is_dir()
        assert Path("app/main.py").is_file()


class TestConfig:
    """Test: verificazione configurazione."""

    def test_env_file_exists(self):
        """Verifica che .env esiste."""
        from pathlib import Path
        if not Path(".env").exists():
            pytest.skip(".env non trovato (normale in CI). Usa .env.example")

    def test_env_example_exists(self):
        """Verifica che .env.example esiste."""
        from pathlib import Path
        assert Path(".env.example").exists(), ".env.example non trovato!"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

