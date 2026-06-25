"""
Notes Generator Agent — Study Coach
=====================================
Responsabilità: generare appunti sintetici a partire da:
  1. Il materiale RAG indicizzato (chunks ChromaDB) — per la generazione
     "a freddo" prima di una sessione.
  2. Il qa_log di una sessione completata — per raffinare gli appunti
     focalizzandosi sulle aree deboli emerse durante l'interrogazione.

Modalità di utilizzo:
  - generate_notes(student_id, exam_id, topic_query)
      → appunti dal materiale grezzo (pre-sessione)
  - generate_notes_from_log(attempts)
      → appunti post-sessione, personalizzati sulle lacune rilevate

Agente: Agno + Groq (llama-3.3-70b-versatile)
Prompt versionato: backend/agents/prompts/notes_generator_v1.txt
"""

from __future__ import annotations

from pathlib import Path
import textwrap
import unicodedata
import re

from agno.agent import Agent
from agno.models.groq import Groq
from dotenv import load_dotenv

from backend.agents.ingestor import retrieve_chunks, retrieve_chunks_by_source

load_dotenv()

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPT_VERSION  = "notes_generator_v1"
PROMPT_PATH     = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
DEFAULT_MODEL   = "llama-3.3-70b-versatile"
DEFAULT_N_CHUNKS = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Prompt template non trovato: {PROMPT_PATH}\n"
            "Assicurati che il file esista in backend/agents/prompts/"
        )
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    parts = raw.split("---\n\n", maxsplit=1)
    return parts[-1]


def _make_notes_agent(model_name: str) -> Agent:
    return Agent(
        name="NotesGeneratorAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un tutor universitario esperto. "
            "Crei appunti sintetici chiari, strutturati e utili per lo studio. "
            "Usi titoli, elenchi puntati e grassetto per organizzare i concetti. "
            "Rispondi SOLO con il testo degli appunti, senza introduzioni né commenti."
        ),
        markdown=True,
    )


def _build_log_summary(attempts: list[dict]) -> str:
    """
    Estrae dal qa_log un riassunto delle domande, risposte e lacune
    per contestualizzare la generazione degli appunti.
    """
    lines = []
    for i, a in enumerate(attempts, 1):
        q_text  = a.get("question_text", "")
        topic   = a.get("topic_hint", "")
        score   = a.get("final_score", "—")
        ans2    = a.get("student_answer_2", "")
        missing = []
        evaluation = a.get("evaluation", {})
        if isinstance(evaluation, dict):
            missing = evaluation.get("missing_points", [])

        lines.append(f"Domanda {i} [{topic}] (voto: {score}/10):")
        lines.append(f"  Testo: {q_text}")
        if ans2:
            lines.append(f"  Risposta studente: {ans2[:300]}{'...' if len(ans2) > 300 else ''}")
        if missing:
            lines.append(f"  Lacune rilevate: {'; '.join(missing)}")
        lines.append("")
    return "\n".join(lines)


def _extract_weak_topics(attempts: list[dict]) -> list[str]:
    """Raccoglie i topic con score < 6 dal qa_log."""
    weak = []
    for a in attempts:
        score = a.get("final_score")
        topic = a.get("topic_hint", "")
        if isinstance(score, (int, float)) and score < 6 and topic:
            weak.append(topic)
    return list(dict.fromkeys(weak))  # deduplica mantenendo ordine


def _pdf_safe_text(value: object) -> str:
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    replacements = {
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        "–": "-",
        "—": "-",
        "…": "...",
        "•": "-",
        "→": "->",
        "←": "<-",
        "✓": "OK",
        "✅": "OK",
        "⚠": "!",
        "📘": "",
        "📄": "",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    return text.encode("latin-1", "replace").decode("latin-1")


def _sentence_candidates(text: str) -> list[str]:
    text = _pdf_safe_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []

    parts = re.split(r"(?<=[.!?])\s+", text)
    candidates: list[str] = []
    for part in parts:
        cleaned = part.strip(" -•\t")
        if len(cleaned) < 35:
            continue
        letters = sum(ch.isalpha() for ch in cleaned)
        if letters < 20:
            continue
        if cleaned.count("\ufffd") > 0:
            continue
        # Se il testo è troppo rumoroso (simboli/bytes strani), lo scartiamo.
        non_alnum = sum(not ch.isalnum() and not ch.isspace() for ch in cleaned)
        if non_alnum > max(12, len(cleaned) // 3):
            continue
        candidates.append(cleaned)
    return candidates


def _build_local_notes_from_chunks(chunks: list[str], max_bullets: int = 6) -> list[str]:
    seen: set[str] = set()
    bullets: list[str] = []
    for chunk in chunks:
        for sentence in _sentence_candidates(chunk):
            normalized = sentence.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            bullets.append(sentence)
            if len(bullets) >= max_bullets:
                return bullets
    return bullets


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def generate_notes(
    student_id: int,
    exam_id: int,
    topic_query: str = "concetti principali del corso",
    n_chunks: int = DEFAULT_N_CHUNKS,
    source_name: str = "materiale di studio",
    model_name: str = DEFAULT_MODEL,
) -> str:
    """
    Genera appunti sintetici dal materiale RAG indicizzato.
    Usa questa funzione PRIMA di una sessione o su richiesta esplicita.

    Args:
        student_id:  ID studente
        exam_id:     ID esame
        topic_query: Query per il retrieval RAG (default: concetti principali)
        n_chunks:    Numero di chunk da recuperare
        source_name: Nome sorgente (visualizzato negli appunti)
        model_name:  Modello Groq da usare

    Returns:
        Stringa Markdown con gli appunti sintetici.
    """
    chunks = retrieve_chunks(
        query=topic_query,
        student_id=student_id,
        exam_id=exam_id,
        n_results=n_chunks,
    )
    if not chunks:
        raise ValueError(
            f"Nessun chunk trovato per student_id={student_id}, exam_id={exam_id}.\n"
            "Indicizza il materiale prima di generare gli appunti."
        )

    context_text = "\n\n---\n\n".join(chunks)
    template     = _load_prompt_template()
    prompt       = template.format(
        mode="materiale",
        source_name=source_name,
        context=context_text,
        log_summary="",
        weak_topics="",
    )

    agent  = _make_notes_agent(model_name)
    output = agent.run(prompt, stream=False)
    notes  = output.get_content_as_string().strip()

    print(
        f"[NotesGeneratorAgent] Appunti generati da materiale RAG | "
        f"exam_id={exam_id} | chunks={len(chunks)} | model={model_name}"
    )
    return notes


def generate_notes_pdf(
    student_id: int,
    exam_id: int,
    topic_query: str = "concetti principali del corso",
    min_pages: int = 1,
    n_chunks: int = DEFAULT_N_CHUNKS,
    source_name: str = "materiale di studio",
    model_name: str = DEFAULT_MODEL,
) -> bytes:
    """Genera gli appunti (markdown) e li converte in PDF.
    Garantisce che il PDF abbia almeno `min_pages` pagine (aggiunge pagine vuote se necessario).

    Ritorna i bytes del PDF.
    """
    notes_md = generate_notes(
        student_id=student_id,
        exam_id=exam_id,
        topic_query=topic_query,
        n_chunks=n_chunks,
        source_name=source_name,
        model_name=model_name,
    )

    # Creazione PDF semplice e robusta a partire dal markdown testuale.
    try:
        from fpdf import FPDF
    except Exception as e:
        raise RuntimeError(f"FPDF non disponibile: {e}")

    class _NotesPDF(FPDF):
        def __init__(self):
            super().__init__(orientation="P", unit="mm", format="A4")

        def header(self):
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(30, 30, 30)
            self.cell(0, 8, _pdf_safe_text(f"Appunti - {source_name}"))
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

    pdf = _NotesPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(40, 40, 40)

    def _write_wrapped(text: str, font_style: str = "", font_size: int = 11) -> None:
        pdf.set_font("Helvetica", font_style, font_size)
        for paragraph in _pdf_safe_text(text).splitlines() or [""]:
            clean = paragraph.strip()
            if not clean:
                pdf.ln(4)
                continue
            for chunk in textwrap.wrap(clean, width=60, break_long_words=True, break_on_hyphens=True) or [clean]:
                pdf.multi_cell(0, 6, chunk)
        pdf.ln(1)

    for line in notes_md.splitlines():
        if line.startswith("#"):
            level = len(line.split(" ", 1)[0])
            title = _pdf_safe_text(line.lstrip("#").strip())
            size = 14 if level <= 2 else 12
            _write_wrapped(title, "B", size)
        else:
            normalized = _pdf_safe_text(line.strip().lstrip("-* ").strip())
            _write_wrapped(normalized, "", 11)

    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    raise TypeError(f"Tipo output PDF non supportato: {type(out).__name__}")


def generate_notes_pdf_from_materials(
    student_id: int,
    exam_id: int,
    materials: list[dict],
    model_name: str = DEFAULT_MODEL,
) -> bytes:
    """Genera un PDF con una pagina per ogni fonte caricata."""
    try:
        from fpdf import FPDF
    except Exception as e:
        raise RuntimeError(f"FPDF non disponibile: {e}")

    class _NotesPDF(FPDF):
        def __init__(self):
            super().__init__(orientation="P", unit="mm", format="A4")

        def header(self):
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(30, 30, 30)
            self.cell(0, 8, _pdf_safe_text("Study Coach - Appunti"))
            self.ln(6)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 10, f"Pagina {self.page_no()}", align="C")

    def _render_wrapped(pdf: FPDF, text: str, style: str = "", size: int = 11) -> None:
        pdf.set_font("Helvetica", style, size)
        for paragraph in _pdf_safe_text(text).splitlines() or [""]:
            clean = paragraph.strip()
            if not clean:
                pdf.ln(4)
                continue
            for chunk in textwrap.wrap(clean, width=60, break_long_words=True, break_on_hyphens=True) or [clean]:
                pdf.multi_cell(0, 6, chunk)
        pdf.ln(1)

    pdf = _NotesPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)

    if not materials:
        materials = [{"filename": "materiale di studio", "pages_count": 1}]

    for material in materials:
        filename = getattr(material, "filename", None) or material.get("filename", "materiale di studio")
        pages_count = getattr(material, "pages_count", None) or material.get("pages_count", 1)
        pdf.add_page()
        pdf.set_text_color(40, 40, 40)
        _render_wrapped(pdf, _pdf_safe_text(filename), "B", 14)
        _render_wrapped(pdf, _pdf_safe_text(f"Pagine originali: {pages_count}"), "", 9)

        chunks = retrieve_chunks_by_source(student_id, exam_id, filename, limit=12)
        bullets = _build_local_notes_from_chunks(chunks)

        if not bullets:
            _render_wrapped(pdf, "Nessun testo estraibile da questa fonte.", "", 11)
            continue

        _render_wrapped(pdf, "Punti chiave", "B", 12)
        for bullet in bullets:
            _render_wrapped(pdf, f"- {bullet}", "", 11)

        if len(bullets) < 3:
            _render_wrapped(pdf, "Nota: questa fonte contiene poco testo pulito o e' prevalentemente OCR.", "", 10)

    out = pdf.output()
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    if isinstance(out, str):
        return out.encode("latin-1", "replace")
    raise TypeError(f"Tipo output PDF non supportato: {type(out).__name__}")


def generate_notes_from_log(
    attempts: list[dict],
    student_id: int | None = None,
    exam_id: int | None = None,
    source_name: str = "sessione di studio",
    model_name: str = DEFAULT_MODEL,
    enrich_with_rag: bool = False,
) -> str:
    """
    Genera appunti sintetici post-sessione personalizzati sulle lacune
    emerse durante l'interrogazione socratica.

    Args:
        attempts:        Lista di dict dal qa_log (formato piatto di session.py)
        student_id:      Opzionale — se fornito con exam_id, arricchisce col RAG
        exam_id:         Opzionale — vedi sopra
        source_name:     Nome sorgente per l'intestazione
        model_name:      Modello Groq
        enrich_with_rag: Se True e student_id/exam_id disponibili, aggiunge
                         chunk RAG sui topic deboli

    Returns:
        Stringa Markdown con gli appunti focalizzati sulle lacune.
    """
    if not attempts:
        raise ValueError("Lista attempts vuota: impossibile generare appunti.")

    log_summary  = _build_log_summary(attempts)
    weak_topics  = _extract_weak_topics(attempts)
    weak_str     = ", ".join(weak_topics) if weak_topics else "nessuna lacuna rilevata"

    # Arricchimento RAG opzionale sui topic deboli
    rag_context = ""
    if enrich_with_rag and student_id and exam_id and weak_topics:
        query = " ".join(weak_topics[:3])
        try:
            chunks      = retrieve_chunks(query, student_id, exam_id, n_results=6)
            rag_context = "\n\n---\n\n".join(chunks)
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"[NotesGeneratorAgent] RAG enrichment fallito: {e}")

    template = _load_prompt_template()
    prompt   = template.format(
        mode="sessione",
        source_name=source_name,
        context=rag_context if rag_context else "(nessun contesto RAG aggiuntivo)",
        log_summary=log_summary,
        weak_topics=weak_str,
    )

    agent  = _make_notes_agent(model_name)
    output = agent.run(prompt, stream=False)
    notes  = output.get_content_as_string().strip()

    print(
        f"[NotesGeneratorAgent] Appunti post-sessione | "
        f"domande={len(attempts)} | topic_deboli={weak_topics} | model={model_name}"
    )
    return notes