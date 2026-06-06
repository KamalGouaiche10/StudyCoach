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

from agno.agent import Agent
from agno.models.groq import Groq
from dotenv import load_dotenv

from backend.agents.ingestor import retrieve_chunks

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