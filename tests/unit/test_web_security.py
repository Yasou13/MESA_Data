from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from mesa_legal_data.web.security import verify_security


def test_web_security_localhost_authless(monkeypatch):
    monkeypatch.delenv("MESA_DATA_WEB_ADMIN_TOKEN", raising=False)

    app = FastAPI()

    @app.get("/test")
    def test_endpoint(request: Request):
        verify_security(request)
        return {"ok": True}

    client = TestClient(app)
    res = client.get("/test")
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_web_security_token_required(monkeypatch):
    monkeypatch.setenv("MESA_DATA_WEB_ADMIN_TOKEN", "secret123")

    app = FastAPI()

    @app.get("/test")
    def test_endpoint(request: Request):
        verify_security(request)
        return {"ok": True}

    client = TestClient(app)
    res_no_auth = client.get("/test")
    assert res_no_auth.status_code == 401

    res_auth = client.get("/test", headers={"Authorization": "Bearer secret123"})
    assert res_auth.status_code == 200


def test_web_security_csrf_write_header(monkeypatch):
    monkeypatch.delenv("MESA_DATA_WEB_ADMIN_TOKEN", raising=False)

    app = FastAPI()

    @app.post("/test-write")
    def test_write(request: Request):
        verify_security(request)
        return {"ok": True}

    client = TestClient(app)
    res_no_header = client.post("/test-write")
    assert res_no_header.status_code == 403

    res_with_header = client.post("/test-write", headers={"X-MESA-Requested-With": "web-admin"})
    assert res_with_header.status_code == 200
