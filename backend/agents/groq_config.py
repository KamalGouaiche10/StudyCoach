"""Configurazione condivisa per il modello Groq usato dagli agenti."""

import os
import re

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_MODEL = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL


def safe_groq_error(error: Exception) -> str:
    """Restituisce un errore utile per i log senza esporre credenziali."""
    message = str(error)
    api_key = os.getenv("GROQ_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    message = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._-]+", r"\1[REDACTED]", message)
    message = re.sub(
        r"(?i)(groq[_ -]?api[_ -]?key\s*[=:]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        message,
    )
    return f"{type(error).__name__}: {message or 'nessun dettaglio fornito'}"

