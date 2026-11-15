import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.database import Base
from app.models import City, Country, Niche, Service
@pytest.fixture()
def seeded_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, expire_on_commit=False)
    db = S()
    kz = Country(name="Казахстан", market_check_required=False)
    by = Country(name="Беларусь", market_check_required=True)
    db.add_all([kz, by]); db.flush()
    db.add_all([City(country_id=kz.id, name="Алматы"), City(country_id=kz.id, name="Астана")])
    db.add_all([
        Niche(name="Рестораны"), Niche(name="Строительство и ремонт"),
        Niche(name="Агентства недвижимости"), Niche(name="Барбершопы"),
        Niche(name="Монтажные и инженерные компании"), Niche(name="Поставщики оборудования"),
        Niche(name="Курсы и учебные центры"),
    ])
    db.add_all([
        Service(name="Одностраничный сайт по КП"), Service(name="Разработка сайта с нуля"),
        Service(name="Доработка и редизайн"), Service(name="Упаковка и переупаковка"),
        Service(name="Индивидуальный веб-дизайн"), Service(name="Макеты страниц и баннеры"),
    ])
    db.commit(); db.close()
    return engine, S