# 🎯 Tableau MCP AI Agent

An AI-powered platform for querying and analyzing Tableau data using natural language. Built with FastAPI, Streamlit, LangGraph, and PostgreSQL.

## ✨ Features

- **Natural Language Queries**: Ask questions about your Tableau data in plain English
- **AI-Powered Analysis**: Get automated insights and recommendations from GPT-4
- **Activity Tracking**: Full audit trail of queries, feedback, and usage
- **Like/Dislike Feedback**: Rate responses to improve the system
- **Analytics Dashboard**: Usage statistics and performance metrics
- **Multi-Datasource Support**: Query across multiple Tableau datasources

## 🏗️ Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Streamlit     │────▶│   FastAPI       │────▶│   Tableau MCP   │
│   Frontend      │     │   Backend       │     │   Server        │
│   (Port 8501)   │     │   (Port 8000)   │     │   (Port 3927)   │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                        ┌────────▼────────┐
                        │   PostgreSQL    │
                        │   Database      │
                        └─────────────────┘
```

## 📁 Project Structure

```
tableau-mcp-agent/
├── backend/                    # FastAPI Backend
│   ├── src/
│   │   ├── agent/              # LangGraph AI Agent
│   │   ├── api/routes/         # REST API endpoints
│   │   ├── core/               # Config, logging, exceptions
│   │   ├── db/                 # SQLAlchemy models & sessions
│   │   ├── mcp/                # MCP client
│   │   ├── services/           # Business logic services
│   │   └── main.py             # FastAPI application
│   ├── tests/                  # Pytest tests
│   ├── Dockerfile
│   └── pyproject.toml          # UV dependencies
├── frontend/                   # Streamlit Frontend
│   ├── app.py                  # Main application
│   ├── pages/                  # Multi-page app
│   ├── Dockerfile
│   └── pyproject.toml          # UV dependencies
├── k8s/                        # Kubernetes manifests
├── docker-compose.yml          # Development setup
├── docker-compose.prod.yml     # Production setup
└── Makefile
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- OpenAI API key
- Tableau Cloud/Server access with Personal Access Token (PAT)

### 1. Clone and Configure

```bash
cd tableau-mcp-agent

# Copy environment files
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Edit backend/.env with your credentials:
# - OPENAI_API_KEY
# - TABLEAU_SERVER, TABLEAU_SITE_NAME
# - TABLEAU_PAT_NAME, TABLEAU_PAT_VALUE
# - POSTGRES_PASSWORD
```

### 2. Start with Docker

```bash
# Start all services
docker-compose up --build

# Access the applications:
# - Streamlit UI: http://localhost:8501
# - API Docs: http://localhost:8000/docs
```

### 3. Local Development (Optional)

```bash
# Install UV if not installed
pip install uv

# Backend
cd backend
uv sync
uv run uvicorn src.main:app --reload --port 8000

# Frontend (in another terminal)
cd frontend
uv sync
uv run streamlit run app.py
```

## 📊 API Endpoints

| Endpoint                      | Method | Description                   |
| ----------------------------- | ------ | ----------------------------- |
| `/api/v1/query`               | POST   | Submit natural language query |
| `/api/v1/query/history`       | GET    | Get query history             |
| `/api/v1/query/{id}`          | GET    | Get specific query details    |
| `/api/v1/datasources`         | GET    | List available datasources    |
| `/api/v1/feedback`            | POST   | Submit like/dislike feedback  |
| `/api/v1/feedback/stats`      | GET    | Get feedback statistics       |
| `/api/v1/analytics/dashboard` | GET    | Get usage dashboard           |
| `/api/v1/analytics/report`    | GET    | Generate usage report         |
| `/api/v1/health`              | GET    | Health check                  |

## 🗄️ Database Schema

| Table              | Description                |
| ------------------ | -------------------------- |
| `users`            | User accounts              |
| `sessions`         | User sessions              |
| `queries`          | Query history with results |
| `query_feedback`   | Like/dislike feedback      |
| `activity_logs`    | Complete audit trail       |
| `usage_statistics` | Aggregated daily stats     |

## 🔧 Configuration

### Environment Variables

| Variable            | Description        | Default             |
| ------------------- | ------------------ | ------------------- |
| `OPENAI_API_KEY`    | OpenAI API key     | Required            |
| `OPENAI_MODEL`      | Model to use       | gpt-4-turbo-preview |
| `TABLEAU_SERVER`    | Tableau server URL | Required            |
| `TABLEAU_PAT_NAME`  | PAT name           | Required            |
| `TABLEAU_PAT_VALUE` | PAT value          | Required            |
| `POSTGRES_HOST`     | Database host      | localhost           |
| `POSTGRES_PASSWORD` | Database password  | Required            |
| `MCP_SERVER_URL`    | MCP server URL     | http://mcp:3927     |

## 🧪 Testing

```bash
cd backend

# Run tests
uv run pytest tests/ -v

# With coverage
uv run pytest tests/ --cov=src --cov-report=html
```

## 🐳 Docker Commands

```bash
# Build all images
make docker-build

# Start services
make docker-up

# View logs
make docker-logs

# Stop services
make docker-down

# Clean up
make docker-clean
```

## ☸️ Kubernetes Deployment

```bash
# Deploy to Kubernetes
make k8s-deploy

# Check status
make k8s-status

# View logs
make k8s-logs

# Delete deployment
make k8s-delete
```

## 📈 Activity Tracking

The platform tracks:

- ✅ Every query with timestamps
- ✅ Query execution times and row counts
- ✅ Like/dislike feedback with ratings
- ✅ Written comments and suggestions
- ✅ User activity history
- ✅ Aggregated usage statistics

## 🔒 Security

- Non-root Docker containers
- Secrets managed via environment variables
- CORS configuration for frontend
- Input validation on all endpoints

## 📝 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request
