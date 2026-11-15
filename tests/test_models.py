# ===== tests/test_models.py =====
from datetime import datetime

from app.enums import DealStage, ProposalState
from app.models import (
    Activity, City, Company, Contact, Country, Deal, Handoff, Niche,
    Proposal, Service, Task, User,
)


def _mk_dirs(db):
    kz = Country(name="Казахстан")
    db.add(kz); db.flush()
    almaty = City(country_id=kz.id, name="Алматы")
    niche = Niche(name="Строительство и ремонт")
    svc = Service(name="Разработка сайта с нуля")
    db.add_all([almaty, niche, svc]); db.flush()
    return kz, almaty, niche, svc


def test_full_chain(db):
    su = User(email="s@x", password_hash="x", full_name="S")
    mgr = User(email="m@x", password_hash="x", full_name="M")
    db.add_all([su, mgr]); db.flush()
    kz, almaty, niche, svc = _mk_dirs(db)

    c = Company(name="ООО Тест", country_id=kz.id, city_id=almaty.id,
                niche_id=niche.id, owner_id=mgr.id, normalized_domain="test.kz")
    db.add(c); db.flush()

    contact = Contact(company_id=c.id, name="Иван", is_decision_maker=True)
    db.add(contact); db.flush()

    d = Deal(company_id=c.id, contact_id=contact.id, owner_id=mgr.id,
             title="Сайт", service_id=svc.id, stage=DealStage.FOUND)
    db.add(d); db.flush()

    p1 = Proposal(deal_id=d.id, version=1, state=ProposalState.SENT,
                  sent_at=datetime.utcnow(), sent_by=mgr.id,
                  sent_contact_id=contact.id, sent_channel="email",
                  link="https://x/1")
    p2 = Proposal(deal_id=d.id, version=2, state=ProposalState.DRAFT)
    db.add_all([p1, p2]); db.flush()

    assert d.proposals and len(d.proposals) == 2
    assert {p.version for p in d.proposals} == {1, 2}

    t = Task(deal_id=d.id, assignee_id=mgr.id, action_type="call",
             summary="Позвонить", due_at=datetime.utcnow())
    db.add(t); db.flush()

    a = Activity(company_id=c.id, deal_id=d.id, actor_id=mgr.id,
                 activity_type="proposal_sent", notes="v1")
    db.add(a); db.flush()

    h = Handoff(deal_id=d.id, recipient_id=su.id, proposal_id=p1.id,
                agreed_scope="scope", agreed_price=1000, currency="KZT",
                agreed_deadline_or_note="2 недели", created_by=mgr.id)
    db.add(h); db.commit()

    assert db.get(Deal, d.id).stage == DealStage.FOUND
    assert db.get(Handoff, h.id).deal_id == d.id


def test_proposal_version_unique(db):
    from sqlalchemy.exc import IntegrityError
    su = User(email="s@x2", password_hash="x", full_name="S")
    db.add(su); db.flush()
    kz, almaty, niche, svc = _mk_dirs(db)
    c = Company(name="A", country_id=kz.id, owner_id=su.id); db.add(c); db.flush()
    d = Deal(company_id=c.id, owner_id=su.id, title="t", service_id=svc.id)
    db.add(d); db.flush()
    db.add(Proposal(deal_id=d.id, version=1)); db.commit()
    db.add(Proposal(deal_id=d.id, version=1))
    try:
        db.commit()
        assert False, "unique violated"
    except IntegrityError:
        db.rollback()


def test_handoff_unique_per_deal(db):
    from sqlalchemy.exc import IntegrityError
    su = User(email="s@x3", password_hash="x", full_name="S")
    db.add(su); db.flush()
    kz, almaty, niche, svc = _mk_dirs(db)
    c = Company(name="B", country_id=kz.id, owner_id=su.id); db.add(c); db.flush()
    d = Deal(company_id=c.id, owner_id=su.id, title="t", service_id=svc.id)
    db.add(d); db.flush()
    p = Proposal(deal_id=d.id, version=1); db.add(p); db.flush()
    h1 = Handoff(deal_id=d.id, recipient_id=su.id, proposal_id=p.id,
                 agreed_scope="s", agreed_price=1, currency="KZT",
                 agreed_deadline_or_note="n", created_by=su.id)
    db.add(h1); db.commit()
    db.add(Handoff(deal_id=d.id, recipient_id=su.id, proposal_id=p.id,
                   agreed_scope="s", agreed_price=1, currency="KZT",
                   agreed_deadline_or_note="n", created_by=su.id))
    try:
        db.commit()
        assert False
    except IntegrityError:
        db.rollback()