"""End-to-end smoke test for the local MLflow tracking server.

Logs a param, a metric, a text artifact and a registered sklearn model, then
reads everything back through the server. Exits non-zero on failure.

Usage:
    MLFLOW_TRACKING_URI=http://localhost:5050 python scripts/smoke_test.py
"""

import os
import sys
import tempfile
import traceback
from pathlib import Path

import mlflow
import numpy as np
from mlflow import MlflowClient
from mlflow.models import infer_signature
from sklearn.linear_model import LogisticRegression

TRACKING_URI = os.environ.get("MLFLOW_TRACKING_URI", "http://localhost:5050")
EXPERIMENT_NAME = "smoke-test"
MODEL_NAME = "smoke-test-model"
ARTIFACT_PATH = "smoke/hello.txt"
ARTIFACT_CONTENT = "Hello from the MLflow smoke test.\n"


def run_smoke_test() -> str:
    """Run all checks and return the created run ID. Raises AssertionError on failure."""
    mlflow.set_tracking_uri(TRACKING_URI)
    experiment = mlflow.set_experiment(EXPERIMENT_NAME)
    assert experiment.artifact_location.startswith("mlflow-artifacts:"), (
        f"Artifacts are not proxied by the server: {experiment.artifact_location}"
    )

    X = np.array([[0.0], [1.0], [2.0], [3.0]])
    y = np.array([0, 0, 1, 1])
    model = LogisticRegression().fit(X, y)

    with mlflow.start_run(run_name="smoke-test", tags={"project": "smoke-test"}) as run:
        mlflow.log_param("alpha", 0.5)
        mlflow.log_metric("accuracy", 1.0)
        mlflow.log_text(ARTIFACT_CONTENT, ARTIFACT_PATH)
        model_info = mlflow.sklearn.log_model(
            model,
            name="model",
            signature=infer_signature(X, model.predict(X)),
            registered_model_name=MODEL_NAME,
        )
    run_id = run.info.run_id

    client = MlflowClient()
    logged = client.get_run(run_id)
    assert logged.data.params.get("alpha") == "0.5", f"Unexpected params: {logged.data.params}"
    assert logged.data.metrics.get("accuracy") == 1.0, f"Unexpected metrics: {logged.data.metrics}"

    with tempfile.TemporaryDirectory() as tmp:
        local_path = mlflow.artifacts.download_artifacts(
            run_id=run_id, artifact_path=ARTIFACT_PATH, dst_path=tmp
        )
        content = Path(local_path).read_text()
    assert content == ARTIFACT_CONTENT, f"Artifact content mismatch: {content!r}"

    versions = client.search_model_versions(f"name = '{MODEL_NAME}'")
    assert any(v.run_id == run_id for v in versions), (
        f"No version of '{MODEL_NAME}' is linked to run {run_id}"
    )

    loaded = mlflow.sklearn.load_model(model_info.model_uri)
    assert list(loaded.predict(X)) == list(model.predict(X)), "Loaded model predicts differently"

    return run_id


def main() -> int:
    print(f"Running MLflow smoke test against {TRACKING_URI}")
    try:
        run_id = run_smoke_test()
    except Exception:
        traceback.print_exc()
        print("\nSMOKE TEST: FAIL")
        return 1
    print(f"\nRun ID: {run_id}")
    print("SMOKE TEST: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
