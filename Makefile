# Convenience targets for the local MLflow tracking server.
# There is intentionally NO target that removes volumes (docker compose down -v).

-include .env

PYTHON ?= .venv/bin/python

.PHONY: up down logs status backup restore smoke-test example venv db-upgrade

## Build the image and start everything; waits until both services are healthy.
up:
	docker compose up -d --build --wait

## Stop and remove containers. Volumes (data) are kept.
down:
	docker compose down

## Follow logs of all services.
logs:
	docker compose logs -f --tail=100

## Show container status and health.
status:
	docker compose ps

## Dump the database and archive the artifacts into backups/<timestamp>/.
backup:
	./scripts/backup.sh

## Restore from a backup directory: make restore BACKUP=backups/<timestamp>
restore:
	@test -n "$(BACKUP)" || { echo "Usage: make restore BACKUP=backups/<timestamp>" >&2; exit 1; }
	./scripts/restore.sh "$(BACKUP)"

## Run the end-to-end smoke test against the running server.
smoke-test:
	@test -x "$(PYTHON)" || { echo "ERROR: $(PYTHON) not found. Run 'make venv' first." >&2; exit 1; }
	$(PYTHON) scripts/smoke_test.py

## Log example runs (experiment 'iris-classifier') to explore in the UI.
example:
	@test -x "$(PYTHON)" || { echo "ERROR: $(PYTHON) not found. Run 'make venv' first." >&2; exit 1; }
	MLFLOW_TRACKING_URI="$${MLFLOW_TRACKING_URI:-http://localhost:$(MLFLOW_HOST_PORT)}" $(PYTHON) examples/iris_classifier.py

## Create .venv with the client libraries the smoke test needs.
venv:
	@test -n "$(MLFLOW_VERSION)" || { echo "ERROR: MLFLOW_VERSION is not set (create .env first)." >&2; exit 1; }
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install "mlflow==$(MLFLOW_VERSION)" scikit-learn

## Apply MLflow database schema migrations (needed after some version upgrades).
db-upgrade:
	docker compose up -d --wait postgres
	docker compose stop mlflow
	docker compose run --rm --no-deps mlflow \
		mlflow db upgrade "postgresql+psycopg2://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@postgres:5432/$(POSTGRES_DB)"
