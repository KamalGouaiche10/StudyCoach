"""
test_quiz_generator.py

Test per il parsing della risposta LLM del Quiz Generator.
"""

import pytest

from backend.agents.quiz_generator import _parse_llm_response


def test_parse_llm_response_extracts_json_from_code_block():
    raw = """Prima del JSON
```json
{"questions": [{"id": 1, "text": "Cos'è l'attenzione?", "difficulty": "base", "topic_hint": "attention"}], "source_name": "slide 3"}
```
Dopo il JSON"""

    parsed = _parse_llm_response(raw)

    assert parsed["source_name"] == "slide 3"
    assert parsed["questions"][0]["id"] == 1
    assert parsed["questions"][0]["topic_hint"] == "attention"


def test_parse_llm_response_rejects_invalid_json():
    with pytest.raises(ValueError, match="JSON valido"):
        _parse_llm_response("```json\n{not valid json}\n```")


def test_parse_llm_response_requires_questions_field():
    with pytest.raises(ValueError, match="questions"):
        _parse_llm_response('{"source_name": "slides"}')

