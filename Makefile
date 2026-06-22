.PHONY: help install lint format test test-unit test-integration test-security clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install project with dev dependencies
	pip install -e ".[dev]"
	pre-commit install

lint: ## Run linters (ruff + mypy)
	ruff check .
	mypy apps services shared models orchestration

format: ## Auto-format code (ruff + black)
	ruff check --fix .
	black .

test: ## Run all tests
	pytest

test-unit: ## Run unit tests only
	pytest tests/unit -m unit

test-integration: ## Run integration tests only
	pytest tests/integration -m integration

test-security: ## Run tenant isolation security tests
	pytest tests/security -m security

test-performance: ## Run performance benchmark tests
	pytest tests/performance -m performance

test-e2e: ## Run end-to-end tests
	pytest tests/e2e -m e2e

clean: ## Remove build artifacts and caches
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf dist build htmlcov .coverage