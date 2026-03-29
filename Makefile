.PHONY: setup start stop dev test lint build deploy docker-build docker-run clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

setup: ## One-time setup: venv, deps, .env, demo data
	@chmod +x setup.sh start.sh stop.sh
	./setup.sh

start: ## Start backend + frontend (opens browser)
	@chmod +x start.sh
	./start.sh

stop: ## Stop backend + frontend
	@chmod +x stop.sh
	./stop.sh

dev: ## Setup + start (full first-run experience)
	@chmod +x setup.sh start.sh
	@if [ ! -d ".venv" ]; then ./setup.sh; fi
	./start.sh

test: ## Run full test suite
	python3 -m pytest tests/ --tb=short -q

test-verbose: ## Run tests with verbose output
	python3 -m pytest tests/ -v --tb=long

lint: ## Run linting (ruff if available, else basic checks)
	@which ruff > /dev/null 2>&1 && ruff check . || echo "Install ruff for linting: pip install ruff"

fmt: ## Format code (ruff if available)
	@which ruff > /dev/null 2>&1 && ruff format . || echo "Install ruff for formatting: pip install ruff"

eval: ## Run eval suite
	python runner.py eval run

loop: ## Start optimization loop (5 cycles)
	python runner.py loop --max-cycles 5

docker-build: ## Build Docker image
	docker build -t autoagent-vnextcc .

docker-run: ## Run Docker container locally
	docker run --rm -p 8000:8000 --env-file .env autoagent-vnextcc

compose-up: ## Start with docker-compose
	docker compose up --build -d

compose-down: ## Stop docker-compose
	docker compose down

deploy-gcp: ## Deploy to Google Cloud Run (requires gcloud CLI)
	./deploy/deploy.sh

deploy-fly: ## Deploy to fly.io (requires flyctl)
	cd deploy && fly deploy --config fly.toml --dockerfile ../Dockerfile ..

clean: ## Remove .venv, node_modules, .autoagent/, build artifacts, and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist/ build/
	rm -rf .venv
	rm -rf web/node_modules
	rm -rf .autoagent/
	@echo "Clean complete. Run 'make setup' to start fresh."
