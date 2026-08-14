"""Unit/integration test — backend/agents/report_generator.py."""

from backend.agents import report_generator as rg


def _sample_report(avg=7.5):
    return {
        "student_id": 1,
        "exam_id": 2,
        "overall_avg": avg,
        "n_questions_answered": 3,
        "weak_topics": ["derivate"],
        "strong_topics": ["limiti"],
        "topic_breakdown": [
            {"topic": "limiti", "avg_score": 9.0, "n_attempts": 2, "is_weak": False},
            {"topic": "derivate", "avg_score": 4.0, "n_attempts": 1, "is_weak": True},
        ],
        "summary": "Prestazione sufficiente con margini di miglioramento.",
    }


# ---------------------------------------------------------------------------
# generate_markdown
# ---------------------------------------------------------------------------

def test_generate_markdown_contains_key_sections():
    md = rg.generate_markdown(_sample_report(), session_id=5, exam_name="Analisi 1")
    assert "Analisi 1" in md
    assert "Sessione ID:** 5" in md
    assert "7.5/10" in md
    assert "derivate" in md
    assert "limiti" in md


def test_generate_markdown_verdict_thresholds():
    assert "🟢 Ottimo" in rg.generate_markdown(_sample_report(avg=9), session_id=1)
    assert "🟡 Sufficiente" in rg.generate_markdown(_sample_report(avg=6.5), session_id=1)
    assert "🔴 Insufficiente" in rg.generate_markdown(_sample_report(avg=3), session_id=1)


def test_generate_markdown_no_weak_topics_message():
    report = _sample_report()
    report["weak_topics"] = []
    md = rg.generate_markdown(report, session_id=1)
    assert "Nessuna area critica" in md


def test_generate_markdown_no_strong_topics_message():
    report = _sample_report()
    report["strong_topics"] = []
    md = rg.generate_markdown(report, session_id=1)
    assert "Continua a studiare" in md


# ---------------------------------------------------------------------------
# generate_pdf
# ---------------------------------------------------------------------------

def test_generate_pdf_returns_nonempty_bytes():
    pdf_bytes = rg.generate_pdf(_sample_report(), session_id=1, exam_name="Analisi 1")
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"
    assert len(pdf_bytes) > 500


def test_pdf_safe_text_replaces_unicode_punctuation():
    assert rg._pdf_safe_text("è un test’ “citato”") == "e un test' \"citato\""


def test_pdf_safe_text_strips_unsupported_chars():
    # Emoji e caratteri fuori range latin-1 vengono rimossi silenziosamente.
    result = rg._pdf_safe_text("voto ✅ ok 😀")
    assert "😀" not in result
    assert "OK" in result


# ---------------------------------------------------------------------------
# save_report (I/O isolato in tmp_path via fixture isolated_reports_dir)
# ---------------------------------------------------------------------------

def test_save_report_writes_md_and_pdf(isolated_reports_dir):
    paths = rg.save_report(_sample_report(), session_id=9, exam_name="Analisi 1")

    md_path = isolated_reports_dir / paths["md"].split("\\")[-1].split("/")[-1]
    pdf_path = isolated_reports_dir / paths["pdf"].split("\\")[-1].split("/")[-1]

    assert md_path.exists()
    assert pdf_path.exists()
    assert md_path.read_text(encoding="utf-8").startswith("# Report Sessione")
    assert pdf_path.read_bytes()[:4] == b"%PDF"


def test_save_report_filename_includes_ids(isolated_reports_dir):
    paths = rg.save_report(_sample_report(), session_id=9, exam_name="Analisi 1")
    assert "1_2_9" in paths["md"]
    assert "1_2_9" in paths["pdf"]
