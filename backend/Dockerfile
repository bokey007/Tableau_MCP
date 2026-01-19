# =============================================================================
# Backend Dockerfile
# =============================================================================
# Multi-stage build using UV for package management
# =============================================================================

# Stage 1: Build
FROM python:3.11-slim as builder

WORKDIR /app

# Install UV
RUN pip install uv

# Copy project files
COPY pyproject.toml README.md ./
COPY src/ ./src/

# Create virtual environment and install dependencies
RUN uv venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
RUN uv pip install -e . --no-cache

# Stage 2: Runtime
FROM python:3.11-slim as runtime

LABEL maintainer="Tableau MCP Agent Team" \
    version="1.0.0" \
    description="Tableau MCP AI Agent Backend"

# Create non-root user
RUN groupadd --gid 1000 appgroup && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash --create-home appuser

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ /app/src/

# Copy dashboard configurations
COPY configs/ /app/configs/

# Create necessary directories with correct permissions
RUN mkdir -p /app/logs /app/tmp && \
    chown -R appuser:appgroup /app

# Set environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/home/appuser

# Switch to non-root user
USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/live || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
