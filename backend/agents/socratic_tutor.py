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
from backend.agents.groq_config import GROQ_MODEL, safe_groq_error

load_dotenv()

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent / "prompts"
PROMPT_GUIDE = "socratic_tutor_guide_v1"
PROMPT_EVAL = "socratic_tutor_eval_v1"
PROMPT_CONTEST = "socratic_tutor_contest_v1"
PROMPT_DOUBT_OPEN = "socratic_tutor_doubt_open_v1"
PROMPT_DOUBT_EVAL = "socratic_tutor_doubt_eval_v1"

DEFAULT_MODEL = GROQ_MODEL
DEFAULT_N_CHUNKS = 5
RETRY_DELAY = 3

NON_ANSWER_PATTERNS = (
    r"\bnon\s+so\b",
    r"\bnon\s+lo\s+so\b",
    r"\bnon\s+saprei\b",
    r"\bboh\b",
    r"\bnon\s+ricordo\b",
    r"\bnon\s+ne\s+ho\s+idea\b",
    r"\bnessuna\s+idea\b",
    r"\bidk\b",
    r"\bi\s+don'?t\s+know\b",
)


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


class DoubtState(Enum):
    WAITING_ANSWER = auto()
    ANSWERED = auto()


@dataclass
class DoubtEvaluationResult:
    correct_points: list[str]
    missing_points: list[str]
    correct_answer: str


@dataclass
class DoubtAttempt:
    doubt_text: str
    guiding_question: str = ""
    topic_hint: str = ""
    student_answer: str = ""
    evaluation: DoubtEvaluationResult | None = None
    state: DoubtState = DoubtState.WAITING_ANSWER


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


def _is_non_answer(text: str) -> bool:
    normalized = " ".join(text.lower().strip().split())
    if not normalized:
        return True
    return any(re.search(pattern, normalized) for pattern in NON_ANSWER_PATTERNS)


def _apply_severity_guardrails(attempt: QuestionAttempt, evaluation: EvaluationResult) -> EvaluationResult:
    if not _is_non_answer(attempt.student_answer_2):
        return evaluation

    missing_points = list(evaluation.missing_points)
    strict_missing = "Risposta finale non valutabile: assenza di contenuto disciplinare verificabile."
    if strict_missing not in missing_points:
        missing_points.append(strict_missing)

    strict_motivation = (
        "Valutazione severa applicata: la seconda risposta e' una non-risposta "
        "(es. 'non so') e non dimostra comprensione del contenuto."
    )
    if evaluation.motivation:
        strict_motivation = f"{strict_motivation} {evaluation.motivation}"

    return EvaluationResult(
        score=0,
        motivation=strict_motivation,
        correct_points=evaluation.correct_points,
        missing_points=missing_points,
        improvement_after_guidance=evaluation.improvement_after_guidance,
    )


# Frasi con cui il valutatore dichiara esplicitamente l'assenza di lacune,
# pur non lasciando "missing_points" tecnicamente vuoto (es. una singola
# voce come "nessun punto significativo mancante").
NO_GAPS_PATTERNS = (
    r"nessun\s+punto\s+(significativo\s+)?mancante",
    r"nessuna\s+lacuna",
    r"non\s+ci\s+sono\s+lacune",
    r"tutti\s+i\s+punti\s+(chiave\s+)?(sono\s+)?(corretti|presenti|coperti)",
    r"nessun\s+elemento\s+mancante",
)


def _has_no_real_gaps(missing_points: list[str]) -> bool:
    """
    True se la lista "missing_points" non descrive alcuna lacuna reale:
    o è vuota, o contiene solo frasi che dichiarano esplicitamente
    l'assenza di lacune.
    """
    if not missing_points:
        return True
    for point in missing_points:
        normalized = " ".join(str(point).lower().strip().split())
        if not normalized:
            continue
        if not any(re.search(pattern, normalized) for pattern in NO_GAPS_PATTERNS):
            return False
    return True


def _apply_consistency_guardrails(evaluation: EvaluationResult) -> EvaluationResult:
    """
    Garantisce coerenza tra punteggio e lacune segnalate: se il valutatore
    non ha indicato alcuna lacuna disciplinare reale, il punteggio non può
    restare in una fascia "insufficiente/sufficiente" (es. 6-7). Questo
    corregge deterministicamente il caso in cui l'LLM elenca tutti i punti
    come corretti e nessun punto mancante, ma assegna comunque un voto
    parziale in modo incoerente.
    """
    if evaluation.score >= 9:
        return evaluation
    if not _has_no_real_gaps(evaluation.missing_points):
        return evaluation

    note = (
        "Punteggio corretto automaticamente a 9/10 per coerenza: la valutazione "
        "non ha segnalato alcuna lacuna disciplinare significativa."
    )
    motivation = f"{evaluation.motivation} {note}" if evaluation.motivation else note

    return EvaluationResult(
        score=9,
        motivation=motivation,
        correct_points=evaluation.correct_points,
        missing_points=evaluation.missing_points,
        improvement_after_guidance=evaluation.improvement_after_guidance,
    )


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


def _doubt_agent(model_name: str) -> Agent:
    return Agent(
        name="DoubtTutorAgent",
        model=Groq(id=model_name),
        description=(
            "Sei un tutor socratico universitario. Aiuti lo studente a chiarire "
            "un proprio dubbio guidandolo con domande mirate, senza mai rivelare "
            "subito la risposta. Rispondi SOLO con JSON valido, senza markdown."
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

    attempt_num = 0
    while True:
        attempt_num += 1
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
            print(f"[SocraticGuideAgent] Tentativo {attempt_num} fallito ({safe_groq_error(e)}). Ritento...")
            time.sleep(RETRY_DELAY)
            continue


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

    attempt_num = 0
    while True:
        attempt_num += 1
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
            evaluation = EvaluationResult(
                score=score,
                motivation=data.get("motivation", ""),
                correct_points=data.get("correct_points", []),
                missing_points=data.get("missing_points", []),
                improvement_after_guidance=data.get("improvement_after_guidance", ""),
            )
            evaluation = _apply_severity_guardrails(attempt, evaluation)
            evaluation = _apply_consistency_guardrails(evaluation)
            return evaluation

        except Exception as e:
            print(f"[EvaluatorAgent] Tentativo {attempt_num} fallito ({safe_groq_error(e)}). Ritento...")
            time.sleep(RETRY_DELAY)
            continue


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

    attempt_num = 0
    while True:
        attempt_num += 1
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
            if _is_non_answer(attempt.student_answer_2):
                final_score = 0
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
            print(f"[ContestationAgent] Tentativo {attempt_num} fallito ({safe_groq_error(e)}). Ritento...")
            time.sleep(RETRY_DELAY)
            continue


# ---------------------------------------------------------------------------
# Step LLM — flusso "dubbio libero" (chatbot avviato dallo studente)
# ---------------------------------------------------------------------------

def _generate_opening_question(
    doubt_text: str,
    context_chunks: list[str],
    model_name: str,
) -> dict:
    template = _load_prompt(PROMPT_DOUBT_OPEN)
    prompt = template.format(
        doubt_text=doubt_text,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    agent = _doubt_agent(model_name)

    attempt_num = 0
    while True:
        attempt_num += 1
        try:
            output = agent.run(prompt, stream=False)
            raw = output.get_content_as_string()

            if _is_rate_limit_error(raw):
                wait = _parse_retry_after(raw)
                if wait and wait > 0:
                    print(f"[DoubtTutorAgent] Rate limit, attendo {wait}s...")
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(RETRY_DELAY)
                continue

            data = _parse_json(raw)
            if "guiding_question" not in data:
                raise ValueError(f"Risposta mancante di 'guiding_question': {data}")
            return data

        except Exception as e:
            print(f"[DoubtTutorAgent] Tentativo {attempt_num} fallito ({safe_groq_error(e)}). Ritento...")
            time.sleep(RETRY_DELAY)
            continue


def _evaluate_doubt(
    attempt: "DoubtAttempt",
    context_chunks: list[str],
    model_name: str,
) -> DoubtEvaluationResult:
    template = _load_prompt(PROMPT_DOUBT_EVAL)
    prompt = template.format(
        doubt_text=attempt.doubt_text,
        guiding_question=attempt.guiding_question,
        student_answer=attempt.student_answer,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    agent = _doubt_agent(model_name)

    attempt_num = 0
    while True:
        attempt_num += 1
        try:
            output = agent.run(prompt, stream=False)
            raw = output.get_content_as_string()

            if _is_rate_limit_error(raw):
                wait = _parse_retry_after(raw)
                if wait and wait > 0:
                    print(f"[DoubtTutorAgent] Rate limit, attendo {wait}s...")
                    time.sleep(min(wait, 60))
                else:
                    time.sleep(RETRY_DELAY)
                continue

            data = _parse_json(raw)
            if "correct_answer" not in data:
                raise ValueError(f"Risposta mancante di 'correct_answer': {data}")
            return DoubtEvaluationResult(
                correct_points=data.get("correct_points", []),
                missing_points=data.get("missing_points", []),
                correct_answer=data["correct_answer"],
            )

        except Exception as e:
            print(f"[DoubtTutorAgent] Tentativo {attempt_num} fallito ({safe_groq_error(e)}). Ritento...")
            time.sleep(RETRY_DELAY)
            continue


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


# ---------------------------------------------------------------------------
# DoubtTutor — chatbot per dubbi liberi dello studente
# ---------------------------------------------------------------------------

class DoubtTutor:
    """
    Gestisce il loop socratico avviato da un dubbio libero dello studente:
    lo studente scrive un dubbio -> il tutor risponde con una domanda guida
    socratica (senza svelare la risposta) -> lo studente risponde -> il tutor
    mostra dove ha sbagliato e fornisce la risposta corretta e migliorata,
    basandosi sui chunk RAG del materiale caricato per l'esame.
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
        self.attempt: DoubtAttempt | None = None
        self._context_cache: list[str] = []

    def start(self, doubt_text: str) -> dict:
        doubt_text = doubt_text.strip()
        self._context_cache = retrieve_chunks(
            query=doubt_text,
            student_id=self.student_id,
            exam_id=self.exam_id,
            n_results=self.n_chunks,
        )
        if not self._context_cache:
            raise ValueError(
                "Non ho trovato materiale caricato pertinente a questo dubbio. "
                "Carica un PDF sull'argomento o riformula la domanda."
            )

        data = _generate_opening_question(doubt_text, self._context_cache, self.model_name)
        self.attempt = DoubtAttempt(
            doubt_text=doubt_text,
            guiding_question=data["guiding_question"],
            topic_hint=data.get("topic_hint", ""),
        )
        return {
            "guiding_question": self.attempt.guiding_question,
            "topic_hint": self.attempt.topic_hint,
        }

    def submit_answer(self, answer: str) -> dict:
        self._assert_state(DoubtState.WAITING_ANSWER)
        attempt = cast(DoubtAttempt, self.attempt)
        attempt.student_answer = answer.strip()

        eval_result = _evaluate_doubt(attempt, self._context_cache, self.model_name)
        attempt.evaluation = eval_result
        attempt.state = DoubtState.ANSWERED

        print(f"[DoubtTutorAgent] valutato dubbio '{attempt.topic_hint}'")
        return {
            "correct_points": eval_result.correct_points,
            "missing_points": eval_result.missing_points,
            "correct_answer": eval_result.correct_answer,
        }

    def to_dict(self) -> dict:
        if self.attempt is None:
            return {}
        d = asdict(self.attempt)
        d["state"] = self.attempt.state.name
        return d

    def _assert_state(self, expected: DoubtState) -> None:
        if self.attempt is None:
            raise RuntimeError("Tutor non inizializzato. Chiama start() prima.")
        if self.attempt.state != expected:
            raise RuntimeError(
                f"Stato '{self.attempt.state.name}' non valido. "
                f"Atteso: '{expected.name}'."
            )
