"""Example project: log a small hyperparameter sweep to the local MLflow server.

Follows the conventions from the README:
  - one experiment per project (named after the project),
  - a `project` tag on every run,
  - registered model names prefixed with the project name.

Each run logs params, the training dataset, per-iteration loss curves, final
metrics, plots, a text report, and the model. The best run's model is
registered as `iris-classifier-gbm` and gets the alias `champion`.

Usage:
    MLFLOW_TRACKING_URI=http://localhost:5050 python examples/iris_classifier.py
"""

import os
import sys
import time

import matplotlib

matplotlib.use("Agg")  # Headless backend: figures are only saved, never shown.

import matplotlib.pyplot as plt
import mlflow
from mlflow import MlflowClient
from mlflow.entities import Metric
from mlflow.models import infer_signature
from sklearn.datasets import load_iris
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    accuracy_score,
    classification_report,
    f1_score,
    log_loss,
)
from sklearn.model_selection import train_test_split

PROJECT = "iris-classifier"
MODEL_NAME = f"{PROJECT}-gbm"
PARAM_GRID = [
    {"n_estimators": 50, "learning_rate": 0.3, "max_depth": 1},
    {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 2},
    {"n_estimators": 150, "learning_rate": 0.05, "max_depth": 2},
    {"n_estimators": 100, "learning_rate": 0.1, "max_depth": 3},
    {"n_estimators": 200, "learning_rate": 0.02, "max_depth": 3},
]


def plot_confusion_matrix(model, X_test, y_test, class_names):
    fig, ax = plt.subplots(figsize=(5, 4))
    ConfusionMatrixDisplay.from_estimator(
        model, X_test, y_test, display_labels=class_names, cmap="Blues", ax=ax
    )
    ax.set_title("Confusion matrix (test set)")
    fig.tight_layout()
    return fig


def plot_feature_importance(model, feature_names):
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.barh(feature_names, model.feature_importances_)
    ax.set_xlabel("Importance")
    ax.set_title("Feature importance")
    fig.tight_layout()
    return fig


def train_and_log(params, data, dataset):
    """Train one model, log everything to a new run, and return (run_id, model_uri, f1)."""
    X_train, X_test, y_train, y_test, feature_names, class_names = data
    run_name = "gbm-n{n_estimators}-lr{learning_rate}-d{max_depth}".format(**params)

    with mlflow.start_run(run_name=run_name, tags={"project": PROJECT}) as run:
        mlflow.log_params(params)
        mlflow.log_input(dataset, context="training")

        model = GradientBoostingClassifier(random_state=42, **params).fit(X_train, y_train)

        # Per-iteration curves, sent in one batch instead of one request per step.
        now = int(time.time() * 1000)
        curves = [
            Metric("train_deviance", float(loss), now, step)
            for step, loss in enumerate(model.train_score_, start=1)
        ] + [
            Metric("test_log_loss", log_loss(y_test, proba, labels=model.classes_), now, step)
            for step, proba in enumerate(model.staged_predict_proba(X_test), start=1)
        ]
        MlflowClient().log_batch(run.info.run_id, metrics=curves)

        y_pred = model.predict(X_test)
        f1 = f1_score(y_test, y_pred, average="macro")
        mlflow.log_metrics({"test_accuracy": accuracy_score(y_test, y_pred), "test_f1_macro": f1})

        mlflow.log_figure(
            plot_confusion_matrix(model, X_test, y_test, class_names), "plots/confusion_matrix.png"
        )
        mlflow.log_figure(plot_feature_importance(model, feature_names), "plots/feature_importance.png")
        plt.close("all")
        mlflow.log_text(
            classification_report(y_test, y_pred, target_names=class_names),
            "reports/classification_report.txt",
        )

        model_info = mlflow.sklearn.log_model(
            model,
            name="model",
            signature=infer_signature(X_test, y_pred),
            input_example=X_test.head(3),
            # Tree ensembles need this with MLflow's default skops format. Safe here
            # because we trained the model ourselves.
            skops_trusted_types=["sklearn.tree._tree.Tree"],
        )

    print(f"  {run_name:<24} test_f1_macro={f1:.4f}")
    return run.info.run_id, model_info.model_uri, f1


def main() -> int:
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        print("ERROR: MLFLOW_TRACKING_URI is not set, e.g. http://localhost:5050", file=sys.stderr)
        return 1

    mlflow.set_experiment(PROJECT)

    iris = load_iris(as_frame=True)
    frame = iris.frame
    X, y = frame[iris.feature_names], frame["target"]
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, random_state=42, stratify=y
    )
    data = (X_train, X_test, y_train, y_test, iris.feature_names, list(iris.target_names))
    dataset = mlflow.data.from_pandas(frame, name="iris", targets="target")

    print(f"Logging {len(PARAM_GRID)} runs to experiment '{PROJECT}' at {mlflow.get_tracking_uri()}")
    results = [train_and_log(params, data, dataset) for params in PARAM_GRID]

    best_run_id, best_model_uri, best_f1 = max(results, key=lambda r: r[2])
    version = mlflow.register_model(best_model_uri, MODEL_NAME, tags={"project": PROJECT})
    MlflowClient().set_registered_model_alias(MODEL_NAME, "champion", version.version)

    experiment_id = mlflow.get_experiment_by_name(PROJECT).experiment_id
    print(f"\nBest run {best_run_id} (test_f1_macro={best_f1:.4f})")
    print(f"Registered {MODEL_NAME} version {version.version} with alias 'champion'")
    print(f"Open: {mlflow.get_tracking_uri()}/#/experiments/{experiment_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
