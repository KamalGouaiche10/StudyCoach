"""
test_adaptive_engine.py

Test unitari per la logica pura dell'Adaptive Engine.
"""

from backend.agents.adaptive_engine import AdaptiveEngine, SessionStats, TopicStats, _build_summary


def test_topic_stats_and_session_stats_thresholds():
    weak_single = TopicStats(topic="attention", scores=[4])
    borderline_strong = TopicStats(topic="transformers", scores=[6, 6])
    empty = TopicStats(topic="unused")

    assert weak_single.avg_score == 4
    assert weak_single.n_attempts == 1
    assert weak_single.is_weak is True

    assert borderline_strong.avg_score == 6
    assert borderline_strong.n_attempts == 2
    assert borderline_strong.is_weak is False

    assert empty.avg_score == 0.0
    assert empty.n_attempts == 0
    assert empty.is_weak is False

    session = SessionStats(
        student_id=11,
        exam_id=22,
        topic_stats={
            "attention": weak_single,
            "transformers": borderline_strong,
        },
        answered_question_ids=[1, 2, 3],
    )

    assert session.overall_avg == 5
    assert session.weak_topics == ["attention"]
    assert session.strong_topics == ["transformers"]
    assert "Prestazione insufficiente" in _build_summary(SessionStats(student_id=1, exam_id=1))


def test_pick_next_question_prefers_weak_then_unseen_then_first_remaining():
    engine = AdaptiveEngine(student_id=1, exam_id=2)
    engine.record_answer(question_id=1, topic="intro", score=9)
    engine.record_answer(question_id=2, topic="graphs", score=4)

    remaining = [
        {"id": 10, "topic_hint": "intro"},
        {"id": 11, "topic_hint": "graphs"},
        {"id": 12, "topic_hint": "new_topic"},
    ]

    chosen = engine.pick_next_question(remaining)
    assert chosen == {"id": 11, "topic_hint": "graphs"}

    engine = AdaptiveEngine(student_id=1, exam_id=2)
    engine.record_answer(question_id=1, topic="intro", score=9)
    remaining = [
        {"id": 20, "topic_hint": "intro"},
        {"id": 21, "topic_hint": "new_topic"},
        {"id": 22, "topic_hint": "other_new_topic"},
    ]

    chosen = engine.pick_next_question(remaining)
    assert chosen == {"id": 21, "topic_hint": "new_topic"}

    engine = AdaptiveEngine(student_id=1, exam_id=2)
    remaining = [
        {"id": 30, "topic_hint": "a"},
        {"id": 31, "topic_hint": "b"},
    ]
    assert engine.pick_next_question([]) is None
    assert engine.pick_next_question(remaining) == remaining[0]


def test_generate_session_report_contains_sorted_breakdown_and_summary():
    engine = AdaptiveEngine(student_id=7, exam_id=9)
    engine.record_answer(question_id=1, topic="topic_a", score=9)
    engine.record_answer(question_id=2, topic="topic_a", score=8)
    engine.record_answer(question_id=3, topic="topic_b", score=4)
    engine.record_answer(question_id=4, topic="topic_b", score=5)

    report = engine.generate_session_report()

    assert report["student_id"] == 7
    assert report["exam_id"] == 9
    assert report["n_questions_answered"] == 4
    assert report["overall_avg"] == 6.5
    assert report["weak_topics"] == ["topic_b"]
    assert report["strong_topics"] == ["topic_a"]
    assert [row["topic"] for row in report["topic_breakdown"]] == ["topic_b", "topic_a"]
    assert report["topic_breakdown"][0]["is_weak"] is True
    assert "Prestazione sufficiente" in report["summary"]
    assert "Argomenti da rivedere" in report["summary"]
    assert "Argomenti padroneggiati" in report["summary"]

