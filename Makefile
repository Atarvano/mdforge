.PHONY: help install dev test lint format typecheck build clean all

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install the package in editable mode (core only)
	python -m pip install -e .

dev: ## Install with every optional extra plus dev tooling
	python -m pip install -e ".[all,dev]"

test: ## Run the test suite with coverage
	pytest --cov=mdforge --cov-report=term-missing

lint: ## Run ruff
	ruff check .

format: ## Auto-fix and format with ruff
	ruff check --fix . && ruff format .

typecheck: ## Run mypy over the package
	mypy src/mdforge

build: ## Build sdist + wheel
	python -m build

clean: ## Remove build, cache and coverage artefacts
	rm -rf build dist *.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

all: lint typecheck test ## Lint, type-check and test
