# Сценарии работы

Документ описывает проверяемые пользовательские и интеграционные flows. Все URL приведены для локального запуска: `http://127.0.0.1:8000`.

## 1. Первый запуск

Предусловия: установлен Python 3.11+, создан `.env`.

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
alembic upgrade head
uvicorn app.main:app --reload
```

Ожидаемый результат:

- `GET /api/v1/system/health` возвращает `{"status":"ok"}`;
- `GET /api/v1/system/ready` возвращает `{"status":"ready"}`;
- Swagger доступен на `/docs`.

## 2. Регистрация и сессия

1. Вызвать `POST /api/v1/users/register` с `email`, `name`, `password`.
2. Приложение ставит welcome email в очередь.
3. Вызвать `POST /api/v1/users/token` с OAuth2 form fields `username`, `password`, `scope`.
4. Сохранить `access_token`, refresh cookie и CSRF cookie.
5. Вызвать `GET /api/v1/users/me` с `Authorization: Bearer <access_token>`.
6. Для refresh отправить `POST /api/v1/auth/refresh` с refresh cookie, `User-Agent`, `X-Device-Id` и CSRF header.

Проверки ошибок:

- неверный пароль даёт `401`;
- scope, которого нет у пользователя, даёт `403`;
- refresh с другим device id или без CSRF даёт `401`.

## 3. Работа с задачами и командами

1. Получить задачи: `GET /api/v1/tasks/?limit=20&offset=0` со scope `tasks:read`.
2. Создать задачу через `POST /api/v1/tasks/?team_id=1` со scope `tasks:write`.
3. Изменить её через `PUT /api/v1/tasks/{task_id}`.
4. Проверить события через `GET /api/v1/tasks/{task_id}/events/stream`.
5. Получить CSV через `GET /api/v1/tasks/export.csv`.
6. Для команды передать одновременно bearer token и `X-API-Key: local-dev-key`.

Импорт поддерживает два одинаковых по смыслу контракта:

- `POST /api/v1/tasks/import?team_id=1` с `{ "provider": "jira", "payload": [...] }`;
- `POST /api/v1/integrations/trello/tasks?team_id=1` с `{ "payload": [...] }`.

## 4. Фоновые задачи

1. Вызвать `POST /api/v1/jobs/reports` со scope `tasks:write`.
2. Сохранить `job_id` из ответа `202`.
3. Опросить `GET /api/v1/jobs/{job_id}`.
4. Подключиться к `GET /api/v1/jobs/{job_id}/events` с `Accept: text/event-stream`.

Без Redis job выполняется eager и сразу получает `complete`. При доступном Redis запрос ставит задачу в ARQ; worker запускается командой:

```bash
arq app.workers.settings.WorkerSettings
```

Для outbox нужен `POST /api/v1/jobs/outbox/relay` со scope `admin`. Повторный relay не должен повторно публиковать уже обработанные записи.

## 5. Presigned files

Предусловие: access token со scope `tasks:write`.

1. Запросить upload URL:

```http
POST /api/v1/files/presigned-upload
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "filename": "report.txt",
  "content_type": "text/plain",
  "size": 28
}
```

2. Выполнить `PUT` на `upload_url` из ответа с указанным `Content-Type` и байтами файла.
3. Подтвердить объект через `POST /api/v1/files/confirm` с `key`.
4. Скачать через `GET /api/v1/files/download?key=...`.

В local backend upload URL ведёт в TaskFlow и содержит HMAC token. В S3 backend URL подписывается самим S3/MinIO. Content type, размер, срок действия и владелец проверяются до выдачи/приёма файла.

## 6. Inbound webhooks

1. Настроить secret в `WEBHOOK_SIGNING_SECRETS`, например:

```text
stripe=whsec_dev;github=ghsec_dev;generic=dev-webhook-secret
```

2. Подписать raw request body HMAC-SHA256.
3. Отправить `POST /api/v1/webhooks/generic` с `X-Webhook-Signature` и `X-Webhook-Id`.
4. Первый вызов возвращает `accepted`, повтор с тем же external id — `already_processed`.

Для Stripe используется `Stripe-Signature` с timestamp и `v1` digest. Для GitHub — `X-Hub-Signature-256`. Событие сохраняется до постановки job в очередь.

## 7. Outbound webhooks

Предусловие: scope `admin` и доступный destination URL.

Вызвать `POST /api/v1/webhooks/deliver/test`:

```json
{
  "destination": "http://127.0.0.1:9000/webhook",
  "event_type": "task.updated",
  "provider": "generic",
  "payload": {"task_id": 1, "status": "done"}
}
```

Job подписывает компактное JSON-тело, отправляет его через resilient HTTP client и сохраняет status code, attempts и success в `webhook_deliveries`.

## 8. LLM streaming

Вызвать `POST /api/v1/llm/chat/stream` со scope `tasks:read` и `Accept: text/event-stream`.

- При заданном `ANTHROPIC_API_KEY` поток проксирует Anthropic Messages API.
- Без ключа endpoint возвращает детерминированный offline fallback.
- Клиент должен обрабатывать `event: delta`, `event: done` и `event: error`.

## 9. Stripe Checkout

Предусловие: `STRIPE_API_KEY` и scope `integrations:write`.

1. Вызвать `POST /api/v1/payments/checkout` с amount в минимальных единицах валюты, currency, description, success/cancel URL и `idempotency_key`.
2. Сохранить `payment_id` и `checkout_url`.
3. Повторить запрос с тем же idempotency key — новая Stripe/local запись не создаётся.
4. После подписанного `checkout.session.completed` вызвать `GET /api/v1/payments/{payment_id}` и проверить статус `paid`.

Без Stripe key endpoint возвращает `503 integration_not_configured`; это ожидаемое поведение, а не offline payment simulation.

## 10. Postman flow

Коллекция находится в `postman/TaskFlow.postman_collection.json`.

1. `00. Bootstrap` — register и admin token;
2. `01–07` — auth, tasks, teams, system, docs, jobs, realtime;
3. `08. External Integrations` — files, webhooks, LLM, Stripe.

Коллекция сохраняет токены, file key/upload URL, webhook signature и payment id в collection variables.

## 11. Автоматическая проверка

```bash
python -m pytest -q
python -m pytest -q --cov=app --cov-report=term-missing
python -m pytest -q -m e2e
ruff check app tests alembic
git diff --check
```

Тестовые группы:

- `tests/test_app.py` — базовый API и auth;
- `tests/test_background_jobs.py` — jobs, outbox, WebSocket и concurrency;
- `tests/test_integrations.py` — resilience, email, files, webhooks, LLM и Stripe;
- `tests/integration/test_negative_paths.py` — негативные ответы API через `TestClient` и `httpx.AsyncClient`.
- `tests/e2e/test_task_journey.py` — полный пользовательский путь регистрации и работы с задачей.
- `tests/factories/` — Factory Boy/Faker-фабрики валидных payloads.

Mutation testing:

```bash
docker build -f docker/mutation.Dockerfile -t taskflow-mutation .
docker run --rm taskflow-mutation
```

Mutation job запускается в Linux-контейнере через GitHub Actions. Временный `mutants/` существует только внутри контейнера и не попадает в рабочее дерево.

## 12. Integration tests с контейнерами

Docker-backed проверки PostgreSQL и Redis не запускаются обычным `pytest` и не требуют Docker для локальной разработки.

Установка и запуск:

```bash
python -m pip install -e '.[dev,containers]'
RUN_CONTAINERS=1 python -m pytest -m slow
```

Тесты создают временные PostgreSQL и Redis containers, применяют Alembic до `head`, проверяют репозиторий через `asyncpg`/SQLAlchemy и Redis через `redis.asyncio`, а затем удаляют containers через fixture cleanup. Для PostgreSQL каждый тест получает отдельную транзакцию и откатывает её после завершения.

В GitHub Actions этот набор выполняется отдельным `container-tests` job; основной `application-tests` job не требует Docker.
