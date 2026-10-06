PY := backend/.venv/bin/python

.PHONY: setup data process features clones backend frontend test lint

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
	cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint
