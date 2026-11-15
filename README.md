# AI BUSINESS SYSTEMS DENMARK — CRM
CRM для веб-дизайн-студии: компании, контакты, КП, сделки, задачи, отчёт.
## Стек
- Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic v2
- PostgreSQL 16
- JWT (httpOnly cookie), роли manager/supervisor
- Jinja2 + Alpine.js, тёмная/светлая тема, адаптив до телефона
## Запуск локально
1. PostgreSQL 16, создать БД:
   CREATE USER crm WITH PASSWORD 'crm';
   CREATE DATABASE crm OWNER crm;
   GRANT ALL PRIVILEGES ON DATABASE crm TO crm;
2. Скопировать .env.example → .env, проверить DATABASE_URL=postgresql+psycopg://crm:crm@localhost:5432/crm
3. Установить зависимости:
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
4. Миграции и сиды:
   alembic upgrade head
   python -m app.seed
5. Запуск:
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
## Запуск через Docker
docker compose up --build
## Тесты
pytest -q tests/test_e2e.py tests/test_acceptance.py
# Ожидаемо: 16 passed
## Учётные записи
После python -m tests.seed_test_data:
- supervisor: user0@crm.local / pass123
- менеджеры: user1@crm.local ... user99@crm.local / pass123
## Экраны
/login, /register, /tasks, /companies, /companies/{id}, /pipeline, /deals/{id}, /reports, /admin, /imports, /settings, /profile
## PENDING_DECISION
Настраиваются в /settings (supervisor):
- SALE_CONFIRMATION_CRITERION (пусто = продажа заблокирована, 409)
- BELARUS_CHECK_REQUIRED_BEFORE / BELARUS_CHECKER_ROLE
## Что отложено (v2)
- Добавление/архивирование справочников через UI (сейчас read-only в /settings)
- Оптимистичная блокировка (409 при конкурентном изменении)
- Column mapping в импорте (фиксированный формат: name, country, city, website_url)
- Кликабельные KPI в отчёте
