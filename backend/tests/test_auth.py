"""auth 流：注册（年龄强校验）→ 登录 → me → 登出。"""
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_register_requires_age_confirmed(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "minor@test.com", "password": "password123",
              "display_name": "小明", "age_confirmed": False},
    )
    assert resp.status_code == 400


def test_register_login_me_logout(client):
    resp = client.post(
        "/api/auth/register",
        json={"email": "a@test.com", "password": "password123",
              "display_name": "阿测", "age_confirmed": True},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "阿测"
    assert "jh_token" in resp.cookies

    resp = client.get("/api/auth/me")
    assert resp.status_code == 200 and resp.json()["email"] == "a@test.com"

    # 重复注册拒绝
    resp = client.post(
        "/api/auth/register",
        json={"email": "a@test.com", "password": "password123",
              "display_name": "阿测", "age_confirmed": True},
    )
    assert resp.status_code == 409

    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401

    # 登录
    resp = client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "password123"}
    )
    assert resp.status_code == 200
    resp = client.post(
        "/api/auth/login", json={"email": "a@test.com", "password": "wrongpass123"}
    )
    assert resp.status_code == 401


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_sessions_require_auth(client):
    client.post("/api/auth/logout")
    client.cookies.clear()
    assert client.get("/api/sessions").status_code == 401
