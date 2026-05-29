# TaskFlow

TaskFlow — backend-платформа для управления задачами, командами и интеграциями с внешними трекерами.

## Что

- Единый API для жизненного цикла задач: создание, обновление, импорт, вложения, экспорт, real-time события.
- Поддержка командной работы: задачи привязаны к командам, статусам, приоритетам, тегам и исполнителям.
- Интеграционный слой: импорт задач из внешних систем (`jira`, `trello`, `asana`, `linear`, `clickup`, `github`).
- Слой безопасности уровня production: JWT, refresh в cookie, CSRF, API keys для M2M, rate limiting, secure headers.
- Слой данных уровня production: SQLAlchemy 2.0 async, Alembic миграции, Repository + Unit of Work, multi-DB адаптеры (PostgreSQL/Redis/Mongo), полнотекстовый поиск с Meilisearch fallback.

## Зачем

- Снизить потери контекста между инструментами и собрать управление задачами в одном контуре.
- Ускорить операционные процессы: массовый импорт, быстрый экспорт отчётов, live-обновления.
- Повысить безопасность пользовательских сессий (refresh через cookie с привязкой к устройству).

## Почему так

- Разделение API по доменам (`auth`, `users`, `tasks`, `integrations`, `teams`, `system`) упрощает масштабирование.
- Импорт вынесен в два паттерна:
  - `POST /api/v1/tasks/import` для универсального сценария.
  - `POST /api/v1/integrations/{provider}/tasks` для провайдер-специфичных потоков.
- SSE-стрим по задаче позволяет UI получать изменения без постоянного polling.
- Контракт ошибок, middleware и OpenAPI обеспечивают предсказуемую интеграцию клиентов.

## Бизнес-флоу

1. Аутентификация и сессия

- `POST /api/v1/users/token` выдаёт access/refresh и ставит `HttpOnly` refresh cookie.
- `POST /api/v1/auth/refresh` обновляет токены по cookie + `User-Agent` + `X-Device-Id` + CSRF header.
- `GET /api/v1/auth/oauth/{provider}/login` формирует authorize URL для внешнего OAuth2.
- `GET /api/v1/auth/oauth/{provider}/callback` обменивает `code` на provider token и выпускает сессию TaskFlow.

2. Работа с задачами

- Создание/обновление задачи, фильтрация списков, экспорт CSV по фильтрам команды/статуса/исполнителя.
- Получение live-событий задачи через SSE.

3. Импорт из внешних систем

- Batch импорт через wrapped `payload`.
- Импорт через provider endpoint для прозрачной интеграции по источнику.

4. Контент и артефакты

- Предпросмотр описания задачи (`markdown`/`html`) для UI-редактора.
- Загрузка и скачивание вложений по задаче.

5. Данные и поиск

- Операции по задачам/командам идут через Repository + Unit of Work поверх SQLAlchemy async.
- Схема БД ведётся через Alembic (`alembic/` + `alembic.ini`).
- Поиск задач использует Meilisearch при наличии `MEILISEARCH_URL`; при недоступности автоматически работает SQL fallback (`ILIKE`).
- Redis используется как быстрый буфер task events, MongoDB — как event log storage (если подключены).

## Security-конфиг (Layer 2)

- JWT: `JWT_SECRET_KEY`, `JWT_ISSUER`, `JWT_AUDIENCE`, `ACCESS_TOKEN_TTL_SECONDS`, `REFRESH_TOKEN_TTL_SECONDS`.
- CSRF и refresh-cookie: `CSRF_ENABLED`, `REFRESH_COOKIE_NAME`, `CSRF_COOKIE_NAME`, `CSRF_HEADER_NAME`.
- M2M API keys: `MACHINE_API_KEYS` в формате `key=sc1,sc2;key2=sc1,sc2`.
- Rate limiting: `RATE_LIMIT_ENABLED`, `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_WINDOW_SECONDS`.
- OAuth провайдеры: `OAUTH_GOOGLE_CLIENT_ID`, `OAUTH_GOOGLE_CLIENT_SECRET`, `OAUTH_GITHUB_CLIENT_ID`, `OAUTH_GITHUB_CLIENT_SECRET`, `OAUTH_STATE_TTL_SECONDS`.

## Data-конфиг (Layer 3)

- Основная БД: `POSTGRES_DSN` (приоритет), fallback: `DATABASE_URL` (локально можно `sqlite+aiosqlite`).
- SQLAlchemy engine: `DB_ECHO`, `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE_SECONDS`, `DB_POOL_PRE_PING`.
- Seed dev-данных: `DB_SEED_ENABLED`.
- Redis: `REDIS_URL`.
- MongoDB: `MONGO_URL`, `MONGO_DB_NAME`, `MONGO_EVENTS_COLLECTION`.
- Meilisearch: `MEILISEARCH_URL`, `MEILISEARCH_API_KEY`, `MEILISEARCH_INDEX`.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
uvicorn app.main:app --reload
```

Миграции:

```bash
alembic upgrade head
```

Если `authlib`/`slowapi` не установлены, OAuth login и limiter `slowapi` не активируются (используется fallback-limiter).

Документация:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- Scalar: `http://127.0.0.1:8000/scalar`
- Stoplight Elements: `http://127.0.0.1:8000/stoplight`
- Admin docs: `http://127.0.0.1:8000/admin/docs`

## Ключевые маршруты

- `GET /api/v1/tasks`
- `POST /api/v1/tasks/import` (batch import with wrapped `payload`)
- `POST /api/v1/integrations/{provider}/tasks` (provider-specific import)
- `PUT /api/v1/tasks/{task_id}`
- `POST /api/v1/users/register`
- `POST /api/v1/users/token`
- `POST /api/v1/auth/refresh` (refresh token from cookie + `User-Agent`/`X-Device-Id`)
- `GET /api/v1/auth/oauth/{provider}/login` (Google/GitHub authorize URL)
- `GET /api/v1/auth/oauth/{provider}/callback` (OAuth code exchange + TaskFlow session issue)
- `POST /api/v1/tasks/description/preview` (markdown/html preview for task description)
- `POST /api/v1/tasks/{task_id}/attachments` (task attachment upload)
- `GET /api/v1/tasks/{task_id}/attachments/{attachment_id}` (task attachment download)
- `GET /api/v1/tasks/export.csv?team_id=1&status=blocked&assignee=bob@taskflow.dev` (task report export)
- `GET /api/v1/tasks/{task_id}/events/stream?limit=20` (task events SSE)
