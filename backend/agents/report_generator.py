"""
Report Generator — Study Coach
================================
Responsabilità: generare il report finale di una sessione in formato
Markdown e PDF a partire dal report dict prodotto dall'Adaptive Engine.
Il report finale include:
    - reports/{student_id}_{exam_id}_{session_id}.md
    - reports/{student_id}_{exam_id}_{session_id}.pdf
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fpdf import FPDF

REPORTS_DIR = Path(__file__).parent.parent.parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def generate_markdown(report: dict,session_id: int,exam_name: str = "Esame",) -> str:
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    avg = report.get("overall_avg", 0)
    n_q = report.get("n_questions_answered", 0)
    weak = report.get("weak_topics", [])
    strong = report.get("strong_topics", [])
    breakdown = report.get("topic_breakdown", [])
    summary = report.get("summary", "")

    if avg >= 8:
        verdict = "🟢 Ottimo"
    elif avg >= 6:
        verdict = "🟡 Sufficiente"
    else:
        verdict = "🔴 Insufficiente"

    lines = [ f"# Report Sessione — {exam_name}", f"", f"**Data:** {now}  ", f"**Sessione ID:** {session_id}  ",
        f"**Studente ID:** {report.get('student_id')}  ", f"**Esame ID:** {report.get('exam_id')}  ", f"",f"---",
        f"", f"## Risultato Complessivo",f"", f"| Metrica | Valore |", f"|---|---|",f"| Media sessione | **{avg}/10** |",
        f"| Domande completate | {n_q} |",f"| Verdetto | {verdict} |",f"",f"---",f"",f"## Performance per Argomento",
        f"",f"| Argomento | Media | Tentativi | Stato |",f"|---|---|---|---|",]

    for t in breakdown:
        stato = "⚠️ Da rivedere" if t["is_weak"] else "✅ Padroneggiato"
        lines.append(  f"| {t['topic']} | {t['avg_score']}/10 | {t['n_attempts']} | {stato} |")

    lines += [ f"", f"---", f"", f"## Aree da Rivedere", f"",]
    if weak:
        for t in weak:
            lines.append(f"- ❌ {t}")
    else:
        lines.append("Nessuna area critica. Ottimo lavoro!")

    lines += [ f"",  f"## Punti di Forza",  f"",]
    if strong:
        for t in strong:
            lines.append(f"- ✅ {t}")
    else:
        lines.append("Continua a studiare per consolidare gli argomenti.")

    lines += [f"",f"---",f"",f"## Sintesi",f"",f"{summary}",f"",f"---",f"",f"*Report generato automaticamente da Study Coach*",]

    return "\n".join(lines)


# PDF

class _ReportPDF(FPDF):
    """Sottoclasse FPDF con header e footer personalizzati."""

    def header(self) -> None:
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(80, 80, 80)
        self.cell(0, 8, "Study Coach — Report Sessione")
        self.ln(4)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Pagina {self.page_no()}", align="C")


def _add_section_title(pdf: FPDF, title: str) -> None:
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(40, 40, 40)
    pdf.ln(4)
    pdf.cell(0, 8, title)
    pdf.ln(8)
    pdf.set_draw_color(180, 180, 180)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)


def _add_body(pdf: FPDF, text: str) -> None:
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 6, text)
    pdf.ln(2)


def generate_pdf( report: dict, session_id: int, exam_name: str = "Esame",) -> bytes:
    avg = report.get("overall_avg", 0)
    n_q = report.get("n_questions_answered", 0)
    weak = report.get("weak_topics", [])
    strong = report.get("strong_topics", [])
    breakdown = report.get("topic_breakdown", [])
    summary = report.get("summary", "")
    now = datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")

    if avg >= 8:
        verdict = "Ottimo"
    elif avg >= 6:
        verdict = "Sufficiente"
    else:
        verdict = "Insufficiente"

    pdf = _ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Titolo
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, f"Report Sessione — {exam_name}")
    pdf.ln(12)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, f"Generato il {now} | Sessione #{session_id}")
    pdf.ln(10)

    # Risultato complessivo
    _add_section_title(pdf, "Risultato Complessivo")
    if avg >= 8:
        pdf.set_text_color(0, 140, 0)
    elif avg >= 6:
        pdf.set_text_color(200, 140, 0)
    else:
        pdf.set_text_color(200, 0, 0)
    pdf.set_font("Helvetica", "B", 28)
    pdf.cell(0, 14, f"{avg}/10")
    pdf.ln(14)
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 6, f"Verdetto: {verdict}")
    pdf.ln(6)
    pdf.cell(0, 6, f"Domande completate: {n_q}")
    pdf.ln(10)

    # Tabella topic
    _add_section_title(pdf, "Performance per Argomento")
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_text_color(40, 40, 40)
    pdf.cell(90, 7, "Argomento", border=1, fill=True)
    pdf.cell(25, 7, "Media", border=1, fill=True, align="C")
    pdf.cell(25, 7, "Tentativi", border=1, fill=True, align="C")
    pdf.cell(40, 7, "Stato", border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 10)
    for t in breakdown:
        stato = "Da rivedere" if t["is_weak"] else "Padroneggiato"
        if t["is_weak"]:
            pdf.set_text_color(180, 0, 0)
        else:
            pdf.set_text_color(0, 130, 0)
        pdf.cell(90, 6, str(t["topic"])[:45], border=1)
        pdf.cell(25, 6, f"{t['avg_score']}/10", border=1, align="C")
        pdf.cell(25, 6, str(t["n_attempts"]), border=1, align="C")
        pdf.cell(40, 6, stato, border=1, align="C")
        pdf.ln()

    pdf.set_text_color(60, 60, 60)
    pdf.ln(4)

    # Aree da rivedere
    _add_section_title(pdf, "Aree da Rivedere")
    if weak:
        for t in weak:
            _add_body(pdf, f"  - {t}")
    else:
        _add_body(pdf, "Nessuna area critica. Ottimo lavoro!")

    # Punti di forza
    _add_section_title(pdf, "Punti di Forza")
    if strong:
        for t in strong:
            _add_body(pdf, f"  - {t}")
    else:
        _add_body(pdf, "Continua a studiare per consolidare gli argomenti.")

    # Sintesi
    _add_section_title(pdf, "Sintesi")
    _add_body(pdf, summary)

    return bytes(pdf.output())


# Salvataggio su disco

def save_report(report: dict,session_id: int,exam_name: str = "Esame",) -> dict[str, str]:
    """
    Genera e salva Markdown e PDF su disco.
    Returns: {"md": path_md, "pdf": path_pdf}
    """
    student_id = report.get("student_id", 0)
    exam_id = report.get("exam_id", 0)
    base_name = f"{student_id}_{exam_id}_{session_id}"

    md_path = REPORTS_DIR / f"{base_name}.md"
    pdf_path = REPORTS_DIR / f"{base_name}.pdf"

    md_path.write_text(generate_markdown(report, session_id, exam_name), encoding="utf-8")
    pdf_path.write_bytes(generate_pdf(report, session_id, exam_name))

    print(f"[ReportGenerator] Salvato: {md_path}")
    print(f"[ReportGenerator] Salvato: {pdf_path}")

    return {"md": str(md_path), "pdf": str(pdf_path)}