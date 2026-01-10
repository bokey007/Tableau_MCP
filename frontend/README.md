# Tableau MCP Frontend

Streamlit frontend for the Tableau MCP AI Agent platform.

## Features

- Natural language query interface
- Interactive data visualization
- Query history and feedback
- Datasource browser
- Analytics dashboard

## Development

```bash
# Install dependencies
uv sync

# Run development server
uv run streamlit run app.py

# Or with specific port
uv run streamlit run app.py --server.port 8501
```

## Pages

- **Home** - Ask questions about your Tableau data
- **History** - View and manage past queries
- **Analytics** - Usage statistics and metrics
- **Datasources** - Browse available datasources
