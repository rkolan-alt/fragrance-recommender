PY := backend/.venv/bin/python

.PHONY: setup data process features images clones evaluate migrate prices validate-prices backend frontend test lint

setup:
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -e "backend[dev]"
	cd frontend && npm install

data:
	cd backend && ../$(PY) -m pipeline.download

process:
	cd backend && ../$(PY) -m pipeline.clean && ../$(PY) -m pipeline.validate

features:
	cd backend && ../$(PY) -m pipeline.features

clones:
	cd backend && ../$(PY) -m pipeline.clones

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8001

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint

evaluate:
	cd backend && ../$(PY) -m pipeline.evaluate

migrate:
	cd backend && .venv/bin/alembic upgrade head

prices:
	cd backend && .venv/bin/python -m app.pricing.refresh --top 50

validate-prices:
	cd backend && .venv/bin/python -m app.pricing.validate --live --limit 10

images:
	cd backend && ../$(PY) -m pipeline.images
