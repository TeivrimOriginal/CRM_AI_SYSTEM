import pytest
from fastapi.testclient import TestClient
from app.database import get_db
from app.main import app
@pytest.fixture()
def client(seeded_db):
    engine, S = seeded_db
    def _override():
        db = S()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
def _sup(client):
    r = client.post("/api/auth/register", json={"email": "sup@x.com", "password": "pass123", "full_name": "Sup"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "supervisor"
def test_register_first_is_supervisor(client):
    r = client.post("/api/auth/register", json={"email": "a@x.com", "password": "pass123", "full_name": "Admin", "timezone": "Asia/Almaty"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "supervisor"
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["role"] == "supervisor"
def test_register_second_is_manager(client):
    client.post("/api/auth/register", json={"email": "a@x.com", "password": "pass123", "full_name": "Admin"})
    client.post("/api/auth/logout")
    r = client.post("/api/auth/register", json={"email": "m@x.com", "password": "pass123", "full_name": "Mgr"})
    assert r.status_code == 200
    assert r.json()["role"] == "manager"
def test_create_company_and_deal(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Test Co", "country_id": 1}).json()["id"]
    r = client.post("/api/deals", json={"company_id": cid, "title": "Site", "service_id": 1})
    assert r.status_code == 201, r.text
    did = r.json()["id"]
    d = client.get(f"/api/deals/{did}")
    assert d.status_code == 200
    assert d.json()["stage"] == "found"
def test_deal_transition_validation(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    assert client.post(f"/api/deals/{did}/transition", json={"stage": "verified"}).status_code == 422
    assert client.post(f"/api/deals/{did}/transition", json={"stage": "verified", "source_url": "https://x.com"}).status_code == 200
def test_task_lifecycle(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    r = client.post("/api/tasks", json={"deal_id": did, "action_type": "call", "summary": "Звонок", "due_at": "2026-12-01T10:00:00"})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    assert len(client.get("/api/tasks").json()) == 1
    assert client.post(f"/api/tasks/{tid}/complete").json()["state"] == "done"
def test_proposal_versions(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    contact = client.post(f"/api/companies/{cid}/contacts", json={"name": "Иван", "is_decision_maker": True}).json()
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    p1 = client.post(f"/api/deals/{did}/proposals", json={"link": "v1"}).json()
    p2 = client.post(f"/api/deals/{did}/proposals", json={"link": "v2"}).json()
    assert p1["version"] == 1 and p2["version"] == 2
    r = client.post(f"/api/proposals/{p1['id']}/sent", json={"link": "https://kp/1", "sent_channel": "email", "sent_contact_id": contact["id"]})
    assert r.status_code == 200
    assert client.get(f"/api/deals/{did}").json()["stage"] == "proposal_sent"
def test_report_shape(client):
    _sup(client)
    r = client.get("/api/reports/full")
    assert r.status_code == 200
    b = r.json()
    assert "funnel" in b and "workload" in b and "period" in b
    assert "verified_companies" in b["period"]
def test_sale_confirmation_blocked_without_criterion(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    r = client.post(f"/api/deals/{did}/confirmation", json={"confirmation_reference": "ref"})
    assert r.status_code == 409, r.text