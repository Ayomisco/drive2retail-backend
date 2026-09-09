.PHONY: help install dev migrate makemigrations superuser seed test lint format typecheck schema shell worker beat up down logs audit

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install:  ## Create the venv and install everything
	uv venv --python 3.12 && uv pip install -e . && uv pip install --group dev

dev:  ## Run the API
	python manage.py runserver 0.0.0.0:8000

migrate:  ## Apply migrations
	python manage.py migrate

makemigrations:  ## Generate migrations
	python manage.py makemigrations

superuser:  ## Create a staff superuser
	python manage.py createsuperuser

seed:  ## Load reference data (roles, tax classes, zones, settings)
	python manage.py seed_reference_data

test:  ## Run the test suite
	pytest -n auto

test-cov:  ## Run tests with coverage
	pytest --cov --cov-report=term-missing --cov-report=html

lint:  ## Lint
	ruff check .

format:  ## Format and fix
	ruff format . && ruff check --fix .

typecheck:  ## Type check
	mypy d2r config

schema:  ## Write the OpenAPI schema
	python manage.py spectacular --file schema.yml --validate

audit:  ## Check dependencies for known vulnerabilities
	pip-audit

shell:  ## Django shell
	python manage.py shell_plus

worker:  ## Celery worker
	celery -A config worker -Q critical,default -l info

beat:  ## Celery beat
	celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

up:  ## Start the full stack
	docker compose up -d

down:  ## Stop the stack
	docker compose down

logs:  ## Tail the API logs
	docker compose logs -f api
