import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base, get_db
from app.main import app
from app.models import User
from app.security import hash_password
@pytest.fixture()
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    def _override():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _override
    db = TestingSession()
    db.add(User(email="sup@x", password_hash=hash_password("pass"), full_name="Sup", role="supervisor"))
    db.add(User(email="mgr@x", password_hash=hash_password("pass"), full_name="Mgr", role="manager"))
    db.commit()
    db.close()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
def test_login_ok_and_me(client):
    res = client.post("/login", json={"email": "mgr@x", "password": "pass"})
    assert res.status_code == 200
    assert "access_token" in client.cookies
    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["role"] == "manager"
def test_login_wrong_password(client):
    res = client.post("/login", json={"email": "mgr@x", "password": "nope"})
    assert res.status_code == 401
def test_me_unauthorized(client):
    res = client.get("/me")
    assert res.status_code == 401
def test_login_page_200(client):
    res = client.get("/login")
    assert res.status_code == 200
    assert "Вход в CRM" in res.text
def test_index_redirects_anonymous(client):
    res = client.get("/", allow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/login"
def test_logout(client):
    client.post("/login", json={"email": "mgr@x", "password": "pass"})
    res = client.post("/logout")
    assert res.status_code == 200
    me = client.get("/me")
    assert me.status_code == 401