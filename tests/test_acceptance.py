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
    assert r.status_code == 200 and r.json()["role"] == "supervisor"
def test_scenario_1_company_with_two_contacts_and_two_deals(client):
    _sup(client)
    r = client.post("/api/companies", json={"name": "Строй-Алматы", "country_id": 1, "niche_id": 2})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert client.post(f"/api/companies/{cid}/contacts", json={"name": "Иван", "position": "Директор", "is_decision_maker": True}).status_code == 201
    assert client.post(f"/api/companies/{cid}/contacts", json={"name": "Пётр", "position": "Менеджер"}).status_code == 201
    assert client.post("/api/deals", json={"company_id": cid, "title": "Сайт", "service_id": 1}).status_code == 201
    assert client.post("/api/deals", json={"company_id": cid, "title": "Редизайн", "service_id": 3}).status_code == 201
    deals = client.get("/api/deals").json()
    assert len([d for d in deals if d["company_id"] == cid]) == 2
def test_scenario_2_import_new_dup_error(client):
    _sup(client)
    csv_data = "name,country\nНовая,Казахстан\nНовая,Казахстан\n,Казахстан\n"
    r = client.post("/api/imports/preview", files={"file": ("t.csv", csv_data.encode("utf-8"), "text/csv")})
    assert r.status_code == 200, r.text
    rows = r.json()["rows"]
    st = [x["status"] for x in rows]
    assert st.count("ok") == 1 and st.count("dup") == 1 and st.count("error") == 1, st
    commit = client.post("/api/imports/commit", json={"rows": rows})
    assert commit.status_code == 200 and commit.json()["ok"] == 1
def test_scenario_3_tasks_today_overdue_no_next(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    t = client.post("/api/tasks", json={"deal_id": did, "action_type": "call", "summary": "Звонок", "due_at": "2026-01-01T10:00:00"})
    assert t.status_code == 201, t.text
    assert len(client.get("/api/tasks").json()) == 1
    assert client.post(f"/api/tasks/{t.json()['id']}/complete").json()["state"] == "done"
    assert len(client.get("/api/tasks").json()) == 0
def test_scenario_4_proposal_versions_and_no_link(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    contact = client.post(f"/api/companies/{cid}/contacts", json={"name": "ЛПР", "is_decision_maker": True}).json()
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    p1 = client.post(f"/api/deals/{did}/proposals", json={"link": "v1"}).json()
    p2 = client.post(f"/api/deals/{did}/proposals", json={"link": "v2"}).json()
    assert p1["version"] == 1 and p2["version"] == 2
    bad = client.post(f"/api/proposals/{p1['id']}/sent", json={"link": "", "sent_channel": "email", "sent_contact_id": contact["id"]})
    assert bad.status_code == 422
    good = client.post(f"/api/proposals/{p1['id']}/sent", json={"link": "https://kp", "sent_channel": "email", "sent_contact_id": contact["id"]})
    assert good.status_code == 200
    assert client.get(f"/api/deals/{did}").json()["stage"] == "proposal_sent"
def test_scenario_5_handoff_then_sale(client):
    _sup(client)
    client.post("/api/settings", json={"key": "SALE_CONFIRMATION_CRITERION", "value": "manual"})
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    contact = client.post(f"/api/companies/{cid}/contacts", json={"name": "ЛПР", "is_decision_maker": True}).json()
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    p = client.post(f"/api/deals/{did}/proposals", json={"link": "v1"}).json()
    client.post(f"/api/proposals/{p['id']}/sent", json={"link": "https://kp", "sent_channel": "email", "sent_contact_id": contact["id"]})
    r = client.post(f"/api/deals/{did}/handoff", json={"recipient_id": 1, "proposal_id": p["id"], "agreed_scope": "scope", "agreed_price": 1000, "currency": "KZT", "agreed_deadline_or_note": "2 недели"})
    assert r.status_code == 200, r.text
    assert client.get(f"/api/deals/{did}").json()["stage"] == "handed_over"
    rep = client.get("/api/reports/full").json()
    assert rep["period"]["handoffs"] == 1 and rep["period"]["sales_confirmed"] == 0
    assert client.post(f"/api/deals/{did}/confirmation", json={"confirmation_reference": "INV-1"}).status_code == 200
    rep2 = client.get("/api/reports/full").json()
    assert rep2["period"]["sales_confirmed"] == 1
    assert client.post(f"/api/deals/{did}/confirmation", json={"confirmation_reference": "INV-1"}).status_code == 200
    rep3 = client.get("/api/reports/full").json()
    assert rep3["period"]["sales_confirmed"] == 1
def test_scenario_6_two_currencies(client):
    _sup(client)
    client.post("/api/settings", json={"key": "SALE_CONFIRMATION_CRITERION", "value": "manual"})
    for cur, amt in (("KZT", 100000), ("USD", 500)):
        cid = client.post("/api/companies", json={"name": f"Co-{cur}", "country_id": 1}).json()["id"]
        did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1, "amount": amt, "currency": cur}).json()["id"]
        client.post(f"/api/deals/{did}/confirmation", json={"confirmation_reference": f"ref-{cur}"})
    rep = client.get("/api/reports/full").json()
    assert rep["period"]["amounts"].get("KZT") == 100000
    assert rep["period"]["amounts"].get("USD") == 500
def test_scenario_7_manager_isolation(client):
    client.post("/api/auth/register", json={"email": "sup@x.com", "password": "pass123", "full_name": "Sup"})
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "m1@x.com", "password": "pass123", "full_name": "M1"})
    r = client.post("/api/companies", json={"name": "Foreign", "country_id": 1})
    assert r.status_code == 201, r.text
    foreign_id = r.json()["id"]
    client.post("/api/auth/logout")
    client.post("/api/auth/register", json={"email": "m2@x.com", "password": "pass123", "full_name": "M2"})
    assert client.get(f"/api/companies/{foreign_id}").status_code == 403
def test_scenario_8_sale_blocked_without_criterion(client):
    _sup(client)
    cid = client.post("/api/companies", json={"name": "Co", "country_id": 1}).json()["id"]
    did = client.post("/api/deals", json={"company_id": cid, "title": "T", "service_id": 1}).json()["id"]
    r = client.post(f"/api/deals/{did}/confirmation", json={"confirmation_reference": "ref"})
    assert r.status_code == 409, r.text