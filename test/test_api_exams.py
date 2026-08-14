"""Integration test — backend/api/exams.py (via FastAPI TestClient, DB e Chroma isolati)."""


def _register(api_client, username="mario_rossi") -> int:
    resp = api_client.post("/auth/register", json={"username": username, "password": "secret123"})
    return resp.json()["student_id"]


def test_create_and_list_exam(api_client):
    student_id = _register(api_client)

    resp = api_client.post("/exams", params={"student_id": student_id}, json={"name": "Analisi 1"})
    assert resp.status_code == 201
    exam = resp.json()
    assert exam["name"] == "Analisi 1"
    assert exam["n_sessions"] == 0
    assert exam["avg_score"] is None

    resp = api_client.get("/exams", params={"student_id": student_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["exams"][0]["name"] == "Analisi 1"


def test_list_exams_isolated_per_student(api_client):
    student_a = _register(api_client, "mario")
    student_b = _register(api_client, "giulia")

    api_client.post("/exams", params={"student_id": student_a}, json={"name": "Esame A"})

    resp_b = api_client.get("/exams", params={"student_id": student_b})
    assert resp_b.json()["total"] == 0


def test_create_exam_rejects_empty_name(api_client):
    student_id = _register(api_client)
    resp = api_client.post("/exams", params={"student_id": student_id}, json={"name": ""})
    assert resp.status_code == 422


def test_delete_exam_removes_it(api_client):
    student_id = _register(api_client)
    exam_id = api_client.post("/exams", params={"student_id": student_id}, json={"name": "Analisi 1"}).json()["id"]

    resp = api_client.delete(f"/exams/{exam_id}", params={"student_id": student_id})
    assert resp.status_code == 204

    resp = api_client.get("/exams", params={"student_id": student_id})
    assert resp.json()["total"] == 0


def test_delete_unknown_exam_returns_404(api_client):
    student_id = _register(api_client)
    resp = api_client.delete("/exams/999999", params={"student_id": student_id})
    assert resp.status_code == 404


def test_ingest_pdf_indexes_material(api_client, sample_pdf_path):
    student_id = _register(api_client)
    exam_id = api_client.post("/exams", params={"student_id": student_id}, json={"name": "Analisi 1"}).json()["id"]

    with open(sample_pdf_path, "rb") as f:
        resp = api_client.post(
            f"/exams/{exam_id}/ingest",
            params={"student_id": student_id},
            files={"file": (sample_pdf_path.name, f, "application/pdf")},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks"] > 0
    assert body["pages"] >= 1
    assert body["collection"] == f"student_{student_id}_exam_{exam_id}"


def test_ingest_rejects_non_pdf_file(api_client):
    student_id = _register(api_client)
    exam_id = api_client.post("/exams", params={"student_id": student_id}, json={"name": "Analisi 1"}).json()["id"]

    resp = api_client.post(
        f"/exams/{exam_id}/ingest",
        params={"student_id": student_id},
        files={"file": ("note.txt", b"non e' un pdf", "text/plain")},
    )
    assert resp.status_code == 400


def test_ingest_unknown_exam_returns_404(api_client, sample_pdf_path):
    student_id = _register(api_client)
    with open(sample_pdf_path, "rb") as f:
        resp = api_client.post(
            "/exams/999999/ingest",
            params={"student_id": student_id},
            files={"file": (sample_pdf_path.name, f, "application/pdf")},
        )
    assert resp.status_code == 404


def test_delete_exam_also_removes_chroma_collection(api_client, sample_pdf_path):
    from backend.agents.ingestor import retrieve_chunks

    student_id = _register(api_client)
    exam_id = api_client.post("/exams", params={"student_id": student_id}, json={"name": "Analisi 1"}).json()["id"]

    with open(sample_pdf_path, "rb") as f:
        api_client.post(
            f"/exams/{exam_id}/ingest",
            params={"student_id": student_id},
            files={"file": (sample_pdf_path.name, f, "application/pdf")},
        )

    api_client.delete(f"/exams/{exam_id}", params={"student_id": student_id})

    chunks = retrieve_chunks("machine learning", student_id=student_id, exam_id=exam_id, n_results=3)
    assert chunks == []
