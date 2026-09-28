
from __future__ import annotations

from datetime import datetime
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import random
import re
import time
import unicodedata

from agno.agent import Agent
from agno.models.groq import Groq
from dotenv import load_dotenv

try:
    from fpdf import FPDF
except ImportError:
    FPDF = object

from backend.agents.ingestor import retrieve_chunks, retrieve_chunks_by_source
from backend.agents.groq_config import GROQ_MODEL

load_dotenv()

# ---------------------------------------------------------------------------
# Costanti
# ---------------------------------------------------------------------------

PROMPT_VERSION = "notes_generator_v1"
PROMPT_PATH = Path(__file__).parent / "prompts" / f"{PROMPT_VERSION}.txt"
DEFAULT_MODEL = GROQ_MODEL
DEFAULT_N_CHUNKS = 10
MIN_NOTES_LENGTH = 700
RETRY_DELAY = 5
MAX_LLM_ATTEMPTS = 4
MAX_BACKOFF_SECONDS = 60
RETRY_SAFETY_MARGIN = 1.0
MAX_COMPLETION_TOKENS = 2048

# Margini PDF (in mm)
LEFT_MARGIN = 18
RIGHT_MARGIN = 18
TOP_MARGIN = 25      # Aumentato per evitare header
BOTTOM_MARGIN = 22   # Aumentato per evitare footer

# Altezze di linea (in mm)
LINE_HEIGHT = 5.5
TITLE_HEIGHT = 8.0
SUBTITLE_HEIGHT = 6.5


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prompt_template() -> str:
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Prompt template non trovato: {PROMPT_PATH}")
    raw = PROMPT_PATH.read_text(encoding="utf-8")
    parts = raw.split("---\n\n", maxsplit=1)
    return parts[-1]


def _is_error_response(text: str) -> bool:
    if not text:
        return True
    error_patterns = [
        r'^1\'error\':', r'^\{.*"error":', r'"message":\s*"Rate limit reached"',
        r'"type":\s*"tokens"', r'"code":\s*"rate_limit_exceeded"',
        r'Rate limit reached for model', r'Please try again in', r'Upgrade to Dev Tier',
    ]
    for pattern in error_patterns:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            return True
    if text.strip().startswith('{') and '"error"' in text:
        return True
    return False


def _parse_error_retry_time(text: str) -> float | None:
    """Parse explicit retry delays, including fractional seconds; never guess."""
    prefix = r"(?:(?:try again )?in\s*|wait(?: for)?\s*)?"
    match = re.search(prefix + r'(\d+)h(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?', text, re.IGNORECASE)
    if match:
        h, m, s = int(match.group(1)), int(match.group(2) or 0), float(match.group(3) or 0)
        return max(0.0, h * 3600 + m * 60 + s)
    match = re.search(prefix + r'(\d+(?:\.\d+)?)\s*(seconds?|secs?|s)\b', text, re.IGNORECASE)
    if match:
        return max(0.0, float(match.group(1)))
    match = re.search(prefix + r'(\d+(?:\.\d+)?)\s*(minutes?|mins?|m)\b', text, re.IGNORECASE)
    if match:
        return max(0.0, float(match.group(1)) * 60)
    return None


def _retry_after_seconds(error: Exception) -> float | None:
    """Read Retry-After from the SDK exception or its attached HTTP response."""
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or getattr(error, "headers", None) or {}
    value = headers.get("Retry-After") or headers.get("retry-after")
    if value is not None:
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(value))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError, OverflowError):
                pass
    return _parse_error_retry_time(str(error))


def _is_rate_limit_error(error: Exception | str) -> bool:
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status = status or getattr(response, "status_code", None)
    text = str(error).lower()
    return status == 429 or "rate limit" in text or "rate_limit_exceeded" in text or "too many requests" in text


def _api_error_label(error: Exception) -> str:
    """Logga classe e status dell'errore, mai body o dati della richiesta."""
    response = getattr(error, "response", None)
    status = getattr(error, "status_code", None) or getattr(response, "status_code", None)
    status_label = f"HTTP {status}" if status is not None else "status non disponibile"
    return f"{status_label} ({type(error).__name__})"


def _retry_delay(attempt: int, error: Exception | str | None = None) -> tuple[float, str]:
    if error is not None:
        server_delay = _retry_after_seconds(error) if isinstance(error, Exception) else _parse_error_retry_time(error)
        if server_delay is not None:
            return server_delay + RETRY_SAFETY_MARGIN, "retry-after Groq"
    backoff = min(MAX_BACKOFF_SECONDS, RETRY_DELAY * (2 ** (attempt - 1)))
    jittered = backoff + random.uniform(0, min(1.0, backoff * 0.1))
    return min(MAX_BACKOFF_SECONDS, jittered), "exponential backoff"


def _log_usage(output: object) -> str:
    usage = getattr(output, "usage", None)
    if usage is None:
        usage = getattr(output, "token_usage", None)
    if usage is None:
        metrics = getattr(output, "metrics", None)
        usage = metrics.get("token_usage") if isinstance(metrics, dict) else getattr(metrics, "token_usage", None)
    if usage is None:
        return "token usage non disponibile"
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    else:
        input_tokens = getattr(usage, "input_tokens", getattr(usage, "prompt_tokens", None))
        output_tokens = getattr(usage, "output_tokens", getattr(usage, "completion_tokens", None))
    return f"token input={input_tokens or '?'} output={output_tokens or '?'}"


def _make_notes_agent(model_name: str) -> Agent:
    return Agent(
        name="NotesGeneratorAgent",
        model=Groq(id=model_name, max_tokens=MAX_COMPLETION_TOKENS),
        description=(
            "Genera appunti accademici completi in Markdown sulla base del prompt. "
            "Rispetta tutti i vincoli richiesti e includi obbligatoriamente una sezione "
            "con heading esatto `## Riepilogo`. Non aggiungere commenti esterni agli appunti."
        ),
        markdown=True,
    )


def _build_log_summary(attempts: list[dict]) -> str:
    lines = []
    for i, a in enumerate(attempts, 1):
        q = a.get("question_text", "")
        topic = a.get("topic_hint", "")
        score = a.get("final_score", "—")
        ans = a.get("student_answer_2", "")
        missing = []
        eval_data = a.get("evaluation", {})
        if isinstance(eval_data, dict):
            missing = eval_data.get("missing_points", [])
        lines.append(f"Domanda {i} [{topic}] (voto: {score}/10):")
        lines.append(f"  Testo: {q}")
        if ans:
            lines.append(f"  Risposta: {ans[:300]}{'...' if len(ans) > 300 else ''}")
        if missing:
            lines.append(f"  Lacune: {'; '.join(missing)}")
        lines.append("")
    return "\n".join(lines)


def _extract_weak_topics(attempts: list[dict]) -> list[str]:
    weak = []
    for a in attempts:
        score = a.get("final_score")
        topic = a.get("topic_hint", "")
        if isinstance(score, (int, float)) and score < 6 and topic:
            weak.append(topic)
    return list(dict.fromkeys(weak))


def _pdf_safe_text(value: object) -> str:
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    replacements = {
        "’": "'", "‘": "'", "“": '"', "”": '"',
        "–": "-", "—": "-", "…": "...",
        "•": "-", "→": "->", "←": "<-",
        "✓": "OK", "✅": "OK", "⚠": "!",
        "📘": "", "📄": "", "€": "Euro",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or (ord(ch) >= 32 and ord(ch) <= 255))
    return text


def _strip_inline(text: str) -> str:
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text


def _clean_chunk(text: str) -> str:
    text = re.sub(r"[^\x09\x0A\x20-\xFF]", " ", text)
    text = re.sub(r"(?<!\w)`(?!\w)", " ", text)
    text = re.sub(r"\\\s", " ", text)
    text = re.sub(r"\\(?![a-zA-Z])", " ", text)
    text = re.sub(r"\|", " ", text)
    text = re.sub(r"\*{3,}", " ", text)
    text = re.sub(r"~{2,}", " ", text)
    text = re.sub(r"\\[a-zA-Z]*\^?\*?", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\s*", " ", text)
    text = re.sub(r"Study Coach\s*[-|]\s*Pagina\s*\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Pagina\s+\d+\s+di\s+\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"Appunti:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    lines = text.splitlines()
    clean_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            clean_lines.append("")
            continue
        letters = sum(ch.isalpha() for ch in stripped)
        if len(stripped) > 10 and letters < len(stripped) * 0.25:
            continue
        clean_lines.append(line)
    return "\n".join(clean_lines).strip()


def _clean_chunks(chunks: list[str]) -> list[str]:
    cleaned = []
    seen = set()
    for chunk in chunks:
        c = _clean_chunk(chunk)
        normalized = re.sub(r"\s+", " ", c).casefold()
        if len(c) >= 80 and normalized not in seen:
            cleaned.append(c)
            seen.add(normalized)
    return cleaned


def _validate_notes(notes: str) -> tuple[bool, str]:
    if not notes:
        return False, "Testo vuoto"
    if _is_error_response(notes):
        return False, "Errore API"
    word_count = len(re.findall(r'\b\w+\b', notes))
    if word_count < MIN_NOTES_LENGTH:
        return False, f"Troppo corto ({word_count} parole)"
    if not re.search(r"(?m)^\s*#{1,2}\s+\S+", notes):
        return False, "Manca: heading di capitolo"
    if not re.search(r"(?m)^\s*>\s*\*{0,2}\s*Definizione\b", notes, re.IGNORECASE):
        return False, "Manca: definizione formale"
    if not _has_summary_heading(notes):
        return False, "Manca: sezione ## Riepilogo"
    if re.search(r'\\[a-zA-Z]+\^?\*', notes):
        return False, "LaTeX corrotto"
    return True, ""


def _has_summary_heading(notes: str) -> bool:
    # Accetta differenze Markdown minori, suffissi e maiuscole; il prompt
    # richiede comunque che i nuovi output usino esattamente ## Riepilogo.
    return bool(re.search(
        r"(?im)^\s*#{1,6}\s+[*_`]*\s*riepilogo\b[^\n]*$",
        notes,
    ))


def _summary_correction_prompt(notes: str) -> str:
    return (
        "Aggiungi in fondo agli appunti la sola sezione finale richiesta, con il titolo esatto "
        "`## Riepilogo`, contenente 7-10 punti chiave basati esclusivamente sugli appunti qui sotto. "
        "Non riscrivere né ripetere gli appunti. Restituisci solo titolo e punti del riepilogo.\n\n"
        f"APPUNTI:\n{notes}"
    )


def _repair_prompt(notes: str, reason: str) -> str:
    return (
        f"Correggi solo il problema indicato: {reason}. Conserva tutti i contenuti utili, "
        "senza introdurre informazioni non presenti negli appunti. Restituisci il documento "
        "completo in Markdown, con il titolo esatto `## Riepilogo`.\n\n"
        f"APPUNTI DA CORREGGERE:\n{notes}"
    )


def _run_with_retry(agent: Agent, prompt: str) -> str:
    """Genera appunti con retry limitati e correzioni mirate della risposta."""
    current_prompt = prompt
    current_notes: str | None = None
    summary_only_correction = False
    last_reason = "generazione iniziale"
    msg = "risposta non valida"

    for attempt in range(1, MAX_LLM_ATTEMPTS + 1):
        model = getattr(getattr(agent, "model", None), "id", DEFAULT_MODEL)
        print(f"[NotesGenerator] modello={model} tentativo={attempt}/{MAX_LLM_ATTEMPTS} motivo={last_reason}")
        try:
            output = agent.run(current_prompt, stream=False)
            response = output.get_content_as_string().strip()
            if _is_error_response(response):
                if _is_rate_limit_error(response):
                    delay, source = _retry_delay(attempt, response)
                    print(f"[NotesGenerator] retry per HTTP 429 ({source}), delay={delay:.1f}s")
                    if attempt >= MAX_LLM_ATTEMPTS:
                        last_reason = "HTTP 429: limite tentativi esaurito"
                        break
                    time.sleep(delay)
                    continue
                raise RuntimeError("Groq ha restituito un errore API nella risposta")

            if summary_only_correction and current_notes is not None:
                response = current_notes.rstrip() + "\n\n" + response.lstrip()
            is_valid, msg = _validate_notes(response)
            print(f"[NotesGenerator] validazione={'ok' if is_valid else msg}; {_log_usage(output)}")
            if is_valid:
                return response

            current_notes = response
            if attempt >= MAX_LLM_ATTEMPTS:
                last_reason = f"validazione non superata: {msg}"
                break
            summary_only_correction = msg == "Manca: sezione ## Riepilogo"
            current_prompt = (
                _summary_correction_prompt(current_notes)
                if summary_only_correction
                else _repair_prompt(current_notes, msg)
            )
            last_reason = f"correzione mirata: {msg}"
        except Exception as e:
            delay, source = _retry_delay(attempt, e) if _is_rate_limit_error(e) else _retry_delay(attempt)
            error_label = _api_error_label(e)
            print(f"[NotesGenerator] errore Groq {error_label}; retry ({source}), delay={delay:.1f}s")
            if attempt >= MAX_LLM_ATTEMPTS:
                raise RuntimeError(
                    f"NotesGenerator: esauriti {MAX_LLM_ATTEMPTS} tentativi; "
                    f"ultimo errore {error_label}"
                ) from e
            time.sleep(delay)
            last_reason = "errore API/trasporto"
            continue

    raise RuntimeError(
        f"NotesGenerator: {last_reason}; massimo {MAX_LLM_ATTEMPTS} tentativi "
        f"(ultimo problema: {msg})"
    )

# ---------------------------------------------------------------------------
# CLASSE PDF PROFESSIONALE CON LAYOUT CORRETTO
# ---------------------------------------------------------------------------

class _NotesPDF(FPDF):
    """PDF con header, footer e margini corretti, senza sovrapposizioni."""

    def __init__(self, title_str: str = "Appunti"):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.title_str = title_str
        self.set_margins(LEFT_MARGIN, TOP_MARGIN, RIGHT_MARGIN)
        self.set_auto_page_break(auto=True, margin=BOTTOM_MARGIN)
        self._page_start_y = TOP_MARGIN
        self._footer_height = 12

    def header(self):
        """Header: solo sulle pagine dopo la prima."""
        if self.page_no() <= 1:
            return
        # Banda sottile colorata
        self.set_fill_color(44, 62, 80)
        self.rect(0, 0, self.w, 8, "F")
        self.set_y(1.5)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(200, 210, 220)
        self.cell(0, 5, _pdf_safe_text(self.title_str), align="R")
        self.set_text_color(40, 40, 40)
        # Aggiorna la posizione di partenza per il contenuto
        self._page_start_y = 12

    def footer(self):
        """Footer con numero di pagina."""
        self.set_y(-12)
        self.set_draw_color(189, 195, 199)
        self.line(LEFT_MARGIN, self.get_y(), self.w - RIGHT_MARGIN, self.get_y())
        self.ln(1.5)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Study Coach | Pagina {self.page_no()}", align="C")

    def check_page_break(self, needed_height: float) -> bool:
        """Verifica se c'è spazio per un blocco di altezza `needed_height`."""
        current_y = self.get_y()
        max_y = self.h - BOTTOM_MARGIN - self._footer_height
        if current_y + needed_height > max_y:
            self.add_page()
            return True
        return False

    def ensure_space(self, needed_height: float = 15.0):
        """Assicura che ci sia spazio per il prossimo blocco."""
        if self.check_page_break(needed_height):
            self.set_y(self._page_start_y)


# ---------------------------------------------------------------------------
# RENDERER MARKDOWN CON LAYOUT PULITO
# ---------------------------------------------------------------------------

def _render_markdown(pdf: _NotesPDF, text_md: str):
    """
    Renderer Markdown → PDF con layout professionale e senza sovrapposizioni.
    Gestisce: H2, H3, H4, Blockquote (>), Bullet (-), Numerate (1.), Paragrafi.
    """
    PAGE_W = pdf.w - LEFT_MARGIN - RIGHT_MARGIN
    LH = LINE_HEIGHT
    BULLET_INDENT = 6.0
    SUBBULLET_INDENT = 14.0
    QUOTE_INDENT = 6.0

    # Reset posizione
    pdf.set_y(pdf._page_start_y)

    lines = text_md.splitlines()
    i = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # Riga vuota → piccolo spazio
        if not line:
            pdf.ln(2)
            i += 1
            continue

        # --- Separatore ---
        if re.match(r"^-{3,}$|^\*{3,}$|^_{3,}$", line):
            pdf.ensure_space(8)
            y = pdf.get_y()
            pdf.set_draw_color(189, 195, 199)
            pdf.set_line_width(0.3)
            pdf.line(LEFT_MARGIN, y, LEFT_MARGIN + PAGE_W, y)
            pdf.set_line_width(0.2)
            pdf.ln(4)
            i += 1
            continue

        # --- H2: Capitolo (sfondo blu scuro, testo bianco) ---
        if line.startswith("## "):
            txt = _pdf_safe_text(_strip_inline(line[3:].strip()))
            pdf.ensure_space(12)
            pdf.set_fill_color(44, 62, 80)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_x(LEFT_MARGIN)
            pdf.multi_cell(PAGE_W, 9, f"  {txt}", fill=True)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(4)
            i += 1
            continue

        # --- H3: Sottocapitolo (testo blu, sottolineato) ---
        if line.startswith("### "):
            txt = _pdf_safe_text(_strip_inline(line[4:].strip()))
            pdf.ensure_space(10)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(41, 128, 185)
            pdf.set_x(LEFT_MARGIN)
            pdf.multi_cell(PAGE_W, 7, txt)
            # Sottolineatura
            y = pdf.get_y()
            pdf.set_draw_color(41, 128, 185)
            pdf.set_line_width(0.5)
            pdf.line(LEFT_MARGIN, y, LEFT_MARGIN + min(PAGE_W * 0.50, len(txt) * 1.2), y)
            pdf.set_line_width(0.2)
            pdf.set_draw_color(200, 200, 200)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(3)
            i += 1
            continue

        # --- H4: Nota (testo blu scuro, corsivo grassetto) ---
        if line.startswith("#### "):
            txt = _pdf_safe_text(_strip_inline(line[5:].strip()))
            pdf.ensure_space(8)
            pdf.set_font("Helvetica", "BI", 11)
            pdf.set_text_color(52, 73, 94)
            pdf.set_x(LEFT_MARGIN)
            pdf.multi_cell(PAGE_W, 6, txt)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(2)
            i += 1
            continue

        # --- Blockquote: Definizioni/Teoremi (bordo blu a sinistra) ---
        if line.startswith("> "):
            content = _pdf_safe_text(_strip_inline(line[2:].strip()))
            # Stima altezza del blocco
            estimated_lines = max(1, len(content) // 60 + 1)
            needed = estimated_lines * LH + 6
            pdf.ensure_space(needed)

            y_start = pdf.get_y()
            pdf.set_font("Helvetica", "I", 10.5)
            pdf.set_text_color(44, 62, 80)
            pdf.set_x(LEFT_MARGIN + QUOTE_INDENT + 2)
            pdf.multi_cell(PAGE_W - QUOTE_INDENT - 4, LH, content)
            y_end = pdf.get_y()

            # Bordo blu a sinistra
            pdf.set_draw_color(41, 128, 185)
            pdf.set_line_width(1.2)
            pdf.line(LEFT_MARGIN + QUOTE_INDENT - 1, y_start, LEFT_MARGIN + QUOTE_INDENT - 1, y_end)
            pdf.set_line_width(0.2)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(2)
            i += 1
            continue

        # --- Bullet indentato (sub-bullet) ---
        if re.match(r"^ {2,}[-*]\s+", raw):
            content = _pdf_safe_text(_strip_inline(re.sub(r"^ +[-*]\s+", "", raw).strip()))
            pdf.ensure_space(6)
            pdf.set_font("Helvetica", "", 10.5)
            pdf.set_text_color(60, 60, 60)
            pdf.set_x(LEFT_MARGIN + SUBBULLET_INDENT)
            pdf.cell(5, LH, "-")
            pdf.multi_cell(PAGE_W - SUBBULLET_INDENT - 5, LH, content)
            pdf.set_x(LEFT_MARGIN)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(1)
            i += 1
            continue

        # --- Bullet principale ---
        if re.match(r"^[-*]\s+", line):
            content = _pdf_safe_text(_strip_inline(line[2:].strip()))
            pdf.ensure_space(6)
            pdf.set_x(LEFT_MARGIN + BULLET_INDENT)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_text_color(41, 128, 185)
            pdf.cell(6, LH, "·")
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(PAGE_W - BULLET_INDENT - 6, LH, content)
            pdf.set_x(LEFT_MARGIN)
            pdf.ln(1)
            i += 1
            continue

        # --- Lista numerata ---
        num_match = re.match(r"^(\d+)\.\s+(.+)$", line)
        if num_match:
            num = num_match.group(1) + "."
            content = _pdf_safe_text(_strip_inline(num_match.group(2).strip()))
            pdf.ensure_space(6)
            pdf.set_x(LEFT_MARGIN + BULLET_INDENT)
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(44, 62, 80)
            pdf.cell(9, LH, num)
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(40, 40, 40)
            pdf.multi_cell(PAGE_W - BULLET_INDENT - 9, LH, content)
            pdf.set_x(LEFT_MARGIN)
            pdf.ln(1)
            i += 1
            continue

        # --- Paragrafo normale ---
        txt = _pdf_safe_text(_strip_inline(line))
        pdf.ensure_space(6)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(40, 40, 40)
        pdf.set_x(LEFT_MARGIN)
        pdf.multi_cell(PAGE_W, LH, txt)
        pdf.ln(2)
        i += 1


# ---------------------------------------------------------------------------
# Frontespizio
# ---------------------------------------------------------------------------

def _add_front_page(pdf: _NotesPDF, title: str, subtitle: str):
    """Frontespizio professionale."""
    pdf.add_page()
    PAGE_W = pdf.w - LEFT_MARGIN - RIGHT_MARGIN

    # Banda superiore
    pdf.set_fill_color(44, 62, 80)
    pdf.rect(0, 0, pdf.w, 55, "F")

    # Titolo
    pdf.set_y(18)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(255, 255, 255)
    pdf.multi_cell(0, 12, _pdf_safe_text(title), align="C")

    # Sottotitolo
    pdf.set_y(68)
    pdf.set_font("Helvetica", "I", 14)
    pdf.set_text_color(189, 195, 199)
    pdf.multi_cell(0, 9, _pdf_safe_text(subtitle), align="C")

    # Linea decorativa
    pdf.ln(8)
    pdf.set_draw_color(41, 128, 185)
    pdf.set_line_width(1.0)
    pdf.line(LEFT_MARGIN + PAGE_W * 0.2, pdf.get_y(), LEFT_MARGIN + PAGE_W * 0.8, pdf.get_y())
    pdf.set_line_width(0.2)

    # Data
    pdf.set_y(-45)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, f"Generato il {datetime.now().strftime('%d/%m/%Y')}", align="C", ln=True)
    pdf.set_font("Helvetica", "I", 9)
    pdf.cell(0, 7, "Study Coach - Appunti generati automaticamente", align="C")


# ---------------------------------------------------------------------------
# API PUBBLICA
# ---------------------------------------------------------------------------

def generate_notes(
        student_id: int,
        exam_id: int,
        topic_query: str = "concetti principali del corso",
        n_chunks: int = DEFAULT_N_CHUNKS,
        source_name: str = "materiale di studio",
        model_name: str = DEFAULT_MODEL,
) -> str:
    chunks = retrieve_chunks(query=topic_query, student_id=student_id, exam_id=exam_id, n_results=n_chunks)
    if not chunks:
        raise ValueError(f"Nessun chunk trovato per student_id={student_id}, exam_id={exam_id}")
    chunks = _clean_chunks(chunks)
    context = "\n\n---\n\n".join(chunks)
    template = _load_prompt_template()
    prompt = template.format(mode="materiale", source_name=source_name, context=context, log_summary="", weak_topics="")
    agent = _make_notes_agent(model_name)
    notes = _run_with_retry(agent, prompt)
    print(f"[NotesGenerator] Appunti generati | parole={len(re.findall(r'\\b\\w+\\b', notes))}")
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
    if FPDF is object:
        raise RuntimeError("FPDF non disponibile. Installa fpdf2.")

    notes_md = generate_notes(
        student_id=student_id,
        exam_id=exam_id,
        topic_query=topic_query,
        n_chunks=n_chunks,
        source_name=source_name,
        model_name=model_name,
    )

    pdf = _NotesPDF(title_str=f"Appunti: {source_name}")
    _add_front_page(pdf, f"Appunti di Studio\n{source_name}", "Generati automaticamente da Study Coach")

    # Contenuto
    pdf.add_page()
    _render_markdown(pdf, notes_md)

    # Pagine aggiuntive se necessario
    while pdf.page_no() < min_pages:
        pdf.add_page()
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(150, 150, 150)
        pdf.cell(0, 10, "(pagina intenzionalmente lasciata vuota)", align="C")

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
        exam_name_fallback: str | None = None,
) -> bytes:
    if FPDF is object:
        raise RuntimeError("FPDF non disponibile. Installa fpdf2.")

    exam_name = exam_name_fallback or "Materiali di Studio"
    if materials:
        try:
            if hasattr(materials[0], "exam") and materials[0].exam:
                exam_name = materials[0].exam.name
        except Exception:
            pass

    pdf = _NotesPDF(title_str=f"Appunti: {exam_name}")
    _add_front_page(pdf, exam_name, "Sintesi completa dei materiali caricati")

    if not materials:
        pdf.add_page()
        _render_markdown(pdf, "## Nessun materiale caricato.\nCarica dei PDF per generare gli appunti.")
    else:
        global_chunks = _clean_chunks(retrieve_chunks("concetti principali", student_id, exam_id, n_results=15))
        has_content = False

        for material in materials:
            filename = getattr(material, "filename", None) or material.get("filename", "materiale di studio")

            chunks = _clean_chunks(retrieve_chunks_by_source(student_id, exam_id, filename, limit=12))
            if not chunks:
                chunks = global_chunks
            if not chunks:
                continue

            has_content = True
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(52, 73, 94)
            pdf.cell(0, 10, _pdf_safe_text(f"Fonte: {filename}"), ln=True)
            pdf.ln(2)

            context = "\n\n---\n\n".join(chunks)
            template = _load_prompt_template()
            prompt = template.format(mode="materiale", source_name=filename, context=context, log_summary="", weak_topics="")
            agent = _make_notes_agent(model_name)
            notes_md = _run_with_retry(agent, prompt)

            _render_markdown(pdf, notes_md)

        if not has_content:
            if not global_chunks:
                raise ValueError(
                    f"Nessun contenuto indicizzato trovato per student_id={student_id}, exam_id={exam_id}."
                )
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(52, 73, 94)
            pdf.cell(0, 10, "Sintesi Generale dell'Esame", ln=True)
            pdf.ln(2)
            context = "\n\n---\n\n".join(global_chunks)
            template = _load_prompt_template()
            prompt = template.format(mode="materiale", source_name="Sintesi Globale", context=context, log_summary="", weak_topics="")
            agent = _make_notes_agent(model_name)
            notes_md = _run_with_retry(agent, prompt)
            _render_markdown(pdf, notes_md)

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
    if not attempts:
        raise ValueError("Lista attempts vuota")

    log_summary = _build_log_summary(attempts)
    weak_topics = _extract_weak_topics(attempts)
    weak_str = ", ".join(weak_topics) if weak_topics else "nessuna lacuna rilevata"

    rag_context = ""
    if enrich_with_rag and student_id and exam_id and weak_topics:
        query = " ".join(weak_topics[:3])
        rag_chunks = _clean_chunks(retrieve_chunks(query, student_id, exam_id, n_results=6))
        rag_context = "\n\n---\n\n".join(rag_chunks)

    template = _load_prompt_template()
    prompt = template.format(
        mode="sessione",
        source_name=source_name,
        context=rag_context or "(nessun contesto RAG aggiuntivo)",
        log_summary=log_summary,
        weak_topics=weak_str,
    )

    agent = _make_notes_agent(model_name)
    notes = _run_with_retry(agent, prompt)
    print(f"[NotesGenerator] Post-sessione | parole={len(re.findall(r'\\b\\w+\\b', notes))}")
    return notes
