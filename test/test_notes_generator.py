"""Unit/integration test — backend/agents/notes_generator.py."""

import io
import pytest

from backend.agents import model_router, notes_generator as ng
from backend.agents.llm_errors import ModelServiceUnavailable, is_rate_limit_error

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


def test_is_error_response_ignores_rate_limit_phrase_inside_notes():
    assert not ng._is_error_response("## Introduzione\nIl server dice: Please try again in 5s.")


def test_bounded_context_keeps_multiple_excerpts_within_budget():
    chunks = [(f"Argomento {i} " * 400) for i in range(15)]
    context = ng._bounded_context(chunks)
    assert len(context) <= ng.MAX_CONTEXT_CHARS + 100
    assert "Argomento 0" in context
    assert "Argomento 5" in context
    assert "Argomento 14" not in context


def test_oversized_groq_response_has_actionable_error():
    payload = '{"error":{"message":"Request too large for model; please reduce your message size", "code":"rate_limit_exceeded"}}'
    error = ng._response_error(payload)
    assert "limite di token" in str(error)
    assert not ng.is_retryable_error(error)


def test_temporary_groq_rate_limit_response_is_retryable():
    payload = '{"error":{"message":"Rate limit reached. Please try again in 2.5s", "code":"rate_limit_exceeded"}}'
    error = ng._response_error(payload)
    assert ng.is_rate_limit_error(error)
    assert ng._retry_delay(1, error) == (3.5, "retry-after Groq")


def test_gemini_503_is_safe_and_retryable(monkeypatch):
    monkeypatch.setattr(ng, "provider_name", lambda *_: "Gemini")
    error = ng._response_error('{"error":{"code":503,"status":"UNAVAILABLE","message":"internal detail"}}')
    assert isinstance(error, ModelServiceUnavailable)
    assert error.status_code == 503
    assert "Gemini è temporaneamente non disponibile" in str(error)
    assert "internal detail" not in str(error)


def test_gemini_daily_quota_is_reported_without_waiting(monkeypatch):
    monkeypatch.setattr(ng, "provider_name", lambda *_: "Gemini")
    payload = ('{"error":{"code":429,"status":"RESOURCE_EXHAUSTED",'
               '"message":"Please retry in 5h51m50s",'
               '"details":[{"quotaId":"GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}}')
    sleeps = []
    monkeypatch.setattr(ng.time, "sleep", sleeps.append)

    class Output:
        status = "ERROR"

        def get_content_as_string(self):
            return payload

    class Agent:
        def __init__(self):
            self.calls = 0

        def run(self, prompt, stream=False):
            self.calls += 1
            return Output()

    agent = Agent()
    with pytest.raises(ng.RetryableLLMError, match="Quota giornaliera di richieste Gemini") as caught:
        ng._run_with_retry(agent, "prompt")
    assert caught.value.status_code == 429
    assert agent.calls == 1 and sleeps == []


def test_windows_connection_reset_from_failed_model_run_is_retryable(monkeypatch):
    monkeypatch.setattr(ng, "provider_name", lambda *_: "Gemini")
    error = ng._response_error("[WinError 10054] Connessione interrotta forzatamente dall'host remoto")
    assert isinstance(error, ModelServiceUnavailable)
    assert "Gemini" in str(error)
    assert "WinError" not in str(error)


def test_rate_limit_text_is_not_an_error():
    assert not is_rate_limit_error(RuntimeError("la media e' 429 e la varianza 500"))


def test_rate_limit_http_429_exception_is_detected():
    error = RuntimeError("Too Many Requests")
    error.status_code = 429
    assert is_rate_limit_error(error)


def test_is_error_response_empty_text_is_error():
    assert ng._is_error_response("")


def test_parse_error_retry_time_hms_format():
    assert ng._parse_error_retry_time("try again in 1h2m3.5s") == 3723.5


def test_parse_error_retry_time_minutes_and_seconds_format():
    assert ng._parse_error_retry_time("Please try again in 6m8.928s") == 368.928


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

    monkeypatch.setattr(model_router, "Groq", FakeGroq)
    monkeypatch.setattr(ng, "Agent", FakeAgent)
    ng._make_notes_agent("openai/gpt-oss-120b")

    assert captured["model"] == {
        "id": "openai/gpt-oss-120b",
        "max_tokens": ng.MAX_COMPLETION_TOKENS,
        "timeout": ng.LLM_TIMEOUT_SECONDS,
    }
    assert "## Riepilogo" in captured["agent"]["description"]


def test_notes_review_uses_json_mode_and_separate_token_budget(monkeypatch):
    captured = {}

    class FakeGroq:
        def __init__(self, **kwargs):
            captured["model"] = kwargs

    class FakeAgent:
        def __init__(self, **kwargs):
            captured["agent"] = kwargs

    monkeypatch.setattr(model_router, "Groq", FakeGroq)
    monkeypatch.setattr(ng, "Agent", FakeAgent)
    ng._make_notes_review_agent("openai/gpt-oss-120b")
    assert captured["model"]["max_tokens"] == ng.MAX_REVIEW_TOKENS
    assert captured["model"]["request_params"] == {
        "response_format": {"type": "json_object"}, "reasoning_effort": "low",
    }
    assert captured["agent"]["markdown"] is False


# ---------------------------------------------------------------------------
# pdf_text / _strip_inline
# ---------------------------------------------------------------------------

def test_pdf_text_preserves_accents_and_uses_readable_symbol_fallback():
    result = ng.pdf_text("Perché è già così: σ, μ, ∑ e ∫")
    assert "Perché è già così" in result
    assert "sigma" in result and "mu" in result


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


def test_clean_chunks_preserves_short_source_passages():
    chunks = ["breve", "questo e' un chunk abbastanza lungo da superare la soglia minima di ottanta caratteri di lunghezza"]
    cleaned = ng._clean_chunks(chunks)
    assert cleaned == chunks


def test_literature_prompt_and_validation_exclude_unsupported_math():
    template = ng._load_prompt_template()
    assert "Riconosci la disciplina" in template
    assert "soltanto se" in template
    assert "brevi\n   citazioni" in template
    source = "[Fonte: letteratura.pdf, p. 2]\nLeopardi descrive il rapporto tra memoria e desiderio."
    good = (
        "## Leopardi\n\nIl materiale descrive il rapporto fra memoria e desiderio "
        "nella poetica dell'autore (letteratura.pdf, p. 2).\n\n"
        "## Riepilogo\n\n- Memoria e desiderio sono collegati nella fonte."
    )
    assert ng._validate_notes(good, source) == (True, "")
    bad = good.replace("## Leopardi", "## Teoremi")
    assert "assenti dal materiale" in ng._validate_notes(bad, source)[1]


def test_passage_contexts_cover_every_page_without_losing_unicode():
    passages = [
        {"text": f"Pagina {i}: l’Infinito di Leopardi. " * 35, "source": "slide.pdf", "page": i}
        for i in range(1, 20)
    ]
    contexts = ng._passage_contexts(passages)
    assert len(contexts) > 1
    assert all(len(context) <= ng.MAX_CONTEXT_CHARS for context in contexts)
    joined = "\n".join(contexts)
    assert "[Fonte: slide.pdf, p. 1]" in joined
    assert "[Fonte: slide.pdf, p. 19]" in joined
    assert "l’Infinito" in joined


def test_passage_contexts_preserve_verse_layout():
    verse = "Sempre caro mi fu quest'ermo colle,\ne questa siepe, che da tanta parte"
    contexts = ng._passage_contexts([{"text": verse, "source": "poesia.pdf", "page": 1}])
    assert verse in contexts[0]


def test_repair_prompt_retains_source_evidence():
    repaired = ng._repair_prompt("## Teoremi", "non pertinente", "[Fonte: poesia.pdf, p. 4]\nVersi")
    assert "[Fonte: poesia.pdf, p. 4]" in repaired
    assert "elimina quelli non supportati" in repaired
    assert "Non restituire il documento completo" in repaired


def test_notes_patch_preserves_other_sections():
    original = "## Tema\nFatto inventato.\nFatto corretto.\n\n## Riepilogo\n- Fatto corretto."
    revised = ng._apply_notes_patch(original, '{"old": "Fatto inventato.", "replacement": ""}')
    assert revised == original.replace("Fatto inventato.", "", 1)
    with pytest.raises(ValueError, match="passaggio unico"):
        ng._apply_notes_patch(original, '{"old": "Fatto corretto.", "replacement": "Altro"}')


def test_notes_retry_applies_targeted_patch(monkeypatch):
    first = "## Teoremi\nLa memoria compare nei versi.\n\n## Riepilogo\n- Memoria nei versi."

    class Output:
        def __init__(self, content):
            self.content = content

        def get_content_as_string(self):
            return self.content

    class Agent:
        def __init__(self):
            self.calls = []

        def run(self, prompt, stream=False):
            self.calls.append(prompt)
            return Output(first if len(self.calls) == 1 else '{"old": "## Teoremi", "replacement": "## Memoria"}')

    agent = Agent()
    result = ng._run_with_retry(agent, "PROMPT", "[Fonte: versi.pdf, p. 1]\nLa memoria compare nei versi.")
    assert result == first.replace("## Teoremi", "## Memoria")
    assert "documento completo" in agent.calls[1]


def test_fidelity_review_removes_only_unsupported_claim(monkeypatch):
    class Output:
        def get_content_as_string(self):
            return '{"unsupported": ["Dante ha scritto i Promessi Sposi."]}'

    class Agent:
        def run(self, prompt, stream=False):
            assert "Leopardi parla della memoria" in prompt
            return Output()

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    notes = (
        "## Memoria\nLeopardi parla della memoria.\nDante ha scritto i Promessi Sposi.\n"
        "\n## Riepilogo\n- Il testo tratta la memoria."
    )
    result = ng._verify_notes_fidelity(notes, "Leopardi parla della memoria", "fake")
    assert "Dante" not in result
    assert "Leopardi parla" in result
    assert "## Riepilogo" in result


def test_fidelity_review_retries_empty_model_response(monkeypatch):
    responses = iter(["", '{"unsupported": []}'])
    calls = []

    class Output:
        def __init__(self, content):
            self.content = content

        def get_content_as_string(self):
            return self.content

    class Agent:
        def run(self, prompt, stream=False):
            calls.append(prompt)
            return Output(next(responses))

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)
    notes = "## Tema\nFatto documentato.\n\n## Riepilogo\n- Fatto documentato."
    assert ng._verify_notes_fidelity(notes, "Fatto documentato.", "fake") == notes
    assert len(calls) == 2


def test_fidelity_review_retries_gemini_503(monkeypatch):
    responses = iter([
        '{"error":{"code":503,"status":"UNAVAILABLE","message":"high demand"}}',
        '{"unsupported": []}',
    ])
    calls = []

    class Output:
        def __init__(self, content):
            self.content = content

        def get_content_as_string(self):
            return self.content

    class Agent:
        def run(self, prompt, stream=False):
            calls.append(prompt)
            return Output(next(responses))

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)
    notes = "## Tema\nFatto documentato.\n\n## Riepilogo\n- Fatto documentato."
    assert ng._verify_notes_fidelity(notes, "Fatto documentato.", "fake") == notes
    assert len(calls) == 2


def test_fidelity_review_retries_paraphrased_unsupported_claim(monkeypatch):
    responses = iter([
        '{"unsupported": ["Dante scrisse i Promessi Sposi."]}',
        '{"unsupported": ["Dante ha scritto i Promessi Sposi."]}',
    ])
    calls = []

    class Output:
        def get_content_as_string(self):
            return next(responses)

    class Agent:
        def run(self, prompt, stream=False):
            calls.append(prompt)
            return Output()

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    notes = ("## Tema\nFatto documentato.\nDante ha scritto i Promessi Sposi.\n\n"
             "## Riepilogo\n- Fatto documentato.")
    result = ng._verify_notes_fidelity(notes, "Fatto documentato.", "fake")
    assert "Dante" not in result
    assert len(calls) == 2
    assert "identica e continua" in calls[1]


def test_fidelity_review_never_accepts_repeated_empty_response(monkeypatch):
    calls = []

    class Output:
        def get_content_as_string(self):
            return ""

    class Agent:
        def run(self, prompt, stream=False):
            calls.append(prompt)
            return Output()

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    monkeypatch.setattr(ng.time, "sleep", lambda *_: None)
    with pytest.raises(ng.NotesReviewUnavailable):
        ng._verify_notes_fidelity("## Tema\nFatto.\n\n## Riepilogo\n- Fatto.", "Fatto.", "fake")
    assert len(calls) == ng.MAX_REVIEW_ATTEMPTS


def test_fidelity_review_exposes_rate_limit_instead_of_empty_review(monkeypatch):
    calls = []

    class Output:
        def get_content_as_string(self):
            return '{"error":{"message":"Rate limit reached. Please try again in 6m8s", "code":"rate_limit_exceeded"}}'

    class Agent:
        def run(self, prompt, stream=False):
            calls.append(prompt)
            return Output()

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    with pytest.raises(ng.RetryableLLMError) as caught:
        ng._verify_notes_fidelity("## Tema\nFatto.\n\n## Riepilogo\n- Fatto.", "Fatto.", "fake")
    assert ng.is_rate_limit_error(caught.value)
    assert "368" in str(caught.value)
    assert len(calls) == 1


def test_fidelity_review_rejects_unverifiable_review_output(monkeypatch):
    class Output:
        def get_content_as_string(self):
            return '{"unsupported": ["frase assente dagli appunti"]}'

    class Agent:
        def run(self, prompt, stream=False):
            return Output()

    monkeypatch.setattr(ng, "_make_notes_review_agent", lambda *_: Agent())
    with pytest.raises(ng.NotesReviewUnavailable, match="verifica"):
        ng._verify_notes_fidelity(
            "## Tema\nFatto documentato.\n\n## Riepilogo\n- Fatto documentato.",
            "Fatto documentato.", "fake",
        )


def test_merge_note_sections_keeps_one_final_summary():
    merged = ng._merge_note_sections([
        ("slide 1", "## Leopardi\nTema della memoria.\n\n## Riepilogo\n- Memoria."),
        ("slide 2", "## Manzoni\nTema della storia.\n\n## Riepilogo\n- Storia."),
    ])
    assert merged.count("## Riepilogo") == 1
    assert merged.index("## Riepilogo") > merged.index("## Manzoni")
    assert "- Memoria." in merged and "- Storia." in merged


def test_merge_note_sections_removes_truncated_summary_heading():
    merged = ng._merge_note_sections([
        ("parte 1", "## Leopardi\nTema.\n\n## Rie\n\n## Riepilogo\n- Tema."),
        ("parte 2", "## Dante\nOpera.\n\n## Riepilogo\n- Opera."),
    ])
    assert "## Rie\n" not in merged
    assert merged.count("## Riepilogo") == 1


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


def test_validate_notes_accepts_short_source_based_notes():
    ok, msg = ng._validate_notes("## Titolo\n\n> **Definizione**: breve.\n\n## Riepilogo\nFine.")
    assert (ok, msg) == (True, "")


def test_validate_notes_rejects_missing_required_section():
    text = ("## Titolo\n\n" + ("parola " * 700))
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
        {"final_score": 2, "topic_hint": ""},
    ]
    assert ng._extract_weak_topics(attempts) == ["derivate"]


# ---------------------------------------------------------------------------
# generate_notes (integrazione con FakeAgent + RAG finto)
# ---------------------------------------------------------------------------

def test_generate_notes_returns_agent_output(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(ng, "_verify_notes_fidelity", lambda notes, *_: notes)
    monkeypatch.setattr(ng, "retrieve_passages", lambda **kwargs: [
        {"text": "chunk di materiale " * 20, "source": "Analisi 1", "page": 1}
    ])
    monkeypatch.setattr(ng, "_make_notes_agent", fake_agent_factory(FAKE_VALID_NOTES))

    notes = ng.generate_notes(student_id=1, exam_id=1, source_name="Analisi 1")
    assert notes == FAKE_VALID_NOTES.strip()


def test_generate_notes_pdf_preserves_accents_and_symbols(monkeypatch):
    notes = "## Analisi\n\nPerché è già così: sigma, mu, somma e l'integrale"
    monkeypatch.setattr(ng, "generate_notes", lambda **kwargs: notes)
    pdf_bytes = ng.generate_notes_pdf(student_id=1, exam_id=1, source_name="Analisi 1")
    from pypdf import PdfReader
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)
    assert "Perché è già così" in text


def test_pdf_notes_do_not_substitute_another_source(monkeypatch):
    monkeypatch.setattr(ng, "retrieve_passages", lambda *args, **kwargs: [])
    with pytest.raises(ValueError, match="missing.pdf"):
        ng.generate_notes_pdf_from_materials(
            student_id=1, exam_id=1, materials=[{"filename": "missing.pdf"}]
        )


def test_pdf_notes_report_actual_source_and_part_progress(monkeypatch):
    monkeypatch.setattr(ng, "retrieve_passages", lambda *args, **kwargs: [
        {"text": "La letteratura studia testi, autori, opere e temi presenti nel corso. " * 3,
         "source": "letteratura.pdf", "page": 1}
    ])
    monkeypatch.setattr(ng, "_run_with_retry", lambda *args, **kwargs: "## Tema\nFatto.\n\n## Riepilogo\n- Fatto.")
    monkeypatch.setattr(ng, "_verify_notes_fidelity", lambda notes, *_: notes)
    monkeypatch.setattr(ng, "_make_notes_agent", lambda *_: object())
    events = []
    pdf = ng.generate_notes_pdf_from_materials(
        1, 1, [{"filename": "letteratura.pdf"}], progress=events.append,
    )
    assert pdf.startswith(b"%PDF")
    assert [event["phase"] for event in events] == [
        "reading", "generating", "reviewing", "part_done", "source_done", "pdf",
    ]
    assert events[1]["source"] == "letteratura.pdf"
    assert events[1]["part"] == 1 and events[1]["parts"] == 1
    both_pdf, markdown = ng.generate_notes_pdf_from_materials(
        1, 1, [{"filename": "letteratura.pdf"}], include_markdown=True,
    )
    assert both_pdf.startswith(b"%PDF")
    assert "# Fonte: letteratura.pdf" in markdown
    assert "## Tema\nFatto." in markdown


def test_generate_notes_raises_without_material(monkeypatch):
    monkeypatch.setattr(ng, "retrieve_passages", lambda **kwargs: [])
    try:
        ng.generate_notes(student_id=1, exam_id=1)
        assert False, "doveva sollevare ValueError"
    except ValueError as e:
        assert "Nessun chunk" in str(e)


def test_generate_notes_retries_on_invalid_response(monkeypatch, fake_agent_factory):
    monkeypatch.setattr(ng, "_verify_notes_fidelity", lambda notes, *_: notes)
    monkeypatch.setattr(ng, "retrieve_passages", lambda **kwargs: [
        {"text": "chunk di materiale " * 20, "source": "materiale di studio", "page": 1}
    ])
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
    # _run_with_retry strips the model response before preserving the notes.
    assert notes.startswith(first.strip())
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


def test_agno_rate_limit_output_retries_same_prompt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ng.time, "sleep", sleeps.append)

    class FakeOutput:
        def __init__(self, content, status):
            self.content = content
            self.status = status

        def get_content_as_string(self):
            return self.content

    class FakeAgent:
        def __init__(self):
            self.calls = []

        def run(self, prompt, stream=False):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return FakeOutput('{"error":{"message":"Rate limit reached. Please try again in 2s", "code":"rate_limit_exceeded"}}', "ERROR")
            return FakeOutput(FAKE_VALID_NOTES, "COMPLETED")

    agent = FakeAgent()
    assert ng._run_with_retry(agent, "original prompt") == FAKE_VALID_NOTES.strip()
    assert agent.calls == ["original prompt", "original prompt"]
    assert sleeps == [3.0]


def test_agno_gemini_503_retries_same_prompt(monkeypatch):
    sleeps = []
    monkeypatch.setattr(ng.time, "sleep", sleeps.append)

    class Output:
        def __init__(self, content, status):
            self.content = content
            self.status = status

        def get_content_as_string(self):
            return self.content

    class Agent:
        def __init__(self):
            self.calls = []

        def run(self, prompt, stream=False):
            self.calls.append(prompt)
            if len(self.calls) == 1:
                return Output('{"error":{"code":503,"status":"UNAVAILABLE","message":"high demand"}}', "ERROR")
            return Output(FAKE_VALID_NOTES, "COMPLETED")

    agent = Agent()
    assert ng._run_with_retry(agent, "original prompt") == FAKE_VALID_NOTES.strip()
    assert agent.calls == ["original prompt", "original prompt"]
    assert len(sleeps) == 1


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
