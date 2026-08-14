"""Integration test — backend/api/auth.py (via FastAPI TestClient + DB isolato)."""


def test_register_creates_student(api_client):
    resp = api_client.post("/auth/register", json={"username": "mario_rossi", "password": "secret123"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["username"] == "mario_rossi"
    assert isinstance(body["student_id"], int)


def test_register_duplicate_username_conflicts(api_client):
    api_client.post("/auth/register", json={"username": "mario_rossi", "password": "secret123"})
    resp = api_client.post("/auth/register", json={"username": "mario_rossi", "password": "another123"})
    assert resp.status_code == 409


def test_register_rejects_short_password(api_client):
    resp = api_client.post("/auth/register", json={"username": "mario_rossi", "password": "123"})
    assert resp.status_code == 422


def test_register_rejects_short_username(api_client):
    resp = api_client.post("/auth/register", json={"username": "ab", "password": "secret123"})
    assert resp.status_code == 422


def test_login_with_correct_credentials(api_client):
    api_client.post("/auth/register", json={"username": "mario_rossi", "password": "secret123"})
    resp = api_client.post("/auth/login", json={"username": "mario_rossi", "password": "secret123"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "mario_rossi"


def test_login_with_wrong_password_unauthorized(api_client):
    api_client.post("/auth/register", json={"username": "mario_rossi", "password": "secret123"})
    resp = api_client.post("/auth/login", json={"username": "mario_rossi", "password": "wrongpass"})
    assert resp.status_code == 401


def test_login_unknown_username_unauthorized(api_client):
    resp = api_client.post("/auth/login", json={"username": "nessuno", "password": "whatever"})
    assert resp.status_code == 401


def test_logout_returns_message(api_client):
    resp = api_client.post("/auth/logout")
    assert resp.status_code == 200
    assert "message" in resp.json()
