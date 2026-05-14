"""
Quiz Generator Agent — Study Coach
===================================
Responsabilità: dato un exam_id, recupera chunk rilevanti da ChromaDB (RAG)
e genera N domande a risposta aperta calibrate sul materiale dello studente.

Prompt versionato: backend/agents/prompts/quiz_generator_v1.txt
"""

import os
import json
import re
from pathlib import Path
from dataclasses import dataclass, asdict

import google.generativeai as genai
from dotenv import load_dotenv

from ingestor import retrieve_chunks  # aggiusta l'import se cambia la struttura

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPT_VERSION = "quiz_generator_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"

DEFAULT_N_QUESTIONS = 5
DEFAULT_N_CHUNKS = 8          # quanti chunk RAG passare al modello
DEFAULT_MODEL = "gemini-1.5-flash"

# ---------------------------------------------------------------------------
# Dataclasses di output
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: int
    text: str
    difficulty: str           # "base" | "intermedia" | "avanzata"
    topic_hint: str


@dataclass
class QuizResult:
    questions: list[Question]
    source_name: str
    n_questions: int
    prompt_version: str
    exam_id: int
    student_id: int


# ---------------------------------------------------------------------------
# Caricamento prompt versionato
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    """
    Carica il template del prompt dal file .txt versionato.
    Solleva FileNotFoundError se il file non esiste — fail fast e visibile.
    """
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(
            f"Prompt template non trovato: {PROMPT_PATH}\n"
            "Assicurati che il file esista in backend/agents/prompts/"
        )
    return PROMPT_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsing della risposta JSON del modello
# ---------------------------------------------------------------------------

def _parse_llm_response(raw: str) -> dict:
    """
    Estrae e valida il JSON dalla risposta del modello.
    Gestisce il caso in cui il modello avvolga il JSON in ```json ... ```.
    """
    # Rimuovi eventuale blocco markdown ```json ... ```
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Il modello non ha restituito JSON valido.\n"
            f"Errore: {e}\n"
            f"Risposta ricevuta:\n{raw[:500]}"
        ) from e

    # Validazione struttura minima
    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError(
            f"JSON mancante del campo 'questions' o non è una lista.\n"
            f"Campi ricevuti: {list(data.keys())}"
        )

    return data


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def generate_quiz(
    student_id: int,
    exam_id: int,
    topic_query: str = "concetti principali del corso",
    n_questions: int = DEFAULT_N_QUESTIONS,
    n_chunks: int = DEFAULT_N_CHUNKS,
    source_name: str = "materiale di studio",
    model_name: str = DEFAULT_MODEL,
) -> QuizResult:
    """
    Genera N domande a risposta aperta sul materiale indicizzato per exam_id.

    Flusso:
        1. Recupero chunk rilevanti da ChromaDB (RAG)
        2. Caricamento prompt versionato
        3. Compilazione del prompt con chunk + parametri
        4. Chiamata al modello Gemini
        5. Parsing e validazione della risposta JSON
        6. Restituzione di un QuizResult strutturato

    Args:
        student_id:   ID dello studente (usato per isolare la collection ChromaDB)
        exam_id:      ID dell'esame
        topic_query:  Query usata per il retrieval RAG (default: overview generale)
        n_questions:  Numero di domande da generare (default: 5)
        n_chunks:     Numero di chunk RAG da includere nel contesto (default: 8)
        source_name:  Nome del documento/esame da mostrare nel report
        model_name:   Modello Gemini da usare

    Returns:
        QuizResult con lista di Question, metadati e versione del prompt usato
    """

    # --- Step 1: RAG retrieval ---
    chunks = retrieve_chunks(
        query=topic_query,
        student_id=student_id,
        exam_id=exam_id,
        n_results=n_chunks,
    )

    if not chunks:
        raise ValueError(
            f"Nessun chunk trovato per student_id={student_id}, exam_id={exam_id}.\n"
            "Assicurati di aver indicizzato il materiale prima di generare il quiz."
        )

    context_text = "\n\n---\n\n".join(chunks)

    # --- Step 2 & 3: Prompt loading e compilazione ---
    template = _load_prompt_template()

    # Estrai solo la sezione del prompt (dopo il frontmatter "---")
    # Il file .txt ha un header documentativo separato da "---"
    parts = template.split("---\n\n", maxsplit=1)
    prompt_body = parts[-1]  # prende la seconda metà se c'è il separatore

    filled_prompt = prompt_body.format(
        n_questions=n_questions,
        source_name=source_name,
        context_chunks=context_text,
    )

    # --- Step 4: Chiamata LLM ---
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(filled_prompt)

    raw_text = response.text

    # --- Step 5: Parsing ---
    data = _parse_llm_response(raw_text)

    # --- Step 6: Costruzione QuizResult ---
    questions = []
    for q in data["questions"]:
        questions.append(Question(
            id=q.get("id", 0),
            text=q.get("text", ""),
            difficulty=q.get("difficulty", "intermedia"),
            topic_hint=q.get("topic_hint", ""),
        ))

    result = QuizResult(
        questions=questions,
        source_name=data.get("source_name", source_name),
        n_questions=len(questions),
        prompt_version=PROMPT_VERSION,
        exam_id=exam_id,
        student_id=student_id,
    )

    print(
        f"[QuizGenerator] Generato quiz: {result.n_questions} domande | "
        f"exam_id={exam_id} | prompt={PROMPT_VERSION}"
    )

    return result


# ---------------------------------------------------------------------------
# Utilità: serializzazione
# ---------------------------------------------------------------------------

def quiz_to_dict(result: QuizResult) -> dict:
    """Converte QuizResult in dict serializzabile (per JSON / qa_log)."""
    return asdict(result)


def quiz_to_json(result: QuizResult, indent: int = 2) -> str:
    """Serializza QuizResult in stringa JSON."""
    return json.dumps(quiz_to_dict(result), ensure_ascii=False, indent=indent)