"""Presentation helpers shared by all pages. CSS is built locally with Tailwind."""

from html import escape
from base64 import b64encode
from functools import lru_cache
from pathlib import Path

import streamlit as st


def load_styles() -> None:
    css = (Path(__file__).parent / "styles" / "app.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


def icon(name: str = "book") -> str:
    paths = {
        "book": '<path d="M12 7c-3-2-6-2-9-1v14c3-1 6-1 9 1 3-2 6-2 9-1V6c-3-1-6-1-9 1Z"/><path d="M12 7v14"/>',
        "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
        "chat": '<path d="M21 11a9 9 0 0 1-9 9 10 10 0 0 1-4-.9L3 21l1.9-5A9 9 0 1 1 21 11Z"/><path d="M8 10h8M8 14h5"/>',
        "study": '<path d="m8 5 11 7-11 7Z"/>',
        "history": '<path d="M3 11a9 9 0 1 1 2.6 7M3 4v7h7M12 7v5l3 2"/>',
    }
    # st.html sanitizes with the HTML-only DOMPurify profile, stripping inline
    # SVG nodes. An image data URI preserves the vector without enabling JS.
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#bdd5bf" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{paths.get(name, paths["book"])}</svg>'
    uri = b64encode(svg.encode("utf-8")).decode("ascii")
    return f'<img class="sc-icon" width="20" height="20" src="data:image/svg+xml;base64,{uri}" alt="" aria-hidden="true">'


@lru_cache(maxsize=1)
def _logo_uri() -> str:
    svg = (Path(__file__).parent / "assets" / "logo.svg").read_bytes()
    return "data:image/svg+xml;base64," + b64encode(svg).decode("ascii")


def logo(size: int = 36) -> str:
    return f'<img class="sc-logo" src="{_logo_uri()}" width="{size}" height="{size}" alt="Logo Study Coach">'


def brand(context: str = "") -> None:
    crumb = f'<span class="sc:text-muted" aria-hidden="true">/</span><strong>{escape(context)}</strong>' if context else ""
    st.html(f'<div class="sc-breadcrumb"><div class="sc-brand">{logo()}<span>Study Coach</span></div>{crumb}</div>')


def page_heading(title: str, description: str, eyebrow: str = "") -> None:
    overline = f'<div class="sc-eyebrow">{escape(eyebrow)}</div>' if eyebrow else ""
    st.html(f'<div class="sc-page-heading">{overline}<h1>{escape(title)}</h1><p>{escape(description)}</p></div>')


def section(title: str, description: str = "") -> None:
    st.html(f'<div class="sc-section"><h2>{escape(title)}</h2><p>{escape(description)}</p></div>')


def empty_state(title: str, description: str, symbol: str = "book") -> None:
    st.html(f'<div class="sc-empty"><span class="sc-mark">{icon(symbol)}</span><h2>{escape(title)}</h2><p>{escape(description)}</p></div>')


def source_row(filename: str, pages: int, ready: bool) -> str:
    status = "Disponibile per lo studio" if ready else "Nessun testo indicizzato"
    return f'<div class="sc-source"><span class="sc-mark">{icon("file")}</span><div class="sc:min-w-0"><div class="sc-source-name">{escape(filename)}</div><div class="sc-meta">PDF · {pages} pagine<br>{status}</div></div></div>'


def agent_status(name: str, state: str) -> None:
    st.html(f'<div class="sc-agent-status" role="status"><span class="sc-dot" aria-hidden="true"></span><strong>{escape(name)}</strong><span>· {escape(state)}</span></div>')


def study_steps(current: int = 0) -> None:
    labels = ["Prima risposta", "Domanda guida", "Valutazione"]
    steps = []
    for index, label in enumerate(labels):
        selected = ' aria-current="step"' if index == current else ""
        steps.append(f'<div class="sc-step"{selected}><b>{index + 1}</b>{label}</div>')
    st.html('<div class="sc-workflow" aria-label="Fasi dello studio">' + "".join(steps) + '</div>')
