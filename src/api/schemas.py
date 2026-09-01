"""
Schémas Pydantic du corps JSON de l'API de prédiction.

Les champs d'entrée reprennent les colonnes de
``src.models.jeu.liste_colonnes_features(True)``.
La cible (durée observée) et ``last_seen`` n'y figurent pas.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntreePrediction(BaseModel):
    """Features d'un vol au décollage, alignées sur le joblib d'entraînement."""

    hub_origine: str = Field(description="Code ICAO du hub de départ.")
    jour_semaine: int = Field(ge=1, le=7, description="Jour ISO (1 = lundi).")
    mois: int = Field(ge=1, le=12, description="Mois calendaire (1–12).")
    heure_utc: float = Field(
        ge=0.0,
        le=24.0,
        description="Heure UTC de first_seen (heure + minutes / 60).",
    )
    temperature_origine: float | None = Field(
        default=None, description="Température au départ, °C."
    )
    vent_origine: float | None = Field(
        default=None, description="Vent au départ, m/s."
    )
    rafale_origine: float | None = Field(
        default=None, description="Rafale au départ, m/s."
    )
    pluie_origine: float | None = Field(
        default=None, description="Pluie 1 h au départ, mm."
    )
    visibilite_origine: float | None = Field(
        default=None, description="Visibilité au départ, m."
    )
    humidite_origine: float | None = Field(
        default=None, description="Humidité au départ, %."
    )
    temperature_dest: float | None = Field(
        default=None, description="Température destination, °C (souvent absente)."
    )
    vent_dest: float | None = Field(
        default=None, description="Vent destination, m/s."
    )
    rafale_dest: float | None = Field(
        default=None, description="Rafale destination, m/s."
    )
    pluie_dest: float | None = Field(
        default=None, description="Pluie 1 h destination, mm."
    )
    visibilite_dest: float | None = Field(
        default=None, description="Visibilité destination, m."
    )
    nb_articles_actu: float = Field(
        default=0.0,
        ge=0.0,
        description="Nombre d'articles du jour (jointure par date UTC).",
    )
    proxy_perturbation_actu: float = Field(
        default=0.0,
        description="Proxy lexical d'actualité déjà calculé (pas de BERT).",
    )


class SortieSante(BaseModel):
    """État du processus API et présence du fichier joblib."""

    statut: str
    modele_charge: bool


class SortiePrediction(BaseModel):
    """Prédiction de durée observée en minutes (pas un retard programmé)."""

    duree_minutes_predite: float
    cible: str
