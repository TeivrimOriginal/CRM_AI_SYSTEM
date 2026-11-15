from datetime import timezone as _tz
from zoneinfo import ZoneInfo as _ZoneInfo
from fastapi import FastAPI
from app.config import settings
from app.routers import auth, companies, pages
from app.routers.companies import (
    router_deals, router_proposals, router_tasks, router_reports,
    router_imports, router_settings,
)
STAGE_RU = {
    "found": "Найдено",
    "verified": "Проверено",
    "dm_found": "ЛПР найден",
    "proposal_sent": "КП отправлено",
    "negotiation": "Переговоры",
    "terms_agreed": "Условия согласованы",
    "handed_over": "Заказ передан",
    "sale_confirmed": "Продажа подтверждена",
    "deferred": "Отложено",
    "lost": "Отказ",
}
ACTION_RU = {
    "call": "Звонок",
    "message": "Сообщение",
    "send_proposal": "Отправить КП",
    "clarify_terms": "Уточнить условия",
    "handoff": "Передать заказ",
    "other": "Другое",
}
TASK_STATE_RU = {
    "open": "Открыта",
    "done": "Выполнена",
    "cancelled": "Отменена",
}
PROPOSAL_STATE_RU = {
    "draft": "Черновик",
    "ready": "Готова",
    "sent": "Отправлена",
}
CHANNEL_RU = {
    "email": "Email",
    "telegram": "Telegram",
    "whatsapp": "WhatsApp",
    "call": "Звонок",
    "other": "Другое",
}
ACTIVITY_RU = {
    "call": "Звонок",
    "message": "Сообщение",
    "proposal_sent": "КП отправлено",
    "agreement": "Договорённость",
    "stage_change": "Смена стадии",
    "reassignment": "Переназначение",
    "handoff": "Передача заказа",
    "sale_confirmation": "Подтверждение продажи",
    "import": "Импорт",
    "export": "Экспорт",
}
MARKET_CHECK_RU = {
    "not_required": "Не требуется",
    "pending": "Ожидает",
    "passed": "Пройдена",
    "failed": "Не пройдена",
}

app = FastAPI(title="AI BUSINESS SYSTEMS DENMARK CRM", version="0.7.0")
app.include_router(auth.router)
app.include_router(companies.router)
app.include_router(router_deals)
app.include_router(router_proposals)
app.include_router(router_tasks)
app.include_router(router_reports)
app.include_router(router_imports)
app.include_router(router_settings)
app.include_router(pages.router)
def _make_localtime():
    def _localtime(value, tz_name: str = "Europe/Moscow"):
        if value is None:
            return "—"
        try:
            if value.tzinfo is None:
                value = value.replace(tzinfo=_tz.utc)
            return value.astimezone(_ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(value)
    return _localtime
@app.on_event("startup")
def _install_filters():
    from app.routers.pages import templates
    templates.env.filters["localtime"] = _make_localtime()
    templates.env.globals["STAGE_RU"] = STAGE_RU
    templates.env.globals["ACTION_RU"] = ACTION_RU
    templates.env.globals["TASK_STATE_RU"] = TASK_STATE_RU
    templates.env.globals["PROPOSAL_STATE_RU"] = PROPOSAL_STATE_RU
    templates.env.globals["CHANNEL_RU"] = CHANNEL_RU
    templates.env.globals["ACTIVITY_RU"] = ACTIVITY_RU
    templates.env.globals["MARKET_CHECK_RU"] = MARKET_CHECK_RU
@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok", "sale_confirmation_criterion": settings.SALE_CONFIRMATION_CRITERION or None}
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
