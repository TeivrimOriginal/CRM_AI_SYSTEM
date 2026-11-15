"""Работа со временем.

Правило проекта: в базе хранится **наивный UTC** (DateTime без tz), в интерфейсе
показывается время в часовом поясе пользователя. Все сравнения дат выполняются
только после приведения к UTC, иначе наивные и aware-значения несравнимы.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

UTC = timezone.utc


def utcnow() -> datetime:
    """Текущее время в UTC без tzinfo (формат хранения в БД)."""
    return datetime.now(UTC).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    """Привести любое datetime к наивному UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        # Считаем, что наивное значение уже в UTC (так его хранит БД).
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def to_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def tz_for(tz_name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name or settings.APP_TZ)
    except Exception:
        return ZoneInfo(settings.APP_TZ)


def localize(value: datetime | None, tz_name: str | None = None) -> datetime | None:
    """UTC-время из БД → aware-время в часовом поясе пользователя."""
    aware = to_aware_utc(value)
    if aware is None:
        return None
    return aware.astimezone(tz_for(tz_name))


def local_date(value: datetime | None, tz_name: str | None = None) -> date | None:
    localized = localize(value, tz_name)
    return localized.date() if localized else None


def today_for(tz_name: str | None = None) -> date:
    return datetime.now(tz_for(tz_name)).date()


def start_of_day(value: date, tz_name: str | None = None) -> datetime:
    """Начало календарного дня в поясе пользователя, выраженное в наивном UTC."""
    local = datetime.combine(value, time.min, tzinfo=tz_for(tz_name))
    return local.astimezone(UTC).replace(tzinfo=None)


def end_of_day(value: date, tz_name: str | None = None) -> datetime:
    return start_of_day(value + timedelta(days=1), tz_name) - timedelta(microseconds=1)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def parse_datetime(value: str | datetime | None) -> datetime | None:
    """Разобрать дату/время из формы и привести к наивному UTC."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return to_naive_utc(value)
    text = str(value).strip()
    try:
        return to_naive_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def local_input_value(value: datetime | None, tz_name: str | None = None) -> str:
    """Значение для <input type="datetime-local">."""
    localized = localize(value, tz_name)
    return localized.strftime("%Y-%m-%dT%H:%M") if localized else ""
