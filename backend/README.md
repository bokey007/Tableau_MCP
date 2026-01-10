# Tableau MCP Backend

FastAPI backend for the Tableau MCP AI Agent platform.

## Features

- Natural language query processing using LangGraph and OpenAI
- MCP client for Tableau data integration
- Query history and feedback tracking
- Analytics and usage reporting
- PostgreSQL database with async SQLAlchemy

## Development

```bash
# Install dependencies
uv sync --all-extras

# Run development server
uv run uvicorn src.main:app --reload --port 8000

# Run tests
uv run pytest

# Run linting
uv run ruff check src tests
```

## API Endpoints

- `GET /api/v1/health` - Health check
- `POST /api/v1/query` - Natural language query
- `GET /api/v1/datasources` - List Tableau datasources
- `POST /api/v1/feedback` - Submit query feedback
- `GET /api/v1/analytics/dashboard` - Analytics dashboard
