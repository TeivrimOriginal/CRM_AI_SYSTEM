from enum import Enum


class Role(str, Enum):
    MANAGER = "manager"
    SUPERVISOR = "supervisor"


class DealStage(str, Enum):
    FOUND = "found"
    VERIFIED = "verified"
    DM_FOUND = "dm_found"
    PROPOSAL_SENT = "proposal_sent"
    NEGOTIATION = "negotiation"
    TERMS_AGREED = "terms_agreed"
    HANDED_OVER = "handed_over"
    SALE_CONFIRMED = "sale_confirmed"
    DEFERRED = "deferred"
    LOST = "lost"


class ProposalState(str, Enum):
    DRAFT = "draft"
    READY = "ready"
    SENT = "sent"


class TaskActionType(str, Enum):
    CALL = "call"
    MESSAGE = "message"
    SEND_PROPOSAL = "send_proposal"
    CLARIFY_TERMS = "clarify_terms"
    HANDOFF = "handoff"
    OTHER = "other"


class TaskState(str, Enum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class ActivityType(str, Enum):
    CALL = "call"
    MESSAGE = "message"
    NOTE = "note"
    PROPOSAL_SENT = "proposal_sent"
    AGREEMENT = "agreement"
    STAGE_CHANGE = "stage_change"
    REASSIGNMENT = "reassignment"
    HANDOFF = "handoff"
    SALE_CONFIRMATION = "sale_confirmation"
    IMPORT = "import"
    EXPORT = "export"


class MarketCheckStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class PreferredChannel(str, Enum):
    EMAIL = "email"
    PHONE = "phone"
    MESSENGER = "messenger"
    OTHER = "other"


class ImportKind(str, Enum):
    IMPORT = "import"
    EXPORT = "export"


class ImportRowStatus(str, Enum):
    OK = "ok"
    DUP = "dup"
    ERROR = "error"


# ===== Русские подписи (интерфейс полностью на русском) =====
ROLE_LABELS = {Role.MANAGER: "Менеджер", Role.SUPERVISOR: "Руководитель"}

STAGE_LABELS = {
    DealStage.FOUND: "Найдено",
    DealStage.VERIFIED: "Проверено",
    DealStage.DM_FOUND: "ЛПР найден",
    DealStage.PROPOSAL_SENT: "КП отправлено",
    DealStage.NEGOTIATION: "Переговоры",
    DealStage.TERMS_AGREED: "Условия согласованы",
    DealStage.HANDED_OVER: "Заказ передан",
    DealStage.SALE_CONFIRMED: "Продажа подтверждена",
    DealStage.DEFERRED: "Отложено",
    DealStage.LOST: "Отказ",
}

STAGE_ORDER = [
    DealStage.FOUND,
    DealStage.VERIFIED,
    DealStage.DM_FOUND,
    DealStage.PROPOSAL_SENT,
    DealStage.NEGOTIATION,
    DealStage.TERMS_AGREED,
    DealStage.HANDED_OVER,
    DealStage.SALE_CONFIRMED,
    DealStage.DEFERRED,
    DealStage.LOST,
]

# Этапы, которые считаются «в работе» (активная воронка).
ACTIVE_STAGES = [s for s in STAGE_ORDER if s not in (DealStage.LOST, DealStage.SALE_CONFIRMED)]

PROPOSAL_STATE_LABELS = {
    ProposalState.DRAFT: "Черновик",
    ProposalState.READY: "Готово",
    ProposalState.SENT: "Отправлено",
}

TASK_ACTION_LABELS = {
    TaskActionType.CALL: "Звонок",
    TaskActionType.MESSAGE: "Сообщение",
    TaskActionType.SEND_PROPOSAL: "Отправить КП",
    TaskActionType.CLARIFY_TERMS: "Уточнить условия",
    TaskActionType.HANDOFF: "Передать заказ",
    TaskActionType.OTHER: "Другое",
}

TASK_STATE_LABELS = {
    TaskState.OPEN: "Открыта",
    TaskState.DONE: "Выполнена",
    TaskState.CANCELLED: "Отменена",
}

ACTIVITY_LABELS = {
    ActivityType.CALL: "Звонок",
    ActivityType.MESSAGE: "Сообщение",
    ActivityType.NOTE: "Заметка",
    ActivityType.PROPOSAL_SENT: "Отправка КП",
    ActivityType.AGREEMENT: "Договорённость",
    ActivityType.STAGE_CHANGE: "Смена этапа",
    ActivityType.REASSIGNMENT: "Переназначение",
    ActivityType.HANDOFF: "Передача заказа",
    ActivityType.SALE_CONFIRMATION: "Подтверждение продажи",
}

MARKET_CHECK_LABELS = {
    MarketCheckStatus.NOT_REQUIRED: "Не требуется",
    MarketCheckStatus.PENDING: "Требуется проверка",
    MarketCheckStatus.PASSED: "Проверено",
    MarketCheckStatus.FAILED: "Не пройдено",
}


def label(mapping: dict, value) -> str:
    """Подпись по значению enum/строке; неизвестное значение — «Не указано»."""
    for key, text in mapping.items():
        if getattr(key, "value", key) == value:
            return text
    return "Не указано"
