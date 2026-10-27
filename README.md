# Local MLflow Tracking Server

One long-running, self-hosted MLflow tracking server for all local ML projects.
Projects are separated by **experiments**, not by separate servers.

| Component      | Details                                                                 |
|----------------|-------------------------------------------------------------------------|
| MLflow server  | `ghcr.io/mlflow/mlflow:v3.17.2` + `psycopg2-binary` (multi-arch: arm64 and amd64) |
| Backend store  | PostgreSQL 16 (`postgres:16`), Docker volume `pgdata`                   |
| Artifact store | Docker volume `mlartifacts`, served through MLflow's artifact proxy     |
| URL            | <http://localhost:5050> (bound to `127.0.0.1` only, not exposed to the network) |

Port 5000 is deliberately not used on the host because macOS AirPlay Receiver occupies it.

## Files

```
Dockerfile              MLflow image (official image + Postgres driver)
docker-compose.yml      postgres + mlflow services, named volumes
.env.example            template for .env (committed)
.env                    real credentials (gitignored)
Makefile                day-to-day commands
scripts/backup.sh       pg_dump + artifacts tarball -> backups/<timestamp>/
scripts/restore.sh      restore from a backup directory (asks for confirmation)
scripts/smoke_test.py   end-to-end check of tracking, artifacts and model registry
examples/               example project (make example)
backups/                created by make backup (gitignored)
.venv/                  client environment, created by make venv (gitignored)
```

## First-time setup

```bash
cd "$HOME/Work Local/SQE/local-server/mlflow-server"
cp .env.example .env
sed -i '' "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/" .env
chmod 600 .env
make up          # build + start, waits until both services are healthy
make venv        # local .venv with mlflow==$MLFLOW_VERSION and scikit-learn
make smoke-test
```

## Commands

| Command                       | What it does                                                          |
|-------------------------------|-----------------------------------------------------------------------|
| `make up`                     | Build the image and start in the background; waits for `healthy`.     |
| `make down`                   | Stop and remove containers. **Volumes (all data) are kept.**          |
| `make logs`                   | Follow logs.                                                          |
| `make status`                 | Container status and health.                                          |
| `make backup`                 | Dump the database and archive artifacts into `backups/<timestamp>/`.  |
| `make restore BACKUP=<dir>`   | Restore database and artifacts from a backup (asks for confirmation). |
| `make smoke-test`             | End-to-end check: params, metrics, artifacts, model registry.         |
| `make example`                | Log example runs to the `iris-classifier` experiment.                 |
| `make venv`                   | Create `.venv` with `mlflow==$MLFLOW_VERSION` and `scikit-learn`.     |
| `make db-upgrade`             | Run `mlflow db upgrade` on the database (after some version upgrades).|

## Start / stop

Both services use `restart: unless-stopped`, so they come back automatically after
Docker Desktop restarts, unless you stopped them with `make down`.

There is intentionally no target that runs `docker compose down -v`. Doing that
would delete the `pgdata` and `mlartifacts` volumes, which means all runs, models and artifacts.

UI: <http://localhost:5050>. Health: `curl http://localhost:5050/health` returns `OK`.

## Design decisions

These go beyond the basic setup. Each one fixes a concrete problem or makes the
server easier to run day to day.

| Decision | Where | Why |
|----------|-------|-----|
| `postgresql+psycopg2://` backend URI | `docker-compose.yml`, `Makefile` | SQLAlchemy 2.1 (shipped in the image) maps a plain `postgresql://` URI to psycopg 3, which is not installed. Without the explicit driver the server crashes with `No module named 'psycopg'`. |
| `init: true` on the mlflow service | `docker-compose.yml` | MLflow starts uvicorn worker processes. Without an init process as PID 1, exited workers are never reaped and `docker compose stop` fails with *"PID is zombie and can not be killed"*. `restore` depends on stopping the server cleanly. |
| `--workers=2` | `docker-compose.yml` | The default is 4. Two workers are enough for one user and use less memory. |
| Postgres has no published port | `docker-compose.yml` | Only the MLflow container can reach the database. Backup and restore use `docker compose exec`, so no host port is needed. |
| Python-based healthcheck | `docker-compose.yml` | The MLflow image has no `curl` or `wget`. |
| `--allowed-hosts` and `--cors-allowed-origins` | `docker-compose.yml` | MLflow 3.x rejects unknown Host headers. The allowlist (exact `host:port` match) covers `localhost`, `127.0.0.1` and `host.docker.internal` on the host port. `/health` is always exempt. |
| Image tagged `mlflow-server:<version>` | `docker-compose.yml` | Each upgrade builds a new tag, so the previous image stays available for a rollback. |
| `make venv` | `Makefile` | Creates the client environment for the smoke test and examples with the same MLflow version as the server. |
| `make db-upgrade` | `Makefile` | Makes the schema migration in the upgrade procedure a single command. It stops the server, runs `mlflow db upgrade` in a one-off container, and leaves Postgres running. |
| `make example` | `Makefile`, `examples/` | Example project to explore the UI and to copy as a template. |
| `skops_trusted_types` for tree models | `examples/`, README example | MLflow 3.17 saves sklearn models with skops. Tree-based models (DecisionTree, RandomForest, GradientBoosting) fail to log unless `sklearn.tree._tree.Tree` is marked as trusted. Only do this for models you trained yourself. |
| `MLFLOW_VERSION` file in each backup | `scripts/backup.sh` | `restore` warns when a backup comes from a different MLflow version, because the schema might need `make db-upgrade`. |
| `.venv/`, `__pycache__/`, `.DS_Store` in `.gitignore` | `.gitignore` | Local and generated files that should not be committed. |

### Recommended host settings

- **Start Docker Desktop at login** (*Settings → General → Start Docker Desktop
  when you sign in*). `restart: unless-stopped` only brings the containers back
  when Docker Desktop itself is running.
- **Keep a copy of `backups/` off this Mac** (external disk or cloud drive).

## Backup and restore

```bash
make backup                                  # -> backups/<YYYYmmdd-HHMMSS>/
make restore BACKUP=backups/20261027-120000  # asks you to type 'yes'
```

A backup directory contains:

- `db.dump`: `pg_dump` in custom format (runs, params, metrics, model registry)
- `artifacts.tar.gz`: the full contents of the `mlartifacts` volume
- `MLFLOW_VERSION`: the MLflow version the backup was taken with

Restore stops the MLflow server, drops and recreates the database, restores it,
replaces all artifacts, and starts the server again.

Backups are taken while the server is running. For a fully consistent snapshot,
avoid logging runs while a backup is in progress. `backups/` is gitignored. Copy it
somewhere safe (external disk or cloud drive) if the data matters.

## Upgrading MLflow safely

1. **Back up first:** `make backup`
2. Bump `MLFLOW_VERSION` in `.env` (and in `.env.example`, plus the default
   `ARG` in `Dockerfile`, to keep them in sync). Check the
   [release notes](https://github.com/mlflow/mlflow/releases) for breaking changes.
3. Rebuild and start: `make up`
4. If the server does not become healthy, check `make logs`. If MLflow reports an
   out-of-date database schema, run the migration and start again:
   ```bash
   make db-upgrade   # runs `mlflow db upgrade <backend-uri>` in a one-off container
   make up
   ```
5. Run `make smoke-test` (update the client first: `.venv/bin/pip install "mlflow==<new version>"`).
6. Upgrade `mlflow` in your projects to the same version.

**Rollback:** set `MLFLOW_VERSION` back, then `make restore BACKUP=<pre-upgrade backup>`
and `make up`. Schema migrations are not reversible, so restoring the backup is required.

## Using the server from your projects

### Point projects at the server

Set the tracking URI through the environment, not in code. MLflow reads
`MLFLOW_TRACKING_URI` automatically.

- Globally, in `~/.zshrc`:
  ```bash
  export MLFLOW_TRACKING_URI=http://localhost:5050
  ```
- Or per project, in the project's `.env` file (loaded by your tooling, e.g. `python-dotenv`, `direnv`, `uv run --env-file .env`):
  ```
  MLFLOW_TRACKING_URI=http://localhost:5050
  ```
- **Code running inside another Docker container** must use
  `http://host.docker.internal:5050`. Inside a container, `localhost` refers to the container itself:
  ```yaml
  # docker-compose.yml of your project
  environment:
    MLFLOW_TRACKING_URI: http://host.docker.internal:5050
  ```

The server only accepts the Host headers `localhost:5050`, `127.0.0.1:5050` and
`host.docker.internal:5050` (configured with `--allowed-hosts`). Any other
hostname gets `403 Invalid Host header`.

### Conventions

- One experiment per project: `mlflow.set_experiment("<project-name>")`
- Add a `project` tag to every run: `tags={"project": "<project-name>"}`
- Prefix registered model names with the project name: `<project-name>-<model>`

### Minimal example

```python
import mlflow
from sklearn.datasets import load_iris
from sklearn.ensemble import RandomForestClassifier

PROJECT = "iris-classifier"

# MLFLOW_TRACKING_URI comes from the environment, e.g. http://localhost:5050
mlflow.set_experiment(PROJECT)

X, y = load_iris(return_X_y=True)

with mlflow.start_run(tags={"project": PROJECT}):
    params = {"n_estimators": 100, "max_depth": 3}
    model = RandomForestClassifier(**params).fit(X, y)

    mlflow.log_params(params)
    mlflow.log_metric("train_accuracy", model.score(X, y))
    mlflow.sklearn.log_model(
        model,
        name="model",
        registered_model_name=f"{PROJECT}-rf",
        # Required for tree-based models with MLflow's default skops format
        # (only for models you trained or otherwise trust).
        skops_trusted_types=["sklearn.tree._tree.Tree"],
    )
```

### Example runs

`make example` runs [`examples/iris_classifier.py`](examples/iris_classifier.py). It logs a
5-run hyperparameter sweep to the experiment `iris-classifier`: params, the dataset,
per-iteration loss curves, final metrics, plots, a classification report and the model.
The best model is registered as `iris-classifier-gbm` with the alias `champion`.
Open the experiment in the UI, select the runs and click **Compare**.

Keep the client `mlflow` version in your projects close to the server version
(ideally the same).
