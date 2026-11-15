"""Idempotent seed of directories and settings. Users не создаются — регистрация через /register.
Run: python -m app.seed
"""
from datetime import datetime
from sqlalchemy import select
from app.config import settings
from app.database import SessionLocal
from app.models import AppSetting, City, Country, Niche, Service
COUNTRIES = [
    ("Казахстан", ["Алматы", "Астана"], False),
    ("Узбекистан", ["Ташкент"], False),
    ("Армения", ["Ереван"], False),
    ("Кыргызстан", ["Бишкек"], False),
    ("Беларусь", [], True),
]
NICHES = [
    ("Рестораны", "Кафе, рестораны, доставка, кофейни"),
    ("Строительство и ремонт", "Строительные и ремонтные компании, подрядчики"),
    ("Агентства недвижимости", "Риелторы, агентства, застройщики"),
    ("Барбершопы", "Барбершопы, салоны мужского ухода"),
    ("Монтажные и инженерные компании", "Инженерные сети, монтаж оборудования"),
    ("Поставщики оборудования", "B2B-поставщики, дистрибьюторы"),
    ("Курсы и учебные центры", "Онлайн и офлайн обучение, учебные центры"),
]
SERVICES = [
    "Одностраничный сайт по утверждённому КП",
    "Разработка сайта с нуля",
    "Доработка и редизайн существующего сайта",
    "Упаковка и переупаковка сайта",
    "Индивидуальный веб-дизайн",
    "Макеты страниц и баннеры",
]
SETTINGS_DEFAULTS = {
    "SALE_CONFIRMATION_CRITERION": settings.SALE_CONFIRMATION_CRITERION,
    "BELARUS_CHECK_REQUIRED_BEFORE": settings.BELARUS_CHECK_REQUIRED_BEFORE,
    "BELARUS_CHECKER_ROLE": settings.BELARUS_CHECKER_ROLE,
}
def seed() -> None:
    db = SessionLocal()
    try:
        for name, cities, market in COUNTRIES:
            country = db.scalar(select(Country).where(Country.name == name))
            if country is None:
                country = Country(name=name, market_check_required=market)
                db.add(country)
                db.flush()
            else:
                if market and not country.market_check_required:
                    country.market_check_required = True
            for c in cities:
                exists = db.scalar(select(City).where(City.country_id == country.id, City.name == c))
                if not exists:
                    db.add(City(country_id=country.id, name=c))
        for name, desc in NICHES:
            if not db.scalar(select(Niche).where(Niche.name == name)):
                db.add(Niche(name=name, description=desc))
        for name in SERVICES:
            if not db.scalar(select(Service).where(Service.name == name)):
                db.add(Service(name=name))
        for key, default in SETTINGS_DEFAULTS.items():
            if not db.get(AppSetting, key):
                db.add(AppSetting(key=key, value=default or ""))
        db.commit()
        print("Seed complete:", datetime.utcnow().isoformat())
    finally:
        db.close()
if __name__ == "__main__":
    seed()
