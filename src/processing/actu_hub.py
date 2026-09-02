"""
Actualités ciblées par hub : filtre lexical, flags grève/ATC, grain (date, ICAO).

Aucun appel NewsAPI. Sert à l'expérience `src.models.experience_actu`,
pas à l'API FastAPI.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pandas as pd

from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES
from src.processing.data_cleaning import _sans_accents, normaliser_titre

# Alias assez spécifiques : pas « paris » / « london » seuls (trop de bruit).
ALIAS_HUB: dict[str, tuple[str, ...]] = {
    "LFPG": ("cdg", "lfpg", "charles de gaulle", "charles-de-gaulle", "roissy"),
    "EGLL": ("lhr", "egll", "heathrow"),
    "EDDF": (
        "eddf",
        "frankfurt",
        "francfort",
        "flughafen frankfurt",
    ),
    "EHAM": ("ams", "eham", "schiphol"),
    "LEMD": ("mad", "lemd", "barajas"),
    "LIRF": ("fco", "lirf", "fiumicino"),
    "LTFM": ("ist", "ltfm", "istanbul airport", "aeroport istanbul"),
    "EIDW": ("dub", "eidw", "dublin airport", "aeroport dublin"),
    "EDDM": ("muc", "eddm", "munich airport", "flughafen munchen", "aeroport munich"),
    "LEBL": ("bcn", "lebl", "el prat", "barcelona airport", "aeroport barcelone"),
}

PHRASES_ATC = (
    "air traffic",
    "air traffic control",
    "controle aerien",
    "control aereo",
    "controllo del traffico",
    "fluglots",
    "airspace",
    "espace aerien",
)
PHRASES_GREVE = (
    "airport strike",
    "greve aeroport",
    "greve aéroport",
    "flughafen streik",
    "huelga aeropuerto",
    "sciopero aeroporto",
    "atc strike",
    "greve controle",
)
STEMS_GREVE = ("greve", "strike", "huelga", "sciopero", "streik")
STEMS_ATC = ("fluglots", "ansp")


def date_id_veille(date_id: int) -> int:
    """
    Passe YYYYMMDD au calendrier de la veille (ne pas faire date_id - 1).
    """
    jour = datetime.strptime(str(int(date_id)), "%Y%m%d")
    return int((jour - timedelta(days=1)).strftime("%Y%m%d"))


def _texte_normalise(texte: str) -> str:
    return _sans_accents(normaliser_titre(texte))


def _contient_alias(texte_norm: str, alias: str) -> bool:
    alias_n = _texte_normalise(alias)
    if not alias_n:
        return False
    if len(alias_n) <= 3:
        return (
            re.search(
                rf"(?<![a-z0-9]){re.escape(alias_n)}(?![a-z0-9])",
                texte_norm,
            )
            is not None
        )
    return alias_n in texte_norm


def icaos_cites(texte: str) -> tuple[str, ...]:
    """
    ICAO des hubs dont un alias figure dans le titre ou le descriptif.
    """
    normalise = _texte_normalise(texte)
    if not normalise:
        return ()
    cites: list[str] = []
    for hub in HUBS_AEROPORTUAIRES:
        for alias in ALIAS_HUB.get(hub.code_icao, ()):
            if _contient_alias(normalise, alias):
                cites.append(hub.code_icao)
                break
    return tuple(cites)


def flag_greve(texte: str) -> bool:
    """True si le texte évoque une grève (phrases ou stems)."""
    normalise = _texte_normalise(texte)
    if any(_texte_normalise(p) in normalise for p in PHRASES_GREVE):
        return True
    return any(
        jeton.startswith(stem) for jeton in normalise.split() for stem in STEMS_GREVE
    )


def flag_atc(texte: str) -> bool:
    """True si le texte évoque le contrôle aérien / l'espace aérien."""
    normalise = _texte_normalise(texte)
    if " atc " in f" {normalise} " or normalise.startswith("atc ") or normalise.endswith(" atc"):
        return True
    if any(_texte_normalise(p) in normalise for p in PHRASES_ATC):
        return True
    return any(
        jeton.startswith(stem) for jeton in normalise.split() for stem in STEMS_ATC
    )


def exploser_articles_par_hub(articles: pd.DataFrame) -> pd.DataFrame:
    """
    Une ligne par (article, hub cité). Les articles sans hub sont écartés.
    """
    if articles.empty:
        return pd.DataFrame(
            columns=[
                "date_id",
                "icao",
                "url",
                "flag_greve",
                "flag_atc",
                "polarite",
            ]
        )
    lignes: list[dict] = []
    for ligne in articles.itertuples(index=False):
        texte = getattr(ligne, "texte", "") or ""
        if not texte:
            titre = getattr(ligne, "title", "") or ""
            descr = getattr(ligne, "description", "") or ""
            texte = f"{titre} {descr}".strip()
        polarite = getattr(ligne, "polarite", None)
        icao_requete = getattr(ligne, "icao_requete", None)
        if icao_requete is not None and not (
            isinstance(icao_requete, float) and pd.isna(icao_requete)
        ):
            icaos = (str(icao_requete),)
        else:
            icaos = icaos_cites(texte)
        for icao in icaos:
            lignes.append(
                {
                    "date_id": int(ligne.date_id),
                    "icao": icao,
                    "url": getattr(ligne, "url", None),
                    "flag_greve": flag_greve(texte),
                    "flag_atc": flag_atc(texte),
                    "polarite": polarite,
                }
            )
    return pd.DataFrame(lignes)


def agreger_hub_jour(explose: pd.DataFrame) -> pd.DataFrame:
    """
    Grain (date_id, icao) : effectifs et flags max, polarité moyenne si présente.
    """
    if explose.empty:
        return pd.DataFrame(
            columns=[
                "date_id",
                "icao",
                "nb_articles_hub",
                "flag_greve_hub",
                "flag_atc_hub",
                "score_bert_hub",
            ]
        )
    travail = explose.copy()
    travail["flag_greve"] = travail["flag_greve"].astype(bool)
    travail["flag_atc"] = travail["flag_atc"].astype(bool)
    agregats = (
        travail.groupby(["date_id", "icao"], as_index=False)
        .agg(
            nb_articles_hub=("url", "count"),
            flag_greve_hub=("flag_greve", "max"),
            flag_atc_hub=("flag_atc", "max"),
            score_bert_hub=("polarite", "mean"),
        )
    )
    agregats["flag_greve_hub"] = agregats["flag_greve_hub"].astype(float)
    agregats["flag_atc_hub"] = agregats["flag_atc_hub"].astype(float)
    return agregats


def agreger_jour_global(articles: pd.DataFrame) -> pd.DataFrame:
    """
    Grain date_id sur tous les articles (pas de filtre hub) : flags et polarité.
    """
    if articles.empty:
        return pd.DataFrame(
            columns=[
                "date_id",
                "nb_articles_jour",
                "flag_greve_jour",
                "flag_atc_jour",
                "score_bert_jour",
            ]
        )
    travail = articles.copy()
    if "texte" not in travail.columns:
        travail["texte"] = [
            f"{t or ''} {d or ''}".strip()
            for t, d in zip(
                travail["title"] if "title" in travail.columns else [""] * len(travail),
                travail["description"]
                if "description" in travail.columns
                else [""] * len(travail),
            )
        ]
    travail["flag_greve"] = travail["texte"].map(flag_greve)
    travail["flag_atc"] = travail["texte"].map(flag_atc)
    if "polarite" not in travail.columns:
        travail["polarite"] = pd.NA
    agregats = (
        travail.groupby("date_id", as_index=False)
        .agg(
            nb_articles_jour=("url", "count"),
            flag_greve_jour=("flag_greve", "max"),
            flag_atc_jour=("flag_atc", "max"),
            score_bert_jour=("polarite", "mean"),
        )
    )
    agregats["flag_greve_jour"] = agregats["flag_greve_jour"].astype(float)
    agregats["flag_atc_jour"] = agregats["flag_atc_jour"].astype(float)
    return agregats
