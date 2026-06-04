"""
Quiz Generator Agent — Study Coach
=====================================
Usa Agno + Groq (llama-3.3-70b-versatile) per generare N domande
A risposta aperta basate sul materiale RAG dello studente.

Prompt versionato: backend/agents/prompts/quiz_generator_v1.txt
"""

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from agno.agent import Agent
from agno.models.groq import Groq
from dotenv import load_dotenv

from backend.agents.ingestor import retrieve_chunks

load_dotenv()

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPT_VERSION    = "quiz_generator_v1"
PROMPT_PATH       = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
DEFAULT_N_QUESTIONS = 5
DEFAULT_N_CHUNKS    = 8
DEFAULT_MODEL       = "llama-3.3-70b-versatile"   # Groq


# ---------------------------------------------------------------------------
# Dataclasses di output (invariati — compatibili con il resto del progetto)
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: int
    text: str
    difficulty: str    # "base" | "intermedia" | "avanzata"
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


def _parse_llm_response(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Il modello non ha restituito JSON valido.\nErrore: {e}\n"
            f"Risposta ricevuta:\n{raw[:500]}"
        ) from e
    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError(
            f"JSON mancante del campo 'questions'.\nCampi: {list(data.keys())}"
        )
    return data


# ---------------------------------------------------------------------------
# Agno agent factory
# ---------------------------------------------------------------------------

def _make_quiz_agent(model_name: str) -> Agent:
    """
    Crea un Agent Agno con Groq come backend LLM.
    Il system prompt definisce il ruolo del docente universitario.
    """
    return Agent(
        name="QuizGeneratorAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un docente universitario esperto. "
            "Generi domande di esame a risposta aperta basandoti "
            "ESCLUSIVAMENTE sul materiale fornito. "
            "Rispondi SOLO con JSON valido, senza markdown."
        ),
        markdown=False,

    )


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
    Genera N domande a risposta aperta sul materiale indicizzato.

    Flusso:
        1. RAG retrieval da ChromaDB
        2. Caricamento prompt versionato
        3. Chiamata Agno Agent (Groq)
        4. Parsing JSON + validazione
        5. Restituzione QuizResult strutturato
    """
    # 1. RAG
    chunks = retrieve_chunks(
        query=topic_query,
        student_id=student_id,
        exam_id=exam_id,
        n_results=n_chunks,
    )
    if not chunks:
        raise ValueError(
            f"Nessun chunk trovato per student_id={student_id}, exam_id={exam_id}.\n"
            "Indicizza il materiale prima di generare il quiz."
        )

    context_text = "\n\n---\n\n".join(chunks)

    # 2. Prompt
    template = _load_prompt_template()
    filled_prompt = template.format(
        n_questions=n_questions,
        source_name=source_name,
        context_chunks=context_text,
    )

    # 3. Agno Agent call
    agent = _make_quiz_agent(model_name)
    run_output = agent.run(filled_prompt, stream=False)
    raw_text = run_output.get_content_as_string()

    # 4. Parsing
    data = _parse_llm_response(raw_text)

    # 5. Build result
    questions = [
        Question(
            id=q.get("id", i + 1),
            text=q.get("text", ""),
            difficulty=q.get("difficulty", "intermedia"),
            topic_hint=q.get("topic_hint", ""),
        )
        for i, q in enumerate(data["questions"])
    ]

    result = QuizResult(
        questions=questions,
        source_name=data.get("source_name", source_name),
        n_questions=len(questions),
        prompt_version=PROMPT_VERSION,
        exam_id=exam_id,
        student_id=student_id,
    )

    print(
        f"[QuizGeneratorAgent] {result.n_questions} domande | "
        f"exam_id={exam_id} | model={model_name} | prompt={PROMPT_VERSION}"
    )
    return result


# ---------------------------------------------------------------------------
# Utilità
# ---------------------------------------------------------------------------

def quiz_to_dict(result: QuizResult) -> dict:
    return asdict(result)


def quiz_to_json(result: QuizResult, indent: int = 2) -> str:
    return json.dumps(quiz_to_dict(result), ensure_ascii=False, indent=indent)