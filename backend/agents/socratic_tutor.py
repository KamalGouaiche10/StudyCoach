"""
Socratic Tutor Agent — Study Coach
=====================================
Gestisce il loop di interrogazione socratica per una singola domanda.
"""

import json
import re
import time
from dataclasses import asdict, dataclass
from enum import Enum, auto
from pathlib import Path
from typing import cast

from agno.agent import Agent
from agno.models.groq import Groq
from dotenv import load_dotenv

from backend.agents.ingestor import retrieve_chunks

load_dotenv()

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_GUIDE = "socratic_tutor_guide_v1"
PROMPT_EVAL = "socratic_tutor_eval_v1"
PROMPT_CONTEST = "socratic_tutor_contest_v1"

DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_N_CHUNKS = 5
MAX_RETRIES = 3
RETRY_DELAY = 3


# ---------------------------------------------------------------------------
# Helper per rate limit
# ---------------------------------------------------------------------------

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
        'tokens per day' in lower,
    ])


def _parse_retry_after(raw: str) -> int | None:
    """Estrae il tempo di attesa dal messaggio di errore (in secondi)."""
    # Pattern: 1h18m31.392s
    match = re.search(r'(?:try again in\s*)?(\d+)h(\d+)m(\d+\.?\d*)s', raw, re.IGNORECASE)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2)), float(match.group(3))
        return int(h * 3600 + m * 60 + s)
    # Solo minuti
    match = re.search(r'(\d+)\s*(?:minute|min|m)', raw, re.IGNORECASE)
    if match:
        return int(match.group(1)) * 60
    # Solo secondi
    match = re.search(r'(\d+)\s*(?:second|sec|s)', raw, re.IGNORECASE)
    if match:
        return int(match.group(1))
    # Fallback
    return None


# ---------------------------------------------------------------------------
# Stato del loop
# ---------------------------------------------------------------------------

class TurnState(Enum):
    WAITING_ANSWER_1 = auto()
    WAITING_ANSWER_2 = auto()
    EVALUATED = auto()
    CONTESTED = auto()
    CLOSED = auto()


@dataclass
class EvaluationResult:
    score: int
    motivation: str
    correct_points: list[str]
    missing_points: list[str]
    improvement_after_guidance: str


@dataclass
class ContestationResult:
    final_score: int
    score_changed: bool
    score_delta: int
    contestation_assessment: str
    final_motivation: str
    response_to_student: str


@dataclass
class QuestionAttempt:
    question_id: int
    question_text: str
    difficulty: str
    topic_hint: str

    student_answer_1: str = ""
    guiding_question: str = ""
    positive_feedback: str = ""
    focus_area: str = ""
    student_answer_2: str = ""

    evaluation: EvaluationResult | None = None
    contestation_text: str = ""
    contestation_result: ContestationResult | None = None
    state: TurnState = TurnState.WAITING_ANSWER_1

    @property
    def final_score(self) -> int | None:
        if self.contestation_result is not None:
            return self.contestation_result.final_score
        if self.evaluation is not None:
            return self.evaluation.score
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt(version_name: str) -> str:
    path = PROMPTS_DIR / f"{version_name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt non trovato: {path}")
    raw = path.read_text(encoding="utf-8")
    parts = raw.split("---\n\n", maxsplit=1)
    return parts[-1]


def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"JSON non valido dal modello.\nErrore: {e}\n"
            f"Risposta (500 char):\n{raw[:500]}"
        ) from e


# ---------------------------------------------------------------------------
# Agno agent factories
# ---------------------------------------------------------------------------

def _guide_agent(model_name: str) -> Agent:
    return Agent(
        name="SocraticGuideAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un tutor socratico universitario. "
            "NON dare mai la risposta corretta. "
            "Guida lo studente con domande mirate. "
            "Rispondi SOLO con JSON valido, senza markdown."
        ),
        markdown=False,
    )


def _eval_agent(model_name: str) -> Agent:
    return Agent(
        name="EvaluatorAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un valutatore universitario esperto e obiettivo. "
            "Valuta la preparazione dello studente con un voto 0-10. "
            "Rispondi SOLO con JSON valido, senza markdown."
        ),
        markdown=False,
    )


def _contest_agent(model_name: str) -> Agent:
    return Agent(
        name="ContestationAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un valutatore universitario imparziale. "
            "Riesamina la valutazione con obiettività dopo la contestazione. "
            "Rispondi SOLO con JSON valido, senza markdown."
        ),
        markdown=False,
    )


# ---------------------------------------------------------------------------
# Step LLM con retry e gestione rate limit
# ---------------------------------------------------------------------------

def _generate_guiding_question(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> dict:
    template = _load_prompt(PROMPT_GUIDE)
    prompt = template.format(
        question=attempt.question_text,
        student_answer_1=attempt.student_answer_1,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    agent = _guide_agent(model_name)

    for attempt_num in range(MAX_RETRIES):
        try:
            output = agent.run(prompt, stream=False)
            raw = output.get_content_as_string()

            if _is_rate_limit_error(raw):
                wait = _parse_retry_after(raw)
                if wait and wait > 0:
                    print(f"[SocraticGuideAgent] Rate limit, attendo {wait}s...")
                    time.sleep(min(wait, 60))  # al massimo 60s per non bloccare troppo
                else:
                    time.sleep(RETRY_DELAY)
                continue

            data = _parse_json(raw)
            if "guiding_question" not in data:
                raise ValueError(f"Risposta mancante di 'guiding_question': {data}")
            return data

        except Exception as e:
            print(f"[SocraticGuideAgent] Tentativo {attempt_num+1} fallito: {e}")
            if attempt_num < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"Impossibile generare la domanda guida dopo {MAX_RETRIES} tentativi. "
                    f"Ultimo errore: {e}"
                ) from e

    raise RuntimeError("Tentativi esauriti per la generazione della domanda guida.")


def _evaluate(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> EvaluationResult:
    template = _load_prompt(PROMPT_EVAL)
    prompt = template.format(
        question=attempt.question_text,
        student_answer_1=attempt.student_answer_1,
        guiding_question=attempt.guiding_question,
        student_answer_2=attempt.student_answer_2,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    agent = _eval_agent(model_name)

    for attempt_num in range(MAX_RETRIES):
        try:
            output = agent.run(prompt, stream=False)
            raw = output.get_content_as_string()

            if _is_rate_limit_error(raw):
                wait = _parse_retry_after(raw)
                if wait and wait > 0:
                    print(f"[EvaluatorAgent] Rate limit, attendo {wait}s...")
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(RETRY_DELAY)
                continue

            data = _parse_json(raw)
            score = max(0, min(10, int(data.get("score", 0))))
            return EvaluationResult(
                score=score,
                motivation=data.get("motivation", ""),
                correct_points=data.get("correct_points", []),
                missing_points=data.get("missing_points", []),
                improvement_after_guidance=data.get("improvement_after_guidance", ""),
            )

        except Exception as e:
            print(f"[EvaluatorAgent] Tentativo {attempt_num+1} fallito: {e}")
            if attempt_num < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"Impossibile valutare dopo {MAX_RETRIES} tentativi. "
                    f"Ultimo errore: {e}"
                ) from e

    raise RuntimeError("Tentativi esauriti per la valutazione.")


def _re_evaluate_after_contestation(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> ContestationResult:
    if attempt.evaluation is None:
        raise ValueError("Nessuna valutazione iniziale: impossibile rivalutare.")

    template = _load_prompt(PROMPT_CONTEST)
    prompt = template.format(
        question=attempt.question_text,
        student_answer_1=attempt.student_answer_1,
        guiding_question=attempt.guiding_question,
        student_answer_2=attempt.student_answer_2,
        original_score=attempt.evaluation.score,
        original_motivation=attempt.evaluation.motivation,
        contestation=attempt.contestation_text,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    agent = _contest_agent(model_name)

    for attempt_num in range(MAX_RETRIES):
        try:
            output = agent.run(prompt, stream=False)
            raw = output.get_content_as_string()

            if _is_rate_limit_error(raw):
                wait = _parse_retry_after(raw)
                if wait and wait > 0:
                    print(f"[ContestationAgent] Rate limit, attendo {wait}s...")
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(RETRY_DELAY)
                continue

            data = _parse_json(raw)
            final_score = max(0, min(10, int(data.get("final_score", attempt.evaluation.score))))
            delta = final_score - attempt.evaluation.score

            return ContestationResult(
                final_score=final_score,
                score_changed=delta != 0,
                score_delta=delta,
                contestation_assessment=data.get("contestation_assessment", "non_valido"),
                final_motivation=data.get("final_motivation", ""),
                response_to_student=data.get("response_to_student", ""),
            )

        except Exception as e:
            print(f"[ContestationAgent] Tentativo {attempt_num+1} fallito: {e}")
            if attempt_num < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                raise RuntimeError(
                    f"Impossibile rivalutare dopo {MAX_RETRIES} tentativi. "
                    f"Ultimo errore: {e}"
                ) from e

    raise RuntimeError("Tentativi esauriti per la rivalutazione.")


# ---------------------------------------------------------------------------
# SocraticTutor — classe principale
# ---------------------------------------------------------------------------

class SocraticTutor:
    """
    Gestisce il loop socratico per una singola domanda usando Agno agents.
    """

    def __init__(
        self,
        student_id: int,
        exam_id: int,
        model_name: str = DEFAULT_MODEL,
        n_chunks: int = DEFAULT_N_CHUNKS,
    ):
        self.student_id = student_id
        self.exam_id = exam_id
        self.model_name = model_name
        self.n_chunks = n_chunks
        self.attempt: QuestionAttempt | None = None
        self._context_cache: list[str] = []

    def start(self, question_data: dict) -> str:
        self.attempt = QuestionAttempt(
            question_id=question_data["id"],
            question_text=question_data["text"],
            difficulty=question_data.get("difficulty", "intermedia"),
            topic_hint=question_data.get("topic_hint", ""),
            state=TurnState.WAITING_ANSWER_1,
        )
        self._context_cache = retrieve_chunks(
            query=question_data["text"],
            student_id=self.student_id,
            exam_id=self.exam_id,
            n_results=self.n_chunks,
        )
        return self.attempt.question_text

    def submit_answer_1(self, answer: str) -> dict:
        self._assert_state(TurnState.WAITING_ANSWER_1)
        attempt = cast(QuestionAttempt, self.attempt)
        attempt.student_answer_1 = answer.strip()

        data = _generate_guiding_question(attempt, self._context_cache, self.model_name)
        attempt.guiding_question = data["guiding_question"]
        attempt.positive_feedback = data.get("positive_feedback", "")
        attempt.focus_area = data.get("focus_area", "")
        attempt.state = TurnState.WAITING_ANSWER_2

        print(f"[SocraticGuideAgent] focus={attempt.focus_area} | q_id={attempt.question_id}")
        return {
            "guiding_question": attempt.guiding_question,
            "positive_feedback": attempt.positive_feedback,
            "focus_area": attempt.focus_area,
        }

    def submit_answer_2(self, answer: str) -> dict:
        self._assert_state(TurnState.WAITING_ANSWER_2)
        attempt = cast(QuestionAttempt, self.attempt)
        attempt.student_answer_2 = answer.strip()

        eval_result = _evaluate(attempt, self._context_cache, self.model_name)
        attempt.evaluation = eval_result
        attempt.state = TurnState.EVALUATED

        print(f"[EvaluatorAgent] score={eval_result.score}/10 | q_id={attempt.question_id}")
        return {
            "score": eval_result.score,
            "motivation": eval_result.motivation,
            "correct_points": eval_result.correct_points,
            "missing_points": eval_result.missing_points,
            "improvement_after_guidance": eval_result.improvement_after_guidance,
            "can_contest": True,
        }

    def submit_contestation(self, argumentation: str) -> dict:
        self._assert_state(TurnState.EVALUATED)
        attempt = cast(QuestionAttempt, self.attempt)
        attempt.contestation_text = argumentation.strip()

        contest_result = _re_evaluate_after_contestation(attempt, self._context_cache, self.model_name)
        attempt.contestation_result = contest_result
        attempt.state = TurnState.CONTESTED

        print(
            f"[ContestationAgent] {contest_result.contestation_assessment} | "
            f"{attempt.evaluation.score} → {contest_result.final_score} | q_id={attempt.question_id}"
        )
        return {
            "final_score": contest_result.final_score,
            "score_changed": contest_result.score_changed,
            "score_delta": contest_result.score_delta,
            "contestation_assessment": contest_result.contestation_assessment,
            "final_motivation": contest_result.final_motivation,
            "response_to_student": contest_result.response_to_student,
        }

    def close(self) -> QuestionAttempt:
        if self.attempt is None:
            raise RuntimeError("Tutor non inizializzato.")
        attempt = self.attempt
        if attempt.state not in (TurnState.EVALUATED, TurnState.CONTESTED):
            raise RuntimeError(
                f"Non si può chiudere in stato {attempt.state.name}. "
                "Lo studente deve aver completato almeno due risposte."
            )
        attempt.state = TurnState.CLOSED
        return attempt

    def to_dict(self) -> dict:
        if self.attempt is None:
            return {}
        d = asdict(self.attempt)
        d["state"] = self.attempt.state.name
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def _assert_state(self, expected: TurnState) -> None:
        if self.attempt is None:
            raise RuntimeError("Tutor non inizializzato. Chiama start() prima.")
        if self.attempt.state != expected:
            raise RuntimeError(
                f"Stato '{self.attempt.state.name}' non valido. "
                f"Atteso: '{expected.name}'."
            )