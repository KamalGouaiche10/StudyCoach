
import json
import re
import time
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

PROMPT_VERSION = "quiz_generator_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
DEFAULT_N_QUESTIONS = 5
DEFAULT_N_CHUNKS = 8
DEFAULT_MODEL = "llama-3.3-70b-versatile"
RETRY_DELAY = 3


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: int
    text: str
    difficulty: str  # "base" | "intermedia" | "avanzata"
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
    return parts[-1] if len(parts) > 1 else raw


def _parse_llm_response(raw: str) -> dict:
    """
    Parser robusto che gestisce markdown, backtick, testo extra e JSON malformato.
    """
    if not raw or not raw.strip():
        raise ValueError("Risposta vuota dal modello.")

    # 1. Rimuovi backtick e markdown
    cleaned = re.sub(r"```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"```\s*$", "", cleaned.strip())

    # 2. Se c'è testo prima del JSON, rimuovilo
    first_brace = cleaned.find('{')
    if first_brace > 0:
        cleaned = cleaned[first_brace:]

    # 3. Se c'è testo dopo il JSON, rimuovilo
    last_brace = cleaned.rfind('}')
    if last_brace > 0 and last_brace < len(cleaned) - 1:
        cleaned = cleaned[:last_brace + 1]

    # 4. Prova a parsare
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 5. Se fallisce, prova a riparare il JSON
        # Rimuovi virgole finali negli array/oggetti
        cleaned = re.sub(r',\s*}', '}', cleaned)
        cleaned = re.sub(r',\s*]', ']', cleaned)
        # Sostituisci virgolette singole con doppie per le chiavi
        cleaned = re.sub(r"(\w+):", r'"\1":', cleaned)
        # Correggi virgolette singole per i valori
        cleaned = re.sub(r':\s*\'([^\']*)\'', r': "\1"', cleaned)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e2:
            raise ValueError(
                f"JSON non valido dopo tentativi di riparazione.\n"
                f"Errore originale: {e}\n"
                f"Errore riparazione: {e2}\n"
                f"Risposta ricevuta (primi 500 caratteri):\n{raw[:500]}"
            ) from e2

    # 6. Validazione
    if "questions" not in data or not isinstance(data["questions"], list):
        raise ValueError(
            f"Campo 'questions' mancante o non è una lista.\n"
            f"Campi ricevuti: {list(data.keys())}\n"
            f"JSON: {json.dumps(data, indent=2)[:500]}"
        )

    return data


def _make_quiz_agent(model_name: str) -> Agent:
    """Crea un Agent Agno con Groq come backend LLM."""
    return Agent(
        name="QuizGeneratorAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un docente universitario esperto. "
            "Generi domande di esame a risposta aperta basandoti "
            "ESCLUSIVAMENTE sul materiale fornito. "
            "Rispondi SOLO con JSON valido, senza markdown, senza testo extra."
        ),
        markdown=False,
    )


def _is_rate_limit_error(raw: str) -> bool:
    """Verifica se la risposta contiene un errore di rate limit."""
    if not raw:
        return False
    lower = raw.lower()
    return any([
        'rate limit' in lower,
        'rate_limit_exceeded' in lower,
        'try again in' in lower,
        '429' in raw,
    ])


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
    Genera N domande a risposta aperta sul materiale indicizzato usando
    esclusivamente l'agente Agno. Nessun fallback: in caso di errore o
    risposta non valida si ritenta indefinitamente finché non si ottiene
    un quiz corretto.
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
    template = _load_prompt_template()

    # 2. Tentativi con retry infinito: nessun fallback, si continua a
    #    interrogare l'agente Agno finché non produce un quiz valido.
    #    Anche la formattazione del prompt è dentro il loop: qualunque
    #    errore (template malformato, dati mancanti, ecc.) viene ritentato
    #    invece di propagarsi subito al chiamante.
    attempt = 0
    while True:
        attempt += 1
        try:
            print(f"[QuizGenerator] Tentativo {attempt}...")

            filled_prompt = template.format(
                n_questions=n_questions,
                source_name=source_name,
                context_chunks=context_text,
            )

            agent = _make_quiz_agent(model_name)
            run_output = agent.run(filled_prompt, stream=False)
            raw_text = run_output.get_content_as_string()

            # Controlla errori di rate limit
            if _is_rate_limit_error(raw_text):
                print(f"[QuizGenerator] Rate limit rilevato, attendo {RETRY_DELAY * 2}s...")
                time.sleep(RETRY_DELAY * 2)
                continue

            # Parsing JSON
            try:
                data = _parse_llm_response(raw_text)
            except ValueError as e:
                print(f"[QuizGenerator] Parsing fallito (tentativo {attempt}): {e}. Ritento...")
                time.sleep(RETRY_DELAY)
                continue

            # Costruzione risultati
            questions = []
            for i, q in enumerate(data.get("questions", [])[:n_questions]):
                if not q.get("text"):
                    continue
                questions.append(Question(
                    id=q.get("id", i + 1),
                    text=q.get("text", f"Domanda {i + 1}"),
                    difficulty=q.get("difficulty", "intermedia"),
                    topic_hint=q.get("topic_hint", "Generale"),
                ))

            if len(questions) < n_questions:
                print(
                    f"[QuizGenerator] Generate solo {len(questions)}/{n_questions} "
                    "domande valide, ritento la generazione completa..."
                )
                time.sleep(RETRY_DELAY)
                continue

            result = QuizResult(
                questions=questions[:n_questions],
                source_name=data.get("source_name", source_name),
                n_questions=len(questions[:n_questions]),
                prompt_version=PROMPT_VERSION,
                exam_id=exam_id,
                student_id=student_id,
            )

            print(f"[QuizGenerator] ✅ {result.n_questions} domande generate con successo (tentativo {attempt})")
            return result

        except Exception as e:
            print(f"[QuizGenerator] Tentativo {attempt} fallito con errore: {e}. Ritento...")
            time.sleep(RETRY_DELAY)
            continue


# ---------------------------------------------------------------------------
# Utilità
# ---------------------------------------------------------------------------

def quiz_to_dict(result: QuizResult) -> dict:
    return asdict(result)


def quiz_to_json(result: QuizResult, indent: int = 2) -> str:
    return json.dumps(quiz_to_dict(result), ensure_ascii=False, indent=indent)