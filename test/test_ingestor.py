"""Unit/integration test — backend/agents/ingestor.py."""

import pytest

from backend.agents import ingestor


# ---------------------------------------------------------------------------
# chunk_text — logica pura
# ---------------------------------------------------------------------------

def test_chunk_text_single_chunk_for_short_text():
    chunks = ingestor.chunk_text("parola " * 10, chunk_size=500, overlap=50)
    assert len(chunks) == 1


def test_chunk_text_splits_long_text_with_overlap():
    text = " ".join(f"parola{i}" for i in range(1000))
    chunks = ingestor.chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    # L'overlap fa si' che le ultime parole di un chunk ricompaiano nel successivo.
    last_words_first_chunk = chunks[0].split()[-10:]
    assert any(w in chunks[1] for w in last_words_first_chunk)


def test_chunk_text_empty_string_returns_empty_list():
    assert ingestor.chunk_text("") == []


# ---------------------------------------------------------------------------
# get_collection — naming/isolamento per studente+esame
# ---------------------------------------------------------------------------

def test_get_collection_naming_is_isolated_per_student_and_exam(isolated_chroma):
    coll_a = ingestor.get_collection(student_id=1, exam_id=1)
    coll_b = ingestor.get_collection(student_id=1, exam_id=2)
    coll_c = ingestor.get_collection(student_id=2, exam_id=1)

    assert coll_a.name == "student_1_exam_1"
    assert coll_b.name == "student_1_exam_2"
    assert coll_c.name == "student_2_exam_1"
    assert coll_a.name != coll_b.name != coll_c.name


# ---------------------------------------------------------------------------
# ingest_pdf / retrieve_chunks / retrieve_chunks_by_source (con embedding finti)
# ---------------------------------------------------------------------------

def test_ingest_pdf_missing_file_raises(isolated_chroma):
    with pytest.raises(FileNotFoundError):
        ingestor.ingest_pdf("/percorso/inesistente.pdf", student_id=1, exam_id=1)


def test_ingest_pdf_indexes_chunks_with_correct_stats(isolated_chroma, sample_pdf_path):
    stats = ingestor.ingest_pdf(str(sample_pdf_path), student_id=1, exam_id=1)
    assert stats["file"] == sample_pdf_path.name
    assert stats["pages"] >= 1
    assert stats["chunks"] > 0
    assert stats["collection"] == "student_1_exam_1"


def test_retrieve_chunks_returns_indexed_content(isolated_chroma, sample_pdf_path):
    ingestor.ingest_pdf(str(sample_pdf_path), student_id=1, exam_id=1)
    chunks = ingestor.retrieve_chunks("machine learning", student_id=1, exam_id=1, n_results=3)
    assert len(chunks) > 0
    assert any("machine learning" in c.lower() for c in chunks)


def test_retrieve_chunks_isolated_per_exam(isolated_chroma, sample_pdf_path):
    ingestor.ingest_pdf(str(sample_pdf_path), student_id=1, exam_id=1)
    # Nessun materiale indicizzato per l'esame 2: nessun risultato.
    chunks = ingestor.retrieve_chunks("machine learning", student_id=1, exam_id=2, n_results=3)
    assert chunks == []


def test_retrieve_chunks_by_source_filters_by_filename(isolated_chroma, sample_pdf_path):
    ingestor.ingest_pdf(str(sample_pdf_path), student_id=1, exam_id=1)
    chunks = ingestor.retrieve_chunks_by_source(student_id=1, exam_id=1, source_file=sample_pdf_path.name)
    assert len(chunks) > 0

    empty = ingestor.retrieve_chunks_by_source(student_id=1, exam_id=1, source_file="altro_file.pdf")
    assert empty == []


def test_delete_exam_collection_removes_indexed_data(isolated_chroma, sample_pdf_path):
    ingestor.ingest_pdf(str(sample_pdf_path), student_id=1, exam_id=1)
    ingestor.delete_exam_collection(student_id=1, exam_id=1)

    chunks = ingestor.retrieve_chunks("machine learning", student_id=1, exam_id=1, n_results=3)
    assert chunks == []


def test_delete_exam_collection_missing_collection_does_not_raise(isolated_chroma):
    ingestor.delete_exam_collection(student_id=999, exam_id=999)
