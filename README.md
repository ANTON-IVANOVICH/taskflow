# TaskFlow

TaskFlow — backend-платформа на FastAPI для управления задачами, командами, фоновыми процессами и внешними интеграциями.

## Возможности

- CRUD и импорт задач из внешних трекеров (`jira`, `trello`, `asana`, `linear`, `clickup`, `github`).
- Команды, статусы, приоритеты, теги, исполнители и CSV-экспорт.
- JWT access/refresh-сессии, HttpOnly cookie, CSRF, OAuth2 Google/GitHub и M2M API keys.
- SQLAlchemy 2 async, Alembic, Repository + Unit of Work, SQLite/PostgreSQL.
- Redis, MongoDB и Meilisearch как подключаемые инфраструктурные сервисы.
- Eager-задачи без Redis или ARQ-воркер с Redis; transactional outbox и real-time WebSocket.
- Presigned file upload/download для local storage и S3/MinIO.
- Подписанные inbound/outbound webhooks с дедупликацией и асинхронной обработкой.
- Provider-agnostic email adapter, Stripe Checkout и потоковый LLM API через SSE.

## Быстрый запуск

Требуется Python 3.11 или новее.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

По умолчанию используется `sqlite+aiosqlite:///./taskflow.db`. При старте приложение также выполняет безопасную инициализацию схемы для локальной разработки и тестов; в deployment-среде применяйте Alembic явно.

Для S3/MinIO:

```bash
python -m pip install -e '.[dev,s3]'
```

При заданном `REDIS_URL` приложение подключает Redis и пытается использовать ARQ. Без доступного Redis фоновые задачи выполняются eager-вариантом внутри процесса.

ARQ-воркер запускается отдельно:

```bash
arq app.workers.settings.WorkerSettings
```

## Миграции

```bash
alembic upgrade head
alembic current
alembic history
```

Текущая цепочка миграций:

- `20260526_0001_core_schema.py` — базовая схема задач, команд и событий;
- `20260610_0002_async_outbox.py` — transactional outbox;
- `20260701_0003_webhook_delivery.py` — inbound events и outbound delivery records;
- `20260711_0004_stripe_payments.py` — локальные записи Stripe Checkout-платежей.

## Конфигурация

Полный шаблон находится в [`.env.example`](.env.example). Основные группы настроек:

- База и поиск: `DATABASE_URL`, `POSTGRES_DSN`, `REDIS_URL`, `MONGO_URL`, `MEILISEARCH_URL`.
- Auth/security: `JWT_*`, `CSRF_*`, `MACHINE_API_KEYS`, `RATE_LIMIT_*`, `OAUTH_*`.
- Worker/runtime: `WORKER_*`, `SCHEDULER_ENABLED`, `OUTBOX_RELAY_*`, `WS_*`.
- HTTP resilience: `HTTP_*`, `CIRCUIT_BREAKER_*`.
- Files: `STORAGE_*`, `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`.
- Webhooks: `WEBHOOK_SIGNING_SECRETS`, `WEBHOOK_SIGNATURE_HEADER`, `WEBHOOK_ID_HEADER`, `WEBHOOK_TOLERANCE_SECONDS`.
- Email: `EMAIL_PROVIDER`, `EMAIL_PROVIDER_BASE_URL`, `EMAIL_API_KEY`, `EMAIL_FROM`.
- Stripe: `STRIPE_API_KEY`, `STRIPE_BASE_URL`; webhook secret задаётся в `WEBHOOK_SIGNING_SECRETS` как `stripe=<secret>`.
- LLM: `ANTHROPIC_API_KEY`, `ANTHROPIC_BASE_URL`, `ANTHROPIC_MODEL`, `LLM_*`.

Формат `MACHINE_API_KEYS`:

```text
key=sc1,sc2;another-key=sc1
```

Локальный development key из `.env.example` — `local-dev-key`.

Если email-провайдер не настроен, welcome-email job завершается со статусом `skipped`. Если `ANTHROPIC_API_KEY` не задан, LLM endpoint возвращает детерминированный offline fallback. Stripe Checkout требует настроенный `STRIPE_API_KEY`.

## Порядок подсистем

Подсистемы описаны снизу вверх: сначала базовые безопасность и данные, затем runtime и только после них внешние интеграции.

### Security

- JWT access/refresh tokens с issuer и audience validation.
- Refresh token хранится в HttpOnly cookie и привязан к `User-Agent` и `X-Device-Id`.
- CSRF-защита для cookie refresh flow.
- M2M API keys, scopes, rate limiting и security headers.
- OAuth2 Authorization Code flow для Google и GitHub.

### Data

- SQLAlchemy 2 async с SQLite или PostgreSQL.
- Alembic для версионирования схемы.
- Repository + Unit of Work для бизнес-операций.
- Redis для очередей/realtime, MongoDB для event log и Meilisearch с SQL fallback.

### Async/runtime

- Eager task queue без Redis или ARQ при доступном Redis.
- Отчёты, welcome email, webhook processing и delivery выполняются как jobs.
- Transactional outbox работает по at-least-once модели.
- APScheduler запускает периодические задачи при включённом Redis.
- WebSocket task rooms и SSE для событий задач, job progress и LLM output.

### External integrations

- Shared long-lived `httpx` client с timeout, retry с jitter, `Retry-After` и circuit breaker.
- Local HMAC storage или S3/MinIO presigned URLs.
- Signed inbound/outbound webhooks с deduplication и delivery history.
- Email adapter, Stripe Checkout с idempotency и Anthropic LLM streaming.

## Аутентификация и scopes

Основные scopes:

- `tasks:read` — чтение задач и файлов;
- `tasks:write` — создание/изменение задач и presigned upload;
- `teams:read` — чтение команд;
- `integrations:write` — импорт из провайдеров и Stripe Checkout;
- `admin` — административные действия и outbound webhook test.

Получить токен:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/users/token \
  -d 'username=admin@taskflow.dev' \
  -d 'password=admin12345' \
  -d 'scope=tasks:read tasks:write integrations:write admin'
```

Для M2M-маршрутов используйте `X-API-Key: local-dev-key`. Маршруты команд дополнительно требуют API key.

## API

### Users и auth

- `POST /api/v1/users/register` — регистрация и постановка welcome email в очередь.
- `POST /api/v1/users/token` — выдача access/refresh token и cookie-сессии.
- `GET /api/v1/users/me` — текущий пользователь.
- `POST /api/v1/auth/refresh` — refresh по cookie, `User-Agent`, `X-Device-Id` и CSRF.
- `GET /api/v1/auth/oauth/{provider}/login` — Google/GitHub authorize URL.
- `GET /api/v1/auth/oauth/{provider}/callback` — OAuth callback.

### Tasks и teams

- `GET /api/v1/tasks/` — список с фильтрами и поиском.
- `POST /api/v1/tasks/` — создание задачи.
- `GET /api/v1/tasks/{task_id}` и `PUT /api/v1/tasks/{task_id}` — чтение/изменение.
- `POST /api/v1/tasks/import` — batch import с обёрткой `payload`.
- `POST /api/v1/integrations/{provider}/tasks` — provider-specific import.
- `GET /api/v1/tasks/export.csv` — экспорт с фильтрами.
- `POST /api/v1/tasks/description/preview` — markdown/HTML preview.
- `POST /api/v1/tasks/{task_id}/attachments` и `GET /api/v1/tasks/{task_id}/attachments/{attachment_id}` — task attachments.
- `GET /api/v1/tasks/{task_id}/events/stream` — SSE task events.
- `GET /api/v1/tasks/dashboard` — параллельный dashboard aggregate.
- `GET/POST /api/v1/teams/` — команды; требуется API key и соответствующий scope.

### Background jobs и realtime

- `POST /api/v1/jobs/reports` — enqueue отчёта.
- `GET /api/v1/jobs/{job_id}` — статус и результат.
- `GET /api/v1/jobs/{job_id}/events` — SSE прогресса.
- `POST /api/v1/jobs/outbox/relay` — relay outbox, только `admin`.
- `GET /api/v1/system/worker-metrics` — метрики очереди, WebSocket и outbox.
- `WS /api/v1/ws/tasks/{task_id}?token=<access_token>` — task room, ping/pong и broadcast.

### Files

- `POST /api/v1/files/presigned-upload` — получить HMAC token для local storage или реальный S3 presigned PUT URL; требуется `tasks:write`.
- `PUT /api/v1/files/upload/{token}` — local upload без bearer token, где сам token является credential.
- `POST /api/v1/files/confirm` — подтвердить загрузку.
- `GET /api/v1/files/download?key=...` — скачать файл или получить redirect на S3 URL.

Ключи файлов привязаны к пользователю: администратор может читать любые, обычный пользователь — только свои `uploads/{user_id}/...`.

### Webhooks

- `POST /api/v1/webhooks/{provider}` — принять подписанный webhook, проверить raw body, дедуплицировать, сохранить и enqueue обработку. Поддерживаются Stripe (`Stripe-Signature`), GitHub (`X-Hub-Signature-256`) и generic (`X-Webhook-Signature`).
- `POST /api/v1/webhooks/deliver/test` — admin-only outbound delivery с HMAC-подписью, retry policy и записью результата.

Stripe-события `checkout.session.completed`, `payment_intent.succeeded`, `payment_intent.payment_failed`, `checkout.session.expired` и `charge.refunded` обновляют локальный payment status.

### LLM и payments

- `POST /api/v1/llm/chat/stream` — SSE streaming Anthropic Messages API; требуется `tasks:read`.
- `POST /api/v1/payments/checkout` — idempotent Stripe Checkout Session; требуется `integrations:write`.
- `GET /api/v1/payments/{payment_id}` — локальный payment status владельца или администратора.

Для Stripe Checkout передавайте сумму в минимальных единицах валюты, например `1999` для `$19.99`. Повторный запрос с тем же `idempotency_key` не создаёт новую локальную запись.

### System и documentation

- `GET /api/v1/system/health` — liveness.
- `GET /api/v1/system/ready` — readiness.
- `/docs` — Swagger UI.
- `/redoc` — ReDoc.
- `/scalar` — Scalar.
- `/stoplight` — Stoplight Elements.
- `/admin/docs` и `/admin/openapi.json` — admin sub-application.

## Postman

Актуальная коллекция находится в [`postman/TaskFlow.postman_collection.json`](postman/TaskFlow.postman_collection.json).

Рекомендуемый порядок:

1. `00. Bootstrap` — register и issue admin token;
2. `01–07` — auth, tasks, teams, system, docs, jobs и realtime;
3. `08. External Integrations` — files, webhooks, LLM и Stripe.

Postman-переменные автоматически сохраняют access token, file upload URL/key, webhook signature и payment id. Реальные Stripe/email/S3 сценарии требуют соответствующих переменных окружения; LLM без ключа работает через offline fallback.

## Проверки

```bash
python -m pytest -q
ruff check app tests alembic
git diff --check
```

Тесты разделены по предметной области:

- `tests/test_app.py` — базовые API/auth/task flows;
- `tests/test_background_jobs.py` — jobs, outbox, WebSocket и concurrency;
- `tests/test_integrations.py` — HTTP resilience, email, files, webhooks, LLM и Stripe.
