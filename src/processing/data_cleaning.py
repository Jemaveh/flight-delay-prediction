"""
Nettoyage des extraits JSON des trois sources, avant chargement en base.

Les règles reprennent celles identifiées dans les notebooks d'exploration,
adaptées au grain des endpoints /flights/departure et /flights/arrival pour
les vols (aéroports nuls, callsign vide, lastSeen < firstSeen, doublons).
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

import pandas as pd

from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES

PLAFOND_VISIBILITE_M = 10_000
ICAO_PAR_IATA: dict[str, str] = {hub.code_iata: hub.code_icao for hub in HUBS_AEROPORTUAIRES}


def charger_json(chemin: str | Path) -> Any:
    """
    Lit un fichier JSON UTF-8 et en retourne le contenu Python.
    """
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


def _texte_ou_manquant(valeur: Any) -> str | None:
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    texte = str(valeur).strip()
    return texte if texte else None


def aplatir_vols(donnees: list | dict) -> pd.DataFrame:
    """
    Met à plat une réponse /flights/departure ou /flights/arrival.

    Accepte une liste brute OpenSky ou une enveloppe `{"vols": [...]}`.
    """
    if isinstance(donnees, dict):
        vols = donnees.get("vols", [])
    else:
        vols = donnees
    if not vols:
        return pd.DataFrame(
            columns=[
                "icao24",
                "callsign",
                "first_seen",
                "last_seen",
                "est_departure_airport",
                "est_arrival_airport",
            ]
        )
    df = pd.DataFrame(vols)
    df = df.rename(
        columns={
            "firstSeen": "first_seen",
            "lastSeen": "last_seen",
            "estDepartureAirport": "est_departure_airport",
            "estArrivalAirport": "est_arrival_airport",
        }
    )
    for colonne in (
        "icao24",
        "callsign",
        "first_seen",
        "last_seen",
        "est_departure_airport",
        "est_arrival_airport",
    ):
        if colonne not in df.columns:
            df[colonne] = pd.NA
    return df


def nettoyer_vols(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Applique les règles de nettoyage des vols departure/arrival.

    Returns
    -------
    tuple[pd.DataFrame, dict[str, int]]
        Le DataFrame conservé et un bilan (lues, rejetees, conservées).
    """
    lues = len(df)
    travail = df.copy()

    travail["icao24"] = travail["icao24"].map(_texte_ou_manquant)
    travail["callsign"] = travail["callsign"].map(_texte_ou_manquant)
    travail["est_departure_airport"] = travail["est_departure_airport"].map(_texte_ou_manquant)
    travail["est_arrival_airport"] = travail["est_arrival_airport"].map(_texte_ou_manquant)

    travail["first_seen"] = pd.to_numeric(travail["first_seen"], errors="coerce")
    travail["last_seen"] = pd.to_numeric(travail["last_seen"], errors="coerce")

    masque_identifiant = travail["icao24"].notna() & travail["first_seen"].notna()
    masque_aeroport = (
        travail["est_departure_airport"].notna() | travail["est_arrival_airport"].notna()
    )
    masque_chrono = travail["last_seen"].isna() | (
        travail["last_seen"] >= travail["first_seen"]
    )

    travail = travail.loc[masque_identifiant & masque_aeroport & masque_chrono].copy()
    travail = travail.drop_duplicates(
        subset=["icao24", "first_seen", "est_departure_airport"],
        keep="first",
    )

    conserves = len(travail)
    bilan = {
        "lues": lues,
        "rejetees": lues - conserves,
        "conservees": conserves,
    }
    return travail.reset_index(drop=True), bilan


def aplatir_meteo(donnees: dict) -> pd.DataFrame:
    """
    Met à plat une capture OpenWeather multi-hubs (`{"hubs": [...]}`).
    """
    lignes: list[dict] = []
    for hub in donnees.get("hubs") or []:
        meteo = hub.get("meteo") or {}
        main = meteo.get("main") or {}
        wind = meteo.get("wind") or {}
        rain = meteo.get("rain") or {}
        weather0 = (meteo.get("weather") or [{}])[0]
        code_iata = hub.get("code_iata")
        code_icao = hub.get("code_icao") or ICAO_PAR_IATA.get(code_iata)
        lignes.append(
            {
                "code_iata": code_iata,
                "code_icao": code_icao,
                "dt": meteo.get("dt"),
                "temperature_celsius": main.get("temp"),
                "feels_like_celsius": main.get("feels_like"),
                "humidity": main.get("humidity"),
                "pressure": main.get("pressure"),
                "wind_speed": wind.get("speed"),
                "wind_gust": wind.get("gust"),
                "rain_1h": rain.get("1h"),
                "visibility": meteo.get("visibility"),
                "description_ciel": weather0.get("description"),
            }
        )
    return pd.DataFrame(lignes)


def nettoyer_meteo(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Remplace l'absence structurelle de rain.1h / wind.gust par 0 et plafonne
    la visibilité à 10 000 m.
    """
    lues = len(df)
    travail = df.copy()
    if travail.empty:
        return travail, {"lues": 0, "rejetees": 0, "conservees": 0}

    for colonne in ("rain_1h", "wind_gust"):
        if colonne not in travail.columns:
            travail[colonne] = 0.0
        else:
            travail[colonne] = pd.to_numeric(travail[colonne], errors="coerce").fillna(0.0)

    if "visibility" in travail.columns:
        visibilite = pd.to_numeric(travail["visibility"], errors="coerce")
        travail["visibility"] = visibilite.clip(upper=PLAFOND_VISIBILITE_M)

    travail = travail.dropna(subset=["code_iata", "dt"])
    conserves = len(travail)
    return travail.reset_index(drop=True), {
        "lues": lues,
        "rejetees": lues - conserves,
        "conservees": conserves,
    }


def normaliser_titre(titre: str | None) -> str:
    """
    Normalise un titre d'article (minuscules, ponctuation retirée) pour la
    déduplication.
    """
    if not titre:
        return ""
    texte = titre.casefold()
    texte = re.sub(r"[^\w\s]", " ", texte, flags=re.UNICODE)
    return re.sub(r"\s+", " ", texte).strip()


def _sans_accents(texte: str) -> str:
    decompose = unicodedata.normalize("NFD", texte)
    return "".join(c for c in decompose if unicodedata.category(c) != "Mn")


# Stems FR/EN/DE/ES/IT déjà présents dans les mots-clés de collecte NewsAPI.
STEMS_PERTURBATION_ACTU = (
    "greve",
    "strike",
    "delay",
    "retard",
    "huelga",
    "sciopero",
    "streik",
    "closur",
    "perturb",
    "verspat",
    "retraso",
    "ritardo",
    "versptaet",
)


def proxy_perturbation_texte(texte: str | None) -> float:
    """
    Polarité lexicale simple (0–1) : part des jetons dont le stem évoque
    une perturbation aérienne. Pas de BERT, pas d'appel réseau.
    """
    normalise = _sans_accents(normaliser_titre(texte))
    if not normalise:
        return 0.0
    jetons = normalise.split()
    if not jetons:
        return 0.0
    hits = 0
    for jeton in jetons:
        if any(jeton.startswith(stem) for stem in STEMS_PERTURBATION_ACTU):
            hits += 1
    return hits / len(jetons)


def aplatir_actualites(donnees: dict) -> pd.DataFrame:
    """
    Met à plat une capture NewsAPI (`{"requetes": [...]}`) sans le champ content.
    """
    lignes: list[dict] = []
    for requete in donnees.get("requetes") or []:
        resultat = requete.get("resultat") or {}
        for article in resultat.get("articles") or []:
            lignes.append(
                {
                    "mots_cles": requete.get("mots_cles"),
                    "langue_requete": requete.get("langue_requete"),
                    "icao_requete": requete.get("code_icao"),
                    "title": article.get("title"),
                    "description": article.get("description"),
                    "url": article.get("url"),
                    "published_at": article.get("publishedAt"),
                }
            )
    return pd.DataFrame(lignes)


def nettoyer_actualites(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Exclut le contenu tronqué (déjà absent après aplatir) et déduplique sur
    l'URL puis sur le titre normalisé.
    """
    lues = len(df)
    travail = df.copy()
    if "content" in travail.columns:
        travail = travail.drop(columns=["content"])
    if travail.empty:
        return travail, {"lues": 0, "rejetees": 0, "conservees": 0}

    travail["url"] = travail["url"].map(_texte_ou_manquant)
    travail = travail.dropna(subset=["url"])
    travail = travail.drop_duplicates(subset=["url"], keep="first")
    travail["titre_normalise"] = travail["title"].map(normaliser_titre)
    travail = travail.drop_duplicates(subset=["titre_normalise"], keep="first")
    travail = travail.drop(columns=["titre_normalise"])

    conserves = len(travail)
    return travail.reset_index(drop=True), {
        "lues": lues,
        "rejetees": lues - conserves,
        "conservees": conserves,
    }
