# =============================================================================
# Frontend Dockerfile
# =============================================================================
# Streamlit frontend using UV for package management
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="Tableau MCP Agent Team" \
    version="1.0.0" \
    description="Tableau MCP AI Agent Frontend"

# Install runtime dependencies (including curl for health check)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home appuser

WORKDIR /app

# Install UV
RUN pip install uv

# Copy project files
COPY pyproject.toml README.md ./
COPY app.py .
COPY pages/ ./pages/
COPY components/ ./components/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN uv pip install -e . --no-cache

# Configure Streamlit
RUN mkdir -p /app/.streamlit
COPY <<EOF /app/.streamlit/config.toml
[server]
port = 8501
enableCORS = false
enableXsrfProtection = true
headless = true

[theme]
primaryColor = "#667eea"
backgroundColor = "#0e1117"
secondaryBackgroundColor = "#1a1f2c"
textColor = "#fafafa"
EOF

# Fix ownership
RUN chown -R appuser:appgroup /app

# Set environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0"]
