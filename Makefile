# =============================================================================
# Makefile for Tableau MCP AI Agent Platform
# =============================================================================
# Usage: make <target>
# =============================================================================

.PHONY: help install dev test clean docker-* k8s-* db-*

.DEFAULT_GOAL := help

# =============================================================================
# Help
# =============================================================================

help: ## Show this help
	@echo "Tableau MCP AI Agent Platform"
	@echo ""
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Development - Backend
# =============================================================================

install-backend: ## Install backend dependencies with UV
	cd backend && uv sync

run-backend: ## Run backend development server
	cd backend && uv run uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

test-backend: ## Run backend tests
	cd backend && uv run pytest tests/ -v

test-cov: ## Run backend tests with coverage
	cd backend && uv run pytest tests/ -v --cov=src --cov-report=html --cov-report=term

lint-backend: ## Lint backend code
	cd backend && uv run ruff check src/ tests/

lint-fix: ## Fix linting issues
	cd backend && uv run ruff check src/ tests/ --fix

typecheck: ## Run type checking
	cd backend && uv run mypy src/

# =============================================================================
# Development - Frontend
# =============================================================================

install-frontend: ## Install frontend dependencies with UV
	cd frontend && uv sync

run-frontend: ## Run frontend development server
	cd frontend && uv run streamlit run app.py --server.port 8501

# =============================================================================
# Development - Full Stack
# =============================================================================

install: install-backend install-frontend ## Install all dependencies

dev: ## Run full stack locally (requires Docker for Postgres & MCP)
	docker-compose up -d postgres mcp
	@echo "Waiting for services..."
	@sleep 5
	$(MAKE) db-migrate
	$(MAKE) run-backend &
	$(MAKE) run-frontend

dev-backend: ## Run only backend with Docker services
	docker-compose up -d postgres mcp
	@sleep 3
	$(MAKE) db-migrate
	$(MAKE) run-backend

# =============================================================================
# Docker
# =============================================================================

docker-build: ## Build all Docker images
	docker-compose build

docker-up: ## Start all services with Docker Compose
	docker-compose up -d
	@echo "Waiting for database..."
	@sleep 5
	docker-compose exec backend uv run alembic upgrade head || true
	@echo ""
	@echo "Services started:"
	@echo "  - Frontend: http://localhost:8501"
	@echo "  - Backend API: http://localhost:8000"
	@echo "  - API Docs: http://localhost:8000/docs"

docker-down: ## Stop all services
	docker-compose down

docker-logs: ## View logs
	docker-compose logs -f

docker-logs-backend: ## View backend logs
	docker-compose logs -f backend

docker-logs-frontend: ## View frontend logs
	docker-compose logs -f frontend

docker-clean: ## Clean up Docker resources
	docker-compose down -v --rmi all
	docker system prune -f

docker-rebuild: ## Rebuild and restart services
	docker-compose down
	docker-compose build --no-cache
	docker-compose up -d

# =============================================================================
# Production Docker
# =============================================================================

docker-build-prod: ## Build production images
	docker-compose -f docker-compose.prod.yml build

docker-up-prod: ## Start production services
	docker-compose -f docker-compose.prod.yml up -d

docker-down-prod: ## Stop production services
	docker-compose -f docker-compose.prod.yml down

# =============================================================================
# Database
# =============================================================================

db-migrate: ## Run database migrations
	cd backend && uv run alembic upgrade head

db-migration: ## Create new migration
	@read -p "Migration name: " name; \
	cd backend && uv run alembic revision --autogenerate -m "$$name"

db-downgrade: ## Downgrade database one version
	cd backend && uv run alembic downgrade -1

db-history: ## Show migration history
	cd backend && uv run alembic history

db-shell: ## Open PostgreSQL shell
	docker-compose exec postgres psql -U tableau_mcp -d tableau_mcp_db

db-reset: ## Reset database (WARNING: destroys data)
	docker-compose down -v
	docker-compose up -d postgres
	@echo "Waiting for postgres..."
	@sleep 5
	$(MAKE) db-migrate
	@echo "Database reset complete"

db-init: ## Initialize database tables (without Alembic)
	cd backend && uv run python -c "import asyncio; from src.db.session import init_db; asyncio.run(init_db())"

# =============================================================================
# Kubernetes/OpenShift
# =============================================================================

k8s-deploy: ## Deploy to Kubernetes
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/secrets.yaml
	kubectl apply -f k8s/deployment-postgres.yaml
	@sleep 10
	kubectl apply -f k8s/deployment-mcp.yaml
	kubectl apply -f k8s/deployment-backend.yaml
	kubectl apply -f k8s/deployment-frontend.yaml
	kubectl apply -f k8s/services.yaml
	kubectl apply -f k8s/route.yaml

k8s-delete: ## Delete from Kubernetes
	kubectl delete -f k8s/ --ignore-not-found

k8s-status: ## Check Kubernetes status
	kubectl get all -n tableau-mcp

k8s-logs: ## View Kubernetes logs
	kubectl logs -f -l app=tableau-mcp -n tableau-mcp --all-containers

k8s-logs-backend: ## View backend logs in Kubernetes
	kubectl logs -f -l component=backend -n tableau-mcp

k8s-restart: ## Restart Kubernetes deployments
	kubectl rollout restart deployment -n tableau-mcp

# =============================================================================
# Utilities
# =============================================================================

clean: ## Clean build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf backend/.venv frontend/.venv
	rm -rf htmlcov .coverage

setup: ## Initial project setup
	@echo "Setting up Tableau MCP AI Agent..."
	cp -n backend/.env.example backend/.env 2>/dev/null || true
	cp -n frontend/.env.example frontend/.env 2>/dev/null || true
	$(MAKE) install
	@echo ""
	@echo "==================================="
	@echo "Setup complete! Next steps:"
	@echo "==================================="
	@echo "1. Edit backend/.env with your credentials:"
	@echo "   - OPENAI_API_KEY"
	@echo "   - TABLEAU_PAT_NAME and TABLEAU_PAT_VALUE"
	@echo "   - POSTGRES_PASSWORD"
	@echo ""
	@echo "2. Run 'make docker-up' to start all services"
	@echo ""
	@echo "3. Access the application:"
	@echo "   - UI: http://localhost:8501"
	@echo "   - API: http://localhost:8000/docs"
	@echo ""

check: lint-backend typecheck test-backend ## Run all checks

format: ## Format code
	cd backend && uv run ruff format src/ tests/
