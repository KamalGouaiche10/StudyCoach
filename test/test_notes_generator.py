"""Unit/integration test — backend/agents/notes_generator.py."""

from backend.agents import notes_generator as ng

FAKE_VALID_NOTES = (
    "## Introduzione\n\n"
    "> **Definizione**: il machine learning e' una tecnica di apprendimento dai dati.\n\n"
    + ("concetto " * 700)
    + "\n\n## Riepilogo\n\nFine degli appunti.\n"
)


# ---------------------------------------------------------------------------
# _is_error_response / _parse_error_retry_time
# ---------------------------------------------------------------------------

def test_is_error_response_detects_rate_limit_message():
    assert ng._is_error_response('{"message": "Rate limit reached", "type": "tokens"}')


def test_is_error_response_false_for_normal_text():
    assert not ng._is_error_response("## Introduzione\nTesto normale di appunti.")


def test_is_error_response_empty_text_is_error():
    assert ng._is_error_response("")


def test_parse_error_retry_time_hms_format():
    assert ng._parse_error_retry_time("try again in 1h2m3.5s") == 3723.5


def test_parse_error_retry_time_minutes_only():
    assert ng._parse_error_retry_time("please wait 5 minutes") == 300


def test_parse_error_retry_time_fractional_seconds_and_no_fallback():
    assert ng._parse_error_retry_time("Please try again in 37.3125s") == 37.3125
    assert ng._parse_error_retry_time("nessuna indicazione temporale") is None


def test_retry_delay_uses_server_delay_with_safety_margin():
    delay, source = ng._retry_delay(1, "Please try again in 37.3125s")
    assert delay == 38.3125
    assert source == "retry-after Groq"


def test_retry_delay_uses_capped_exponential_backoff(monkeypatch):
    monkeypatch.setattr(ng.random, "uniform", lambda *_: 0)
    delay, source = ng._retry_delay(20)
    assert delay == ng.MAX_BACKOFF_SECONDS
    assert source == "exponential backoff"


def test_retry_after_header_is_used():
    error = RuntimeError("too many requests")
    error.response = type("Response", (), {"headers": {"Retry-After": "12.5"}})()
    assert ng._retry_delay(1, error) == (13.5, "retry-after Groq")


def test_notes_agent_sets_model_and_completion_limit(monkeypatch):
    captured = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["model"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent"] = kwargs

    monkeypatch.setattr(ng, "Groq", FakeGroq)
    monkeypatch.setattr(ng, "Agent", FakeAgent)
    ng._make_notes_agent("openai/gpt-oss-120b")

    assert captured["model"] == {
        "id": "openai/gpt-oss-120b",
        "max_tokens": ng.MAX_COMPLETION_TOKENS,
    }
    assert "## Riepilogo" in captured["agent"]["description"]


# ---------------------------------------------------------------------------
# _pdf_safe_text / _strip_inline
# ---------------------------------------------------------------------------

def test_pdf_safe_text_normalizes_punctuation():
    assert ng._pdf_safe_text("l’esempio “giusto”") == "l'esempio \"giusto\""


def test_strip_inline_removes_bold_and_italic_markers():
    assert ng._strip_inline("**grassetto** e *corsivo*") == "grassetto e corsivo"


# ---------------------------------------------------------------------------
# _clean_chunk / _clean_chunks
# ---------------------------------------------------------------------------

def test_clean_chunk_removes_page_footer_noise():
    dirty = "Testo utile.\nStudy Coach - Pagina 3\nAltro testo utile qui."
    cleaned = ng._clean_chunk(dirty)
    assert "Pagina 3" not in cleaned
    assert "Testo utile" in cleaned


def test_clean_chunk_drops_lines_with_mostly_symbols():
    dirty = "Testo normale con contenuto.\n#$%^&*()!@#$%^&*()!!!\nAltra riga leggibile qui."
    cleaned = ng._clean_chunk(dirty)
    assert "#$%^&*()" not in cleaned


def test_clean_chunks_filters_too_short_results():
    chunks = ["breve", "questo e' un chunk abbastanza lungo da superare la soglia minima di ottanta caratteri di lunghezza"]
    cleaned = ng._clean_chunks(chunks)
    assert len(cleaned) == 1


# ---------------------------------------------------------------------------
# _validate_notes
# ---------------------------------------------------------------------------

def test_validate_notes_accepts_well_formed_text():
    ok, msg = ng._validate_notes(FAKE_VALID_NOTES)
    assert ok is True
    assert msg == ""


def test_validate_notes_rejects_empty():
    ok, msg = ng._validate_notes("")
    assert ok is False
    assert "vuoto" in msg.lower()


def test_validate_notes_rejects_too_short():
    ok, msg = ng._validate_notes("## Titolo\n\n> **Definizione**: breve.\n\n## Riepilogo\nFine.")
    assert ok is False
    assert "corto" in msg.lower()


def test_validate_notes_rejects_missing_required_section():
    text = ("## Titolo\n\n" + ("parola " * 700))  # manca Definizione e Riepilogo
    ok, msg = ng._validate_notes(text)
    assert ok is False


def test_validate_notes_accepts_small_markdown_variations_in_summary_heading():
    text = FAKE_VALID_NOTES.replace("## Riepilogo", "### **RIEPILOGO — punti chiave**")
    assert ng._validate_notes(text) == (True, "")


def test_validate_notes_identifies_only_missing_summary():
    text = FAKE_VALID_NOTES.replace("\n\n## Riepilogo\n\nFine degli appunti.\n", "")
    assert ng._validate_notes(text) == (False, "Manca: sezione ## Riepilogo")


def test_validate_notes_rejects_corrupted_latex():
    text = FAKE_VALID_NOTES + "\n\\alpha^*corrotto"
    ok, msg = ng._validate_notes(text)
    assert ok is False
    assert "LaTeX" in msg


# ---------------------------------------------------------------------------
# _build_log_summary / _extract_weak_topics
# ---------------------------------------------------------------------------

def test_build_log_summary_includes_question_and_score():
    attempts = [{
        "question_text": "Cos'e' un limite?",
        "topic_hint": "limiti",
        "final_score": 7,
        "student_answer_2": "Il valore a cui tende una funzione.",
        "evaluation": {"missing_points": ["manca il caso di limite infinito"]},
    }]
    summary = ng._build_log_summary(attempts)
    assert "Cos'e' un limite?" in summary
    assert "voto: 7/10" in summary
    assert "manca il caso di limite infinito" in summary


def test_extract_weak_topics_filters_low_scores_and_dedupes():
    attempts = [
        {"final_score": 3, "topic_hint": "derivate"},
        {"final_score": 8, "topic_hint": "limiti"},
        {"final_score": 4, "topic_hint": "derivate"},
        {"final_score": 2, "topic_hint": ""},  # topic vuoto, ignorato
    ]
    assert ng._extract_weak_topics(attempts) == ["derivate"]


# ---------------------------------------------------------------------------
# generate_notes (integrazione con FakeAgent + RAG finto)
# ---------------------------------------------------------------------------

def test_generate_notes_returns_agent_output(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(ng, "retrieve_chunks", lambda **kwargs: ["chunk di materiale " * 20])
    monkeypatch.setattr(ng, "_make_notes_agent", fake_agent_factory(FAKE_VALID_NOTES))

    notes = ng.generate_notes(student_id=1, exam_id=1, source_name="Analisi 1")
    assert notes == FAKE_VALID_NOTES.strip()


def test_generate_notes_raises_without_material(monkeypatch):
    monkeypatch.setattr(ng, "retrieve_chunks", lambda **kwargs: [])
    try:
        ng.generate_notes(student_id=1, exam_id=1)
        assert False, "doveva sollevare ValueError"
    except ValueError as e:
        assert "Nessun chunk" in str(e)


def test_generate_notes_retries_on_invalid_response(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(ng, "retrieve_chunks", lambda **kwargs: ["chunk di materiale " * 20])
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)
    # Prima risposta troppo corta (non valida) -> ritenta -> seconda risposta valida
    monkeypatch.setattr(ng, "_make_notes_agent", fake_agent_factory(["troppo corta", FAKE_VALID_NOTES]))

    notes = ng.generate_notes(student_id=1, exam_id=1)
    assert notes == FAKE_VALID_NOTES.strip()


def test_summary_missing_is_repaired_without_regenerating_full_notes(monkeypatch):
    first = FAKE_VALID_NOTES.replace("\n\n## Riepilogo\n\nFine degli appunti.\n", "")

    class FakeOutput:
        usage = {"prompt_tokens": 100, "completion_tokens": 800}

        def __init__(self, content):
            self.content = content

        def get_content_as_string(self):
            return self.content

    class FakeAgent:
        def __init__(self):
            self.calls = []
            self.responses = [first, "## Riepilogo\n\n1. Concetto fondamentale."]

        def run(self, prompt, stream=False):
            self.calls.append(prompt)
            return FakeOutput(self.responses[len(self.calls) - 1])

    agent = FakeAgent()
    notes = ng._run_with_retry(agent, "PROMPT ORIGINALE CON CONTESTO")
    assert notes.startswith(first)
    assert "## Riepilogo" in notes
    assert len(agent.calls) == 2
    assert "PROMPT ORIGINALE CON CONTESTO" not in agent.calls[1]
    assert "APPUNTI:" in agent.calls[1]


def test_rate_limit_exception_waits_for_retry_after_and_reuses_prompt(monkeypatch, capsys):
    sleeps = []
    monkeypatch.setattr(ng.time, "sleep", sleeps.append)

    class FakeOutput:
        def get_content_as_string(self):
            return FAKE_VALID_NOTES

    class FakeAgent:
        def __init__(self):
            self.calls = []

        def run(self, prompt, stream=False):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                error = RuntimeError("Rate limit reached secret-request-detail")
                error.status_code = 429
                error.response = type("Response", (), {"headers": {"Retry-After": "2.25"}})()
                raise error
            return FakeOutput()

    agent = FakeAgent()
    assert ng._run_with_retry(agent, "original prompt") == FAKE_VALID_NOTES.strip()
    assert sleeps == [3.25]
    assert agent.calls == ["original prompt", "original prompt"]
    assert "secret-request-detail" not in capsys.readouterr().out


def test_retry_limit_prevents_infinite_validation_loop(monkeypatch):
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)

    class FakeOutput:
        def get_content_as_string(self):
            return "invalid"

    class FakeAgent:
        def __init__(self):
            self.calls = 0

        def run(self, prompt, stream=False):
            self.calls += 1
            return FakeOutput()

    agent = FakeAgent()
    import pytest
    with pytest.raises(RuntimeError, match="validazione non superata"):
        ng._run_with_retry(agent, "prompt")
    assert agent.calls == ng.MAX_LLM_ATTEMPTS
