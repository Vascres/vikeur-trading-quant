# Local Development

## Requirements

- Python 3.12
- Poetry
- Node.js 20
- Docker / Docker Compose
- PostgreSQL / TimescaleDB
- Redis

## Backend

```bash
cd backend
poetry install --no-interaction
```

Run the database migrations explicitly:

```bash
alembic upgrade head
```

Run backend checks:

```bash
pytest --cov=. --cov-report=term-missing --cov-fail-under=80
ruff check .
black --check .
lint-imports --config importlinter.ini
mypy .
```

## Frontend

```bash
cd frontend
npm ci
npm run lint
npm run type-check
npm run test
npm run build
```

## Docker

Create a local environment file from the example and fill it only with development credentials:

```bash
cp infra/.env.example infra/.env
cd infra
docker compose up -d
```

Do not commit the generated `.env` file.
