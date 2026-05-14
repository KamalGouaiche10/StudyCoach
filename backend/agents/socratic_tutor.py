"""
Socratic Tutor Agent — Study Coach
=====================================
Responsabilità: gestire il loop di interrogazione socratica per una singola domanda.

Loop per ogni domanda:
    1. mostra domanda allo studente
    2. ricevi risposta_1
    3. genera domanda_guida socratica (NON dà la risposta)
    4. ricevi risposta_2
    5. valuta con score 0-10 + motivazione
    6. (opzionale) ricevi contestazione → rivaluta

Prompt versionati:
    - socratic_tutor_guide_v1.txt   → step 3
    - socratic_tutor_eval_v1.txt    → step 5
    - socratic_tutor_contest_v1.txt → step 6

Lo stato dell'intera sessione (tutte le domande + risposte) viene mantenuto
nel QuestionAttempt e poi serializzato nel qa_log della Session ORM.
"""

import json
import re
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path

import google.generativeai as genai

from ingestor import retrieve_chunks  # aggiusta al path definitivo del package

# ---------------------------------------------------------------------------
# Costanti e path dei prompt versionati
# ---------------------------------------------------------------------------

PROMPTS_DIR = Path(__file__).parent / "prompts"

PROMPT_GUIDE    = "socratic_tutor_guide_v1"
PROMPT_EVAL     = "socratic_tutor_eval_v1"
PROMPT_CONTEST  = "socratic_tutor_contest_v1"

DEFAULT_MODEL     = "gemini-1.5-flash"
DEFAULT_N_CHUNKS  = 5


# ---------------------------------------------------------------------------
# Stato del loop socratico per una singola domanda
# ---------------------------------------------------------------------------

class TurnState(Enum):
    """Stato corrente del loop per una domanda."""
    WAITING_ANSWER_1   = auto()   # in attesa della prima risposta
    WAITING_ANSWER_2   = auto()   # domanda guida inviata, in attesa della seconda risposta
    EVALUATED          = auto()   # valutato, contestazione ancora possibile
    CONTESTED          = auto()   # contestazione ricevuta, rivalutato
    CLOSED             = auto()   # chiuso definitivamente (no contestazione o già contestata)


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
    contestation_assessment: str   # "valido" | "parzialmente_valido" | "non_valido"
    final_motivation: str
    response_to_student: str


@dataclass
class QuestionAttempt:
    """
    Rappresenta il tentativo completo di uno studente su una singola domanda.
    Viene serializzato nel qa_log della Session.
    """
    question_id: int
    question_text: str
    difficulty: str
    topic_hint: str

    # Turno 1
    student_answer_1: str = ""

    # Turno 2 — guida socratica
    guiding_question: str = ""
    positive_feedback: str = ""
    focus_area: str = ""
    student_answer_2: str = ""

    # Valutazione
    evaluation: EvaluationResult | None = None

    # Contestazione (opzionale)
    contestation_text: str = ""
    contestation_result: ContestationResult | None = None

    # Stato corrente
    state: TurnState = TurnState.WAITING_ANSWER_1

    @property
    def final_score(self) -> int | None:
        """Score definitivo: usa il voto della contestazione se disponibile."""
        if self.contestation_result is not None:
            return self.contestation_result.final_score
        if self.evaluation is not None:
            return self.evaluation.score
        return None


# ---------------------------------------------------------------------------
# Caricamento prompt versionati
# ---------------------------------------------------------------------------

def _load_prompt(version_name: str) -> str:
    path = PROMPTS_DIR / f"{version_name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt non trovato: {path}")
    raw = path.read_text(encoding="utf-8")
    # Rimuove il frontmatter documentativo (tutto prima del secondo "---\n\n")
    parts = raw.split("---\n\n", maxsplit=1)
    return parts[-1]


# ---------------------------------------------------------------------------
# Parsing JSON dalla risposta LLM
# ---------------------------------------------------------------------------

def _parse_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Il modello non ha restituito JSON valido.\nErrore: {e}\n"
            f"Risposta (primi 500 char):\n{raw[:500]}"
        ) from e


# ---------------------------------------------------------------------------
# Chiamate LLM — una funzione per ogni prompt
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str, model_name: str) -> str:
    model = genai.GenerativeModel(model_name)
    response = model.generate_content(prompt)
    return response.text


def _generate_guiding_question(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> dict:
    """Step 3: genera domanda guida socratica dopo la prima risposta."""
    template = _load_prompt(PROMPT_GUIDE)
    prompt = template.format(
        question=attempt.question_text,
        student_answer_1=attempt.student_answer_1,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    raw = _call_gemini(prompt, model_name)
    data = _parse_json(raw)

    if "guiding_question" not in data:
        raise ValueError(f"Risposta mancante di 'guiding_question': {data}")
    return data


def _evaluate(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> EvaluationResult:
    """Step 5: valuta con score 0-10 dopo la seconda risposta."""
    template = _load_prompt(PROMPT_EVAL)
    prompt = template.format(
        question=attempt.question_text,
        student_answer_1=attempt.student_answer_1,
        guiding_question=attempt.guiding_question,
        student_answer_2=attempt.student_answer_2,
        context_chunks="\n\n---\n\n".join(context_chunks),
    )
    raw = _call_gemini(prompt, model_name)
    data = _parse_json(raw)

    score = int(data.get("score", 0))
    score = max(0, min(10, score))  # clamp 0-10

    return EvaluationResult(
        score=score,
        motivation=data.get("motivation", ""),
        correct_points=data.get("correct_points", []),
        missing_points=data.get("missing_points", []),
        improvement_after_guidance=data.get("improvement_after_guidance", ""),
    )


def _re_evaluate_after_contestation(
    attempt: QuestionAttempt,
    context_chunks: list[str],
    model_name: str,
) -> ContestationResult:
    """Step 6: rivaluta dopo contestazione dello studente."""
    if attempt.evaluation is None:
        raise ValueError("Impossibile rivalutare: nessuna valutazione iniziale.")

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
    raw = _call_gemini(prompt, model_name)
    data = _parse_json(raw)

    final_score = int(data.get("final_score", attempt.evaluation.score))
    final_score = max(0, min(10, final_score))

    original = attempt.evaluation.score
    delta = final_score - original

    return ContestationResult(
        final_score=final_score,
        score_changed=delta != 0,
        score_delta=delta,
        contestation_assessment=data.get("contestation_assessment", "non_valido"),
        final_motivation=data.get("final_motivation", ""),
        response_to_student=data.get("response_to_student", ""),
    )


# ---------------------------------------------------------------------------
# SocraticTutor — classe principale che gestisce il loop
# ---------------------------------------------------------------------------

class SocraticTutor:
    """
    Gestisce il loop socratico per una singola domanda.

    Utilizzo tipico (chiamato dalla route FastAPI o dalla pagina Streamlit):

        tutor = SocraticTutor(student_id=1, exam_id=3)
        tutor.start(question)                          # mostra domanda

        resp1 = tutor.submit_answer_1("...")           # ritorna domanda guida
        resp2 = tutor.submit_answer_2("...")           # ritorna valutazione
        resp3 = tutor.submit_contestation("...")       # (opzionale) ritorna rivalutazione
        tutor.close()

        attempt = tutor.attempt                        # QuestionAttempt completo
    """

    def __init__(
        self,
        student_id: int,
        exam_id: int,
        model_name: str = DEFAULT_MODEL,
        n_chunks: int = DEFAULT_N_CHUNKS,
    ):
        self.student_id  = student_id
        self.exam_id     = exam_id
        self.model_name  = model_name
        self.n_chunks    = n_chunks
        self.attempt: QuestionAttempt | None = None
        self._context_cache: list[str] = []

    # ------------------------------------------------------------------
    # API pubblica del loop
    # ------------------------------------------------------------------

    def start(self, question_data: dict) -> str:
        """
        Inizializza il tutor con una domanda.
        question_data deve avere: id, text, difficulty, topic_hint.
        Ritorna il testo della domanda da mostrare allo studente.
        """
        self.attempt = QuestionAttempt(
            question_id=question_data["id"],
            question_text=question_data["text"],
            difficulty=question_data.get("difficulty", "intermedia"),
            topic_hint=question_data.get("topic_hint", ""),
            state=TurnState.WAITING_ANSWER_1,
        )
        # Pre-carica i chunk RAG usando il topic come query
        self._context_cache = retrieve_chunks(
            query=question_data["text"],
            student_id=self.student_id,
            exam_id=self.exam_id,
            n_results=self.n_chunks,
        )
        return self.attempt.question_text

    def submit_answer_1(self, answer: str) -> dict:
        """
        Riceve la prima risposta dello studente.
        Genera e ritorna la domanda guida socratica.

        Returns:
            {
                "guiding_question": str,
                "positive_feedback": str,
                "focus_area": str,
            }
        """
        self._assert_state(TurnState.WAITING_ANSWER_1)

        self.attempt.student_answer_1 = answer.strip()

        data = _generate_guiding_question(
            self.attempt, self._context_cache, self.model_name
        )

        self.attempt.guiding_question = data["guiding_question"]
        self.attempt.positive_feedback = data.get("positive_feedback", "")
        self.attempt.focus_area = data.get("focus_area", "")
        self.attempt.state = TurnState.WAITING_ANSWER_2

        print(
            f"[SocraticTutor] Domanda guida generata | "
            f"q_id={self.attempt.question_id} | focus={self.attempt.focus_area}"
        )
        return {
            "guiding_question": self.attempt.guiding_question,
            "positive_feedback": self.attempt.positive_feedback,
            "focus_area": self.attempt.focus_area,
        }

    def submit_answer_2(self, answer: str) -> dict:
        """
        Riceve la seconda risposta (dopo la guida).
        Valuta e ritorna score + motivazione.

        Returns:
            {
                "score": int,
                "motivation": str,
                "correct_points": list[str],
                "missing_points": list[str],
                "improvement_after_guidance": str,
                "can_contest": True,
            }
        """
        self._assert_state(TurnState.WAITING_ANSWER_2)

        self.attempt.student_answer_2 = answer.strip()

        eval_result = _evaluate(self.attempt, self._context_cache, self.model_name)
        self.attempt.evaluation = eval_result
        self.attempt.state = TurnState.EVALUATED

        print(
            f"[SocraticTutor] Valutazione: {eval_result.score}/10 | "
            f"q_id={self.attempt.question_id}"
        )
        return {
            "score": eval_result.score,
            "motivation": eval_result.motivation,
            "correct_points": eval_result.correct_points,
            "missing_points": eval_result.missing_points,
            "improvement_after_guidance": eval_result.improvement_after_guidance,
            "can_contest": True,
        }

    def submit_contestation(self, argumentation: str) -> dict:
        """
        Riceve l'argomentazione di contestazione dello studente.
        Rivaluta e ritorna il verdetto finale.
        Può essere chiamato UNA SOLA VOLTA dopo submit_answer_2.

        Returns:
            {
                "final_score": int,
                "score_changed": bool,
                "score_delta": int,
                "contestation_assessment": str,
                "final_motivation": str,
                "response_to_student": str,
            }
        """
        self._assert_state(TurnState.EVALUATED)

        self.attempt.contestation_text = argumentation.strip()

        contest_result = _re_evaluate_after_contestation(
            self.attempt, self._context_cache, self.model_name
        )
        self.attempt.contestation_result = contest_result
        self.attempt.state = TurnState.CONTESTED

        print(
            f"[SocraticTutor] Contestazione: {contest_result.contestation_assessment} | "
            f"voto {self.attempt.evaluation.score} → {contest_result.final_score} | "
            f"q_id={self.attempt.question_id}"
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
        """
        Chiude il loop definitivamente. Può essere chiamato da EVALUATED o CONTESTED.
        Ritorna il QuestionAttempt completo da serializzare nel qa_log.
        """
        if self.attempt is None:
            raise RuntimeError("Tutor non inizializzato. Chiama start() prima.")
        if self.attempt.state not in (TurnState.EVALUATED, TurnState.CONTESTED):
            raise RuntimeError(
                f"Non si può chiudere in stato {self.attempt.state}. "
                "Lo studente deve aver risposto almeno due volte."
            )
        self.attempt.state = TurnState.CLOSED
        return self.attempt

    # ------------------------------------------------------------------
    # Serializzazione — per qa_log della Session
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Serializza il QuestionAttempt corrente in dict (per qa_log JSON)."""
        if self.attempt is None:
            return {}
        d = asdict(self.attempt)
        d["state"] = self.attempt.state.name  # Enum → stringa
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # Interno
    # ------------------------------------------------------------------

    def _assert_state(self, expected: TurnState) -> None:
        if self.attempt is None:
            raise RuntimeError("Tutor non inizializzato. Chiama start() prima.")
        if self.attempt.state != expected:
            raise RuntimeError(
                f"Operazione non consentita in stato '{self.attempt.state.name}'. "
                f"Stato atteso: '{expected.name}'."
            )