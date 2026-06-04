#!/usr/bin/env python3
"""
Test script per validare la generazione e salvataggio dei PDF report.
Verifica che il fix per i caratteri non-latin1 funzioni correttamente.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.agents.report_generator import generate_pdf, save_report, _pdf_safe_text


def test_pdf_safe_text():
    """Test la funzione di sicurezza per caratteri non-latin1."""
    print("[TEST 1] Testing _pdf_safe_text()...")

    test_cases = [
        ("Normal text", "Normal text"),
        ("Reti — neurali", "Reti - neurali"),  # em-dash → hyphen
        ("Studio — Avanzato — Completo", "Studio - Avanzato - Completo"),
        ("Text with 你好", "Text with ?"),  # non-latin1 chars
    ]

    for input_text, expected_contains in test_cases:
        result = _pdf_safe_text(input_text)
        print(f"  Input: {input_text!r:40} → {result!r}")
        assert "—" not in result, f"em-dash still present in: {result}"
    print("  ✅ PASSED\n")


def test_pdf_generation():
    """Test la generazione del PDF con vari payload."""
    print("[TEST 2] Testing PDF generation with special characters...")

    payloads = [
        {
            "name": "Esame base",
            "data": {
                'overall_avg': 7.5,
                'n_questions_answered': 5,
                'weak_topics': ['Funzioni'],
                'strong_topics': ['Array', 'Puntatori'],
                'topic_breakdown': [
                    {'topic': 'Array — Gestione dinamica', 'avg_score': 8.5, 'n_attempts': 2, 'is_weak': False},
                    {'topic': 'Funzioni — Ricorsione', 'avg_score': 5.0, 'n_attempts': 3, 'is_weak': True},
                ],
                'summary': 'Performance variabile — Consolidare funzioni ricorsive.',
                'student_id': 1,
                'exam_id': 1
            }
        },
        {
            "name": "Esame con emoji",
            "data": {
                'overall_avg': 8.0,
                'n_questions_answered': 3,
                'weak_topics': [],
                'strong_topics': ['Reti neurali'],
                'topic_breakdown': [
                    {'topic': 'Reti neurali 🧠', 'avg_score': 8.5, 'n_attempts': 3, 'is_weak': False},
                ],
                'summary': 'Ottimo — Continuare con argomenti avanzati 📚',
                'student_id': 1,
                'exam_id': 2
            }
        },
    ]

    for i, payload_info in enumerate(payloads, 1):
        print(f"  Subtest 2.{i}: {payload_info['name']}")
        try:
            pdf_bytes = generate_pdf(payload_info['data'], session_id=i, exam_name=payload_info['name'])
            assert isinstance(pdf_bytes, bytes), f"PDF output is not bytes: {type(pdf_bytes)}"
            assert len(pdf_bytes) > 500, f"PDF too small: {len(pdf_bytes)} bytes"
            print(f"    ✅ Generated: {len(pdf_bytes)} bytes")
        except Exception as e:
            print(f"    ❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            return False
    print("  ✅ PASSED\n")
    return True


def test_full_save_report():
    """Test il salvataggio completo con rigenerazione."""
    print("[TEST 3] Testing full save_report() workflow...")

    payload = {
        'overall_avg': 8.3,
        'n_questions_answered': 4,
        'weak_topics': [],
        'strong_topics': ['Algoritmi'],
        'topic_breakdown': [
            {'topic': 'Algoritmi — Sorting', 'avg_score': 8.3, 'n_attempts': 4, 'is_weak': False},
        ],
        'summary': 'Buono — Proseguire con algoritmi avanzati.',
        'student_id': 2,
        'exam_id': 3
    }

    session_id = 999
    exam_name = "Test — Advanced Algorithms"

    try:
        paths = save_report(payload, session_id, exam_name)
        print(f"  Markdown: {paths.get('md')}")
        print(f"  PDF:      {paths.get('pdf')}")

        if paths.get('pdf'):
            pdf_path = Path(paths['pdf'])
            assert pdf_path.exists(), f"PDF file not created: {pdf_path}"
            size = pdf_path.stat().st_size
            print(f"    ✅ PDF exists, {size} bytes")

        if paths.get('md'):
            md_path = Path(paths['md'])
            assert md_path.exists(), f"Markdown file not created: {md_path}"
            md_content = md_path.read_text()
            assert "8.3/10" in md_content or "8.3" in md_content, "Average score not in markdown"
            print(f"    ✅ Markdown exists, {len(md_content)} chars")

        print("  ✅ PASSED\n")
        return True
    except Exception as e:
        print(f"  ❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "="*70)
    print("PDF GENERATION FIX VALIDATION TEST SUITE")
    print("="*70 + "\n")

    results = []

    try:
        test_pdf_safe_text()
        results.append(("_pdf_safe_text()", True))
    except Exception as e:
        print(f"❌ FAILED: {e}\n")
        results.append(("_pdf_safe_text()", False))

    if not test_pdf_generation():
        results.append(("PDF generation", False))
    else:
        results.append(("PDF generation", True))

    if not test_full_save_report():
        results.append(("Full save_report", False))
    else:
        results.append(("Full save_report", True))

    print("="*70)
    print("SUMMARY")
    print("="*70)
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:30} {status}")

    all_passed = all(r[1] for r in results)
    print("\n" + ("🎉 ALL TESTS PASSED!" if all_passed else "⚠️  SOME TESTS FAILED"))
    sys.exit(0 if all_passed else 1)

