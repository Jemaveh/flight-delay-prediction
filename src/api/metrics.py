"""
Métriques Prometheus exposées par l'API (scrape GET /metrics).

Latence et volume HTTP : instrumentator (histogramme par route).
Métier : jauge joblib + compteur POST /predict. Aucun appel OpenSky.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.applications import Starlette

MODELE_CHARGE = Gauge(
    "airlines_modele_charge",
    "1 si le joblib LightGBM est chargé en mémoire, 0 sinon.",
)
PREDICTIONS = Counter(
    "airlines_predictions_total",
    "Nombre d'appels POST /predict, par issue.",
    ["statut"],
)


def brancher_prometheus(app: Starlette) -> None:
    """Enregistre le scrape /metrics sur l'application FastAPI."""
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics"],
    ).instrument(app).expose(
        app,
        endpoint="/metrics",
        include_in_schema=True,
        tags=["sante"],
    )


def rafraichir_jauge_modele(charge: bool) -> None:
    MODELE_CHARGE.set(1 if charge else 0)


def compter_prediction(statut: str) -> None:
    PREDICTIONS.labels(statut=statut).inc()
