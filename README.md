# 🎯 Tableau MCP AI Agent

An AI-powered platform for querying and analyzing Tableau data using natural language. Built with FastAPI, LangGraph, and VizQL Data Service (MCP).

## ✨ Features

### Core Capabilities

- **Natural Language Queries**: Ask questions about your Tableau data in plain English
- **AI-Powered Analysis**: Get automated insights and recommendations using GPT-4/Azure OpenAI
- **VizQL Data Service**: Native Tableau query execution via MCP Server
- **Multi-turn Conversations**: Follow-up questions with context memory
- **Smart Visualizations**: Chart.js-powered visualizations with auto-generated charts

### Tableau Extension (NEW)

- **Dashboard Embedded AI**: AI assistant embedded directly in Tableau dashboards
- **Context-Aware Queries**: Uses dashboard filters, selections, and parameters
- **Filter Scope Detection**: Intelligently detects if user wants filtered or global data
- **Markdown Rendering**: Rich formatted responses with tables and code blocks
- **Conversation Memory**: Multi-turn conversations within the extension

### Activity Tracking

- Full audit trail of queries, feedback, and usage
- Like/dislike feedback system
- Analytics dashboard with usage statistics

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         TABLEAU CLOUD / SERVER                          │
│  ┌──────────────────┐                                                    │
│  │ Tableau Extension│  ←── AI chat embedded in dashboard                │
│  │ (index.html)     │                                                    │
│  └────────┬─────────┘                                                    │
└───────────┼─────────────────────────────────────────────────────────────┘
            │ HTTPS
            ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                                  │
│  ┌────────────────────────────────────────────────────────────────────┐   │
│  │                    DASHBOARD AGENT (LangGraph)                      │   │
│  │  • Intent Classification (chat, capability, context, data_query)   │   │
│  │  • Context Scope Detection (filtered vs global)                    │   │
│  │  • Conversation Memory (MemorySaver)                               │   │
│  └────────────────────────────────┬───────────────────────────────────┘   │
│                                   │                                        │
│                       ┌───────────▼───────────┐                           │
│                       │     DATA AGENT        │                           │
│                       │  (VizQL Orchestrator) │                           │
│                       │  • Discover → Plan    │                           │
│                       │  • Review → Execute   │                           │
│                       │  • Analyze            │                           │
│                       └───────────┬───────────┘                           │
│                                   │                                        │
└───────────────────────────────────┼────────────────────────────────────────┘
                                    │ HTTP/SSE
                        ┌───────────▼───────────┐
                        │     MCP SERVER        │
                        │  (VizQL Data Service) │
                        │  • tableau-mcp        │
                        └───────────┬───────────┘
                                    │
                        ┌───────────▼───────────┐
                        │   TABLEAU CLOUD/      │
                        │   SERVER API          │
                        └───────────────────────┘
```

## 📁 Project Structure

```
tableau-mcp-agent/
├── backend/                        # FastAPI Backend
│   ├── src/
│   │   ├── agent/
│   │   │   ├── dashboard_agent.py  # LangGraph Dashboard Agent
│   │   │   └── graph.py            # Data Agent (VizQL orchestration)
│   │   ├── api/
│   │   │   ├── dashboard_routes.py # Tableau Extension API
│   │   │   └── routes/             # Other REST endpoints
│   │   ├── core/                   # Config, logging, exceptions
│   │   ├── db/                     # SQLAlchemy models & sessions
│   │   ├── mcp/                    # MCP client
│   │   └── main.py                 # FastAPI application
│   └── Dockerfile
│
├── tableau-extension/              # Tableau Dashboard Extension
│   ├── ai-analytics-agent.trex    # Extension manifest
│   ├── src/
│   │   ├── index.html             # Main extension UI
│   │   ├── app.js                 # Extension logic
│   │   ├── styles.css             # Dark theme styling
│   │   └── demo.html              # Standalone demo for testing
│   └── README.md                  # Extension documentation
│
├── frontend/                       # Streamlit Frontend (alternative UI)
│   ├── app.py
│   └── pages/
│
├── docker-compose.yml              # Development setup
├── docker-compose.prod.yml         # Production setup
└── Makefile
```

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- OpenAI API key (or Azure OpenAI)
- Tableau Cloud/Server with Connected App credentials

### 1. Clone and Configure

```bash
git clone <repo-url>
cd Tableau_MCP

# Create environment file
cp .env.template .env

# Edit .env with your credentials:
# - OPENAI_API_KEY (or Azure OpenAI settings)
# - TABLEAU_SERVER, TABLEAU_SITE_NAME
# - TABLEAU_CONNECTED_APP_* credentials
```

### 2. Start with Docker

```bash
# Start all services
docker compose up -d

# Access the applications:
# - Streamlit UI: http://localhost:8501
# - API Docs: http://localhost:8000/docs
# - Extension Demo: http://localhost:8080/demo.html
```

### 3. Start Extension Demo Server

```bash
cd tableau-extension/src
python3 -m http.server 8080
# Open http://localhost:8080/demo.html
```

## 📊 API Endpoints

### Dashboard Agent (Tableau Extension)

| Endpoint                         | Method | Description                     |
| -------------------------------- | ------ | ------------------------------- |
| `/api/v1/dashboard/query`        | POST   | Process question from extension |
| `/api/v1/dashboard/health`       | GET    | Extension health check          |
| `/api/v1/dashboard/capabilities` | GET    | List available intents          |

### Data Agent (Direct Queries)

| Endpoint                | Method | Description                   |
| ----------------------- | ------ | ----------------------------- |
| `/api/v1/query`         | POST   | Submit natural language query |
| `/api/v1/query/history` | GET    | Get query history             |
| `/api/v1/datasources`   | GET    | List available datasources    |

### Analytics & Feedback

| Endpoint                      | Method | Description                  |
| ----------------------------- | ------ | ---------------------------- |
| `/api/v1/feedback`            | POST   | Submit like/dislike feedback |
| `/api/v1/analytics/dashboard` | GET    | Usage dashboard              |

## 🔌 Tableau Extension Setup

### 1. Deploy Backend

Deploy the backend to your infrastructure and note the URL.

### 2. Configure Extension

Edit `tableau-extension/src/app.js`:

```javascript
const CONFIG = {
    API_URL: 'https://your-backend-url.com/api/v1',
    ...
};
```

### 3. Host Extension Files

Host the extension files (`index.html`, `app.js`, `styles.css`) on HTTPS.

### 4. Update CORS

Add your extension URL to `CORS_ORIGINS` in environment:

```
CORS_ORIGINS=https://your-tableau-site.tableau.com
```

### 5. Register in Tableau

1. Open Tableau dashboard
2. Drag "Extension" object to dashboard
3. Select "Add from file" → select `.trex` file
4. IT may need to allow-list the extension URL

## 🧠 Intent Classification

The Dashboard Agent classifies user intents:

| Intent              | Examples                     | Handler                 |
| ------------------- | ---------------------------- | ----------------------- |
| `chat`              | "Hello", "Thank you"         | Local response          |
| `capability`        | "What can you do?"           | Local response          |
| `dashboard_context` | "What filters are applied?"  | Uses Tableau context    |
| `clarification`     | "sales" (too vague)          | Asks for clarification  |
| `data_query`        | "Top 5 customers by revenue" | Delegates to Data Agent |

## 🔍 Context Scope Detection

When filters are active, the agent detects query scope:

| User Says          | Detected Scope | Behavior               |
| ------------------ | -------------- | ---------------------- |
| "Top 5 products"   | `filtered`     | Uses dashboard filters |
| "Show all regions" | `global`       | Ignores filters        |
| "Overall total"    | `global`       | Queries all data       |
| "In this view"     | `filtered`     | Uses current filters   |

## 🔧 Environment Variables

| Variable                             | Description                       | Required                 |
| ------------------------------------ | --------------------------------- | ------------------------ |
| `OPENAI_API_KEY`                     | OpenAI API key                    | Yes\*                    |
| `AZURE_OPENAI_API_KEY`               | Azure OpenAI key                  | Yes\*                    |
| `AZURE_OPENAI_ENDPOINT`              | Azure endpoint                    | For Azure                |
| `TABLEAU_SERVER`                     | Tableau Cloud/Server URL          | Yes                      |
| `TABLEAU_CONNECTED_APP_CLIENT_ID`    | Connected App ID                  | Yes                      |
| `TABLEAU_CONNECTED_APP_SECRET_VALUE` | Connected App Secret              | Yes                      |
| `CORS_ORIGINS`                       | Allowed origins (comma-separated) | For Extension            |
| `MCP_SERVER_URL`                     | MCP server URL                    | Default: http://mcp:3927 |

\*Either OpenAI or Azure OpenAI is required

## 🧪 Testing

```bash
# Test the demo (no Tableau required)
cd tableau-extension/src
python3 -m http.server 8080
# Open http://localhost:8080/demo.html

# Run backend tests
cd backend
uv run pytest tests/ -v
```

## 🐳 Docker Commands

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f backend

# Rebuild after code changes
docker compose build backend && docker compose up -d backend

# Stop services
docker compose down
```

## 📈 Features Breakdown

### Visualization Support

- Automatic chart type detection (bar, line, pie)
- Chart.js rendering in extension
- Markdown tables for data preview

### Conversation Memory

- Multi-turn conversations
- Thread ID for session continuity
- Follow-up questions (e.g., "What about last year?")

### Security

- Non-root Docker containers
- CORS configuration
- Connected App authentication for Tableau
- Input validation on all endpoints

## 📝 License

MIT License - see LICENSE file for details.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/tableau-extension`)
3. Make your changes
4. Run tests
5. Submit a pull request
