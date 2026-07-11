# Changelog по слоям

Документ фиксирует функциональность TaskFlow по архитектурным слоям, а не по истории Git-коммитов.

## Security

Статус: реализовано.

- JWT access/refresh tokens с issuer и audience validation.
- Refresh-сессии в HttpOnly cookie.
- Привязка refresh к `User-Agent` и `X-Device-Id`.
- CSRF-защита cookie refresh flow.
- OAuth2 Authorization Code flow для Google и GitHub.
- M2M API keys и scopes: `tasks:read`, `tasks:write`, `teams:read`, `integrations:write`, `admin`.
- Rate limiting, request id, access log и secure headers.
- Единый JSON error contract с `request_id`.

## Data

Статус: реализовано.

- SQLAlchemy 2 async с SQLite/PostgreSQL.
- Alembic migrations:
  - `20260526_0001_core_schema.py`;
  - `20260610_0002_async_outbox.py`;
  - `20260701_0003_webhook_delivery.py`;
  - `20260711_0004_stripe_payments.py`.
- Repository + Unit of Work.
- Задачи, команды, task events и attachments.
- Search через Meilisearch с SQL fallback.
- Redis client для queue/realtime и MongoDB event log как подключаемые adapters.

## Async/runtime

Статус: реализовано.

- Eager `TaskQueue` без Redis.
- ARQ + Redis для отдельного worker process.
- Jobs для отчётов, outbox relay, welcome email, webhook processing и outbound delivery.
- Progress records и SSE job events.
- Transactional outbox с at-least-once relay.
- APScheduler для периодических задач при наличии Redis.
- WebSocket task rooms, ping/pong, broadcast и Redis Pub/Sub между инстансами.
- `asyncio.gather` для независимых aggregate operations и worker thread для CPU-bound обработки.

## External integrations

Статус: реализовано локально и через mock transports; реальные providers требуют credentials.

- Shared long-lived `httpx.AsyncClient`.
- Timeout по connect/read/write/pool.
- Retry с jitter, `Retry-After` и circuit breaker.
- Повтор небезопасного POST только при `Idempotency-Key`.
- Local HMAC file storage.
- S3/MinIO storage с presigned upload/download URLs.
- Signed inbound webhooks для Stripe, GitHub и generic providers.
- Webhook deduplication, async processing и delivery history.
- Provider-agnostic email adapter с явным `skipped` режимом без настроек.
- Stripe Checkout Session, local payment state и status transitions из webhook.
- Anthropic Messages SSE streaming, concurrency limit и offline fallback.

## API и документация

Статус: синхронизировано с текущим приложением.

- API routers для users/auth, tasks, teams, integrations, jobs, system, files, webhooks, LLM и payments.
- OpenAPI tags и documentation UI: Swagger, ReDoc, Scalar, Stoplight.
- Admin sub-application с отдельными `/admin/docs` и `/admin/openapi.json`.
- Postman collection с bootstrap, auth, tasks, jobs, realtime и external integration scenarios.
- `README.md`, `SCENARIOS.md` и `ARCHITECTURE.md` описывают текущие flows.

## Tests и качество

Статус: проверено.

- `tests/test_app.py` — базовые API/auth/task flows.
- `tests/test_background_jobs.py` — jobs, outbox, WebSocket и concurrency.
- `tests/test_integrations.py` — resilience, email, files, webhooks, LLM и Stripe.
- Полный pytest-набор: `49 passed`.
- Ruff и `git diff --check` проходят без ошибок.
- Alembic поднимает схему с нуля до текущего head.

## Оставшиеся ограничения

- Пользователи пока хранятся в in-memory service, а не в отдельной SQL-модели.
- Legacy task attachments хранят bytes в SQL и не мигрируются автоматически в object storage.
- Email adapter задаёт общий JSON contract; vendor-specific mapping зависит от gateway.
- Реальные Stripe, email и S3 flows требуют credentials и доступной сети.
- Mypy настроен в strict mode, но в старых модулях остаются type issues.
