"""Строго 100 записей в каждой таблице. Очищает users, companies, contacts, deals,
proposals, tasks, activities, handoffs и создаёт заново ровно 100 в каждой.
Запуск: python -m tests.seed_test_data
"""
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import delete, func, select
from app.database import SessionLocal
from app.enums import (
    ActivityType, DealStage, MarketCheckStatus, ProposalState, Role,
    TaskActionType, TaskState,
)
from app.models import (
    Activity, City, Company, Contact, Country, Deal, Handoff, Niche,
    Proposal, Service, Task, User,
)
from app.security import hash_password
random.seed(42)
NOW = datetime.now(timezone.utc)
COUNTRIES = ["Казахстан", "Узбекистан", "Армения", "Кыргызстан", "Беларусь"]
TZ = ["Europe/Moscow", "Asia/Almaty", "Asia/Astana", "Asia/Tashkent", "Asia/Yerevan", "Asia/Bishkek", "Europe/Minsk", "UTC"]
POSITIONS = ["Директор", "Менеджер", "Владелец", "Маркетолог", "Коммерческий директор", "Руководитель"]
COMPANY_PREFIX = ["Строй", "Альфа", "Мастер", "Гранд", "Техно", "Уют", "Быстрый", "Профи", "Дельта", "Мега",
                  "Ресторан", "Кафе", "Агентство", "Барбершоп", "Монтаж", "Оборудование", "Курсы", "Отель", "Клиника", "Авто"]
COMPANY_SUFFIX = ["Град", "Ремонт", "Бетон", "Дом", "Сервис", "Плюс", "Про", "Групп", "Строй", "Мастер",
                  "Кз", "Центр", "Студия", "Торг", "Опт", "Логистика", "Тур", "Фитнес", "Салон", "Магазин"]
def _clear(db):
    from sqlalchemy import text
    db.execute(text("""
        TRUNCATE TABLE handoffs, activities, tasks, proposals, deals,
                       contacts, companies, journal, users
        RESTART IDENTITY CASCADE
    """))
    db.commit()
def _dirs(db):
    countries = db.scalars(select(Country)).all()
    cities = db.scalars(select(City)).all()
    niches = db.scalars(select(Niche)).all()
    services = db.scalars(select(Service)).all()
    if not (countries and cities and niches and services):
        raise SystemExit("Справочники пусты. Запусти: python -m app.seed")
    return countries, cities, niches, services
def _users(db):
    users = []
    for i in range(100):
        role = Role.SUPERVISOR if i == 0 else Role.MANAGER
        u = User(
            email=f"user{i}@crm.local",
            password_hash=hash_password("pass123"),
            full_name=f"Сотрудник {i:03d}",
            role=role,
            timezone=TZ[i % len(TZ)],
            is_active=True,
            created_at=NOW - timedelta(days=random.randint(0, 365)),
        )
        db.add(u)
        users.append(u)
    db.commit()
    return users
def _companies(db, users, countries, cities, niches):
    companies = []
    for i in range(100):
        country = countries[i % len(countries)]
        country_cities = [c for c in cities if c.country_id == country.id]
        city = random.choice(country_cities) if country_cities else None
        niche = random.choice(niches)
        owner = random.choice(users)
        name = f"{COMPANY_PREFIX[i % len(COMPANY_PREFIX)]}{COMPANY_SUFFIX[i % len(COMPANY_SUFFIX)]} {i:03d}"
        domain = f"client{i}.example.com"
        c = Company(
            name=name,
            country_id=country.id,
            city_id=city.id if city else None,
            niche_id=niche.id,
            website_url=f"https://{domain}",
            normalized_domain=domain,
            source_url=f"https://source.example.com/{i}",
            owner_id=owner.id,
            observed_need=f"Потребность клиента {i}: сайт с каталогом",
            verified_at=NOW - timedelta(days=random.randint(1, 200)),
            created_at=NOW - timedelta(days=random.randint(1, 200)),
        )
        db.add(c)
        companies.append(c)
    db.commit()
    return companies
def _contacts(db, companies):
    contacts = []
    for i, c in enumerate(companies):
        ct = Contact(
            company_id=c.id,
            name=f"Контакт {i:03d}",
            position=POSITIONS[i % len(POSITIONS)],
            is_decision_maker=(i % 2 == 0),
            work_email=f"contact{i}@example.com",
            work_phone=f"+7 7{random.randint(100000000, 999999999)}",
            preferred_channel="email",
            contact_basis="Публичный сайт",
        )
        db.add(ct)
        contacts.append(ct)
    db.commit()
    return contacts
def _deals(db, companies, contacts, services):
    stages = list(DealStage)
    deals = []
    for i, c in enumerate(companies):
        stage = stages[i % len(stages)]
        currency = "KZT" if i % 2 == 0 else "USD"
        amount = Decimal(random.randint(100000, 5000000)) if currency == "KZT" else Decimal(random.randint(500, 20000))
        contact = contacts[i]
        agreed = stage in (DealStage.TERMS_AGREED, DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED)
        d = Deal(
            company_id=c.id,
            contact_id=contact.id,
            owner_id=c.owner_id,
            title=f"Сделка по {c.name}",
            service_id=services[i % len(services)].id,
            customer_need=f"Нужен {services[i % len(services)].name.lower()}",
            amount=amount,
            currency=currency,
            stage=stage,
            agreed_scope=f"Объём {i}" if agreed else None,
            agreed_deadline_or_note=f"Срок {i}" if agreed else None,
            agreement_reference=f"https://agree.example.com/{i}" if agreed else None,
            loss_reason="Клиент выбрал другого" if stage == DealStage.LOST else None,
            defer_until=NOW + timedelta(days=14) if stage == DealStage.DEFERRED else None,
            handed_over_at=NOW - timedelta(days=random.randint(1, 30)) if stage in (DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED) else None,
            confirmed_at=NOW - timedelta(days=random.randint(1, 20)) if stage == DealStage.SALE_CONFIRMED else None,
            confirmation_reference=f"INV-{i}" if stage == DealStage.SALE_CONFIRMED else None,
            created_at=NOW - timedelta(days=random.randint(1, 90)),
        )
        db.add(d)
        deals.append(d)
    db.commit()
    return deals
def _proposals(db, deals, contacts):
    proposals = []
    for i, d in enumerate(deals):
        sent = d.stage not in (DealStage.FOUND, DealStage.VERIFIED, DealStage.DM_FOUND)
        p = Proposal(
            deal_id=d.id,
            version=1,
            link=f"https://kp.example.com/{d.id}",
            state=ProposalState.SENT if sent else ProposalState.READY,
            sent_at=NOW - timedelta(days=random.randint(1, 60)) if sent else None,
            sent_by=d.owner_id if sent else None,
            sent_contact_id=d.contact_id if sent else None,
            sent_channel="email" if sent else None,
        )
        db.add(p)
        proposals.append(p)
    db.commit()
    return proposals
def _tasks(db, deals, users):
    tasks = []
    for i, d in enumerate(deals):
        assignee = next((u for u in users if u.id == d.owner_id), users[0])
        if i % 3 == 0:
            due = NOW - timedelta(days=random.randint(1, 10))
            state = TaskState.OPEN
        elif i % 3 == 1:
            due = NOW + timedelta(hours=random.randint(1, 12))
            state = TaskState.OPEN
        else:
            due = NOW + timedelta(days=random.randint(1, 30))
            state = TaskState.DONE if i % 5 == 0 else TaskState.OPEN
        t = Task(
            deal_id=d.id,
            assignee_id=assignee.id,
            action_type=random.choice(list(TaskActionType)),
            summary=f"Действие по {d.title}",
            due_at=due,
            state=state,
            completed_at=NOW - timedelta(days=random.randint(1, 5)) if state == TaskState.DONE else None,
        )
        db.add(t)
        tasks.append(t)
    db.commit()
    return tasks
def _activities(db, deals, proposals, companies):
    for i, d in enumerate(deals):
        db.add(Activity(
            company_id=d.company_id, deal_id=d.id, actor_id=d.owner_id,
            activity_type=ActivityType.STAGE_CHANGE, occurred_at=NOW - timedelta(days=random.randint(60, 90)),
            notes=f"Создана: {d.title}",
        ))
        if d.stage not in (DealStage.FOUND, DealStage.VERIFIED, DealStage.DM_FOUND):
            db.add(Activity(
                company_id=d.company_id, deal_id=d.id, actor_id=d.owner_id,
                activity_type=ActivityType.PROPOSAL_SENT, occurred_at=NOW - timedelta(days=random.randint(20, 60)),
                notes="КП отправлено",
            ))
        if d.stage in (DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED):
            db.add(Activity(
                company_id=d.company_id, deal_id=d.id, actor_id=d.owner_id,
                activity_type=ActivityType.HANDOFF, occurred_at=d.handed_over_at,
                notes="Передано",
            ))
        if d.stage == DealStage.SALE_CONFIRMED:
            db.add(Activity(
                company_id=d.company_id, deal_id=d.id, actor_id=d.owner_id,
                activity_type=ActivityType.SALE_CONFIRMATION, occurred_at=d.confirmed_at,
                notes=f"Подтверждено: {d.confirmation_reference}",
            ))
        if d.stage == DealStage.LOST:
            db.add(Activity(
                company_id=d.company_id, deal_id=d.id, actor_id=d.owner_id,
                activity_type=ActivityType.STAGE_CHANGE, occurred_at=NOW - timedelta(days=random.randint(1, 20)),
                notes=f"lost: {d.loss_reason}",
            ))
    db.commit()
def _handoffs(db, deals, proposals):
    for d in deals:
        if d.stage in (DealStage.HANDED_OVER, DealStage.SALE_CONFIRMED):
            p = next((p for p in proposals if p.deal_id == d.id), None)
            if not p:
                continue
            db.add(Handoff(
                deal_id=d.id, recipient_id=d.owner_id, proposal_id=p.id,
                agreed_scope=d.agreed_scope or "Объём",
                agreed_price=d.amount or Decimal("0"),
                currency=d.currency or "KZT",
                agreed_deadline_or_note=d.agreed_deadline_or_note or "2 недели",
                materials_link=f"https://drive.example.com/{d.id}",
                created_by=d.owner_id, created_at=d.handed_over_at,
            ))
    db.commit()
def main():
    db = SessionLocal()
    try:
        _clear(db)
        countries, cities, niches, services = _dirs(db)
        users = _users(db)
        companies = _companies(db, users, countries, cities, niches)
        contacts = _contacts(db, companies)
        deals = _deals(db, companies, contacts, services)
        proposals = _proposals(db, deals, contacts)
        tasks = _tasks(db, deals, users)
        _activities(db, deals, proposals, companies)
        _handoffs(db, deals, proposals)
        counts = {
            "users": db.scalar(select(func.count()).select_from(User)),
            "companies": db.scalar(select(func.count()).select_from(Company)),
            "contacts": db.scalar(select(func.count()).select_from(Contact)),
            "deals": db.scalar(select(func.count()).select_from(Deal)),
            "proposals": db.scalar(select(func.count()).select_from(Proposal)),
            "tasks": db.scalar(select(func.count()).select_from(Task)),
            "activities": db.scalar(select(func.count()).select_from(Activity)),
            "handoffs": db.scalar(select(func.count()).select_from(Handoff)),
        }
        print("OK:", counts)
    finally:
        db.close()
if __name__ == "__main__":
    main()