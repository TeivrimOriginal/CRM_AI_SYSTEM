@"
# CRM — AI BUSINESS SYSTEMS DENMARK

CRM для веб-дизайн-студии: компании, контакты, КП, сделки, задачи, воронка, отчёт.

## 🚀 Запуск через Docker (рекомендуется)

`docker compose up --build`

Открой http://localhost:8000/login

## 🐍 Запуск без Docker (локально)

1. PostgreSQL 16, создай БД:
   CREATE USER crm WITH PASSWORD 'crm';
   CREATE DATABASE crm OWNER crm;
2. `copy .env.example .env` → проверь `DATABASE_URL=...@localhost:5432/crm`
3. `python -m venv .venv` → `.\.venv\Scripts\Activate.ps1`
4. `pip install -r requirements.txt`
5. `alembic upgrade head` → `python -m app.seed`
6. `uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## 🔑 Вход

- supervisor: `user0@crm.local` / `pass123`
- менеджеры: `user1@crm.local` ... `user99@crm.local` / `pass123`

(после `python -m tests.seed_test_data`, опционально)

## ✅ Что сделано по ТЗ

**Модель данных** — 14 таблиц (User, Country, City, Niche, Service, Company, Contact, Deal, Proposal, Task, Activity, Handoff, Journal, AppSetting), поля, FK, UNIQUE-ограничения.

**Справочники** — 5 стран (Казахстан, Узбекистан, Армения, Кыргызстан, Беларусь с флагом market_check), 7 ниш, 6 услуг. Россия исключена. Архивные скрыты из списков, сохраняются в карточках.

**Auth + роли** — JWT в httpOnly cookie, регистрация (первый = supervisor), профиль, TZ, смена пароля. Manager видит только свои записи, supervisor — всё. Прямые ссылки проверяются на сервере (403/404).

**Компании + контакты** — CRUD, поиск по name/domain, фильтры (страна, город, ниша, менеджер), карточка с контактами/сделками/историей, доступ через назначенную сделку, переназначение, архив/восстановление.

**Воронка** — 8 стадий (found → verified → dm_found → proposal_sent → negotiation → terms_agreed → handed_over → sale_confirmed) + deferred/lost. Серверная валидация переходов (422 с полями), откат supervisor с причиной, previous_working_stage.

**КП** — версии (draft → ready → sent), отправка атомарно со сменой стадии, идемпотентность, валидация link/contact/channel, запрет при do_not_contact.

**Задачи** — «Мои задачи» (Сегодня / Просрочено / Предстоящие / Без шага), «Выполнено», «Перенести».

**Handoff** — UNIQUE(deal_id), отдельно от продажи, актуальная версия КП, recipient, материалы.

**Подтверждение продажи** — блокировка по `SALE_CONFIRMATION_CRITERION` (409, если пусто), идемпотентность.

**Импорт CSV/XLSX** — preview + commit, дубли (по домену и name+country), отчёт по строкам, журнал.

**Экспорт CSV** — компании и сделки с фильтрами.

**Отчёт руководителя** — воронка, нагрузка, КП (версии + уникальные сделки), handoff, продажи, суммы по валютам, причины отказов, проверенные компании, найденные ЛПР.

**DNC («Не связываться»)** — сервер (409 в create_task/send_proposal) + баннеры и disabled-кнопки в карточках.

**Тема** — тёмная/светлая, сайдбар, адаптив до телефона. Время UTC → TZ пользователя.

**Тесты** — `pytest -q tests/test_e2e.py tests/test_acceptance.py` → **16 passed** (8 сценариев приёмки ТЗ стр. 10 + 8 e2e).

## ⚙️ PENDING_DECISION

В `/settings` (supervisor):
- `SALE_CONFIRMATION_CRITERION` — пусто = продажа заблокирована
- `BELARUS_CHECK_REQUIRED_BEFORE` / `BELARUS_CHECKER_ROLE`

## 📦 Отложено (v2)

- Добавление/архивирование справочников через UI
- Оптимистичная блокировка (409 при конкурентном изменении)
- Column mapping в импорте
- Кликабельные KPI в отчёте
"@ | Set-Content README.md -Encoding UTF8
Write-Host "OK: README.md перезаписан"
