"""
Score de sentiment DistilBERT, agrégé par jour UTC dans dim_news_sentiment.

Lit les JSON NewsAPI déjà présents dans data/raw/ (aucun appel à l'API).
Le pipeline HuggingFace n'est chargé qu'à l'exécution CLI, pas par l'API
FastAPI ni par l'entraînement LightGBM.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from src.database.db_connector import creer_engine
from src.processing.data_cleaning import (
    aplatir_actualites,
    charger_json,
    nettoyer_actualites,
)
from src.processing.etl import DOSSIER_RAW_DEFAUT, date_id_depuis
from src.utils.chemins import chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

# DistilBERT multilingue (FR/EN), ~250 Mo de poids, inférence CPU.
MODELE_SENTIMENT_DEFAUT = (
    "lxyuan/distilbert-base-multilingual-cased-sentiments-student"
)
TAILLE_LOT = 8
LONGUEUR_MAX_JETONS = 256

SQL_MAJ_SCORE = """
UPDATE dim_news_sentiment
SET score_sentiment = :score_sentiment
WHERE date_id = :date_id
"""


def texte_article(titre: object, description: object) -> str:
    """
    Concatène titre et descriptif déjà stockés (pas le champ content tronqué).
    """
    parties: list[str] = []
    for valeur in (titre, description):
        if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
            continue
        texte = str(valeur).strip()
        if texte:
            parties.append(texte)
    return " ".join(parties)


def polarite_depuis_scores(scores: list[dict[str, Any]]) -> float:
    """
    Polarité dans [-1, 1] : P(positive) − P(negative). Neutral n'entre pas.
    """
    positif = 0.0
    negatif = 0.0
    for item in scores:
        etiquette = str(item.get("label", "")).lower()
        proba = float(item.get("score", 0.0))
        if "pos" in etiquette or etiquette in {"5 stars", "4 stars"}:
            positif += proba
        elif "neg" in etiquette or etiquette in {"1 star", "2 stars"}:
            negatif += proba
    return float(max(-1.0, min(1.0, positif - negatif)))


def charger_articles(dossier: Path) -> pd.DataFrame:
    """
    Reconstitue les articles nettoyés depuis tous les newsapi_*.json du dossier.
    """
    fichiers = sorted(dossier.glob("newsapi_*.json"))
    if not fichiers:
        return pd.DataFrame()
    cadres: list[pd.DataFrame] = []
    for chemin in fichiers:
        brut = charger_json(chemin)
        plat = aplatir_actualites(brut)
        propre, _bilan = nettoyer_actualites(plat)
        if not propre.empty:
            cadres.append(propre)
    if not cadres:
        return pd.DataFrame()
    df, _bilan = nettoyer_actualites(pd.concat(cadres, ignore_index=True))
    instants = pd.to_datetime(df["published_at"], utc=True, errors="coerce")
    df = df.assign(published_at=instants).dropna(subset=["published_at"])
    df["date_id"] = df["published_at"].map(
        lambda instant: date_id_depuis(instant.to_pydatetime())
    )
    df["texte"] = [
        texte_article(titre, descr)
        for titre, descr in zip(df.get("title", []), df.get("description", []))
    ]
    return df.loc[df["texte"].str.len() > 0].copy()


def scorer_textes(
    textes: list[str],
    pipeline_hf: Callable[..., Any],
    taille_lot: int = TAILLE_LOT,
) -> list[float]:
    """
    Applique le pipeline text-classification (tous les labels) aux textes.
    """
    if not textes:
        return []
    brut = pipeline_hf(
        textes,
        batch_size=taille_lot,
        truncation=True,
        max_length=LONGUEUR_MAX_JETONS,
    )
    polarites: list[float] = []
    for item in brut:
        if isinstance(item, dict):
            polarites.append(polarite_depuis_scores([item]))
        else:
            polarites.append(polarite_depuis_scores(list(item)))
    return polarites


def agreger_polarite_par_jour(df: pd.DataFrame) -> dict[int, float]:
    """
    Moyenne des polarités d'articles par date_id.
    """
    if df.empty or "polarite" not in df.columns:
        return {}
    moyennes = df.groupby("date_id", sort=True)["polarite"].mean()
    return {int(date_id): float(score) for date_id, score in moyennes.items()}


def ecrire_scores(
    agregats: dict[int, float],
    engine: Engine | None = None,
) -> int:
    """
    Met à jour score_sentiment pour les date_id déjà présents en dimension.
    """
    if not agregats:
        return 0
    moteur = engine if engine is not None else creer_engine()
    maj = 0
    with moteur.begin() as connexion:
        for date_id, score in agregats.items():
            resultat = connexion.execute(
                text(SQL_MAJ_SCORE),
                {"date_id": date_id, "score_sentiment": score},
            )
            maj += int(resultat.rowcount or 0)
    return maj


def charger_pipeline_sentiment(nom_modele: str = MODELE_SENTIMENT_DEFAUT):
    """
    Charge le pipeline HuggingFace sur CPU. Import local : l'API ne l'importe pas.
    """
    from transformers import pipeline as pipeline_hf

    logger.info("Chargement du modèle de sentiment '%s' (CPU).", nom_modele)
    return pipeline_hf(
        "text-classification",
        model=nom_modele,
        top_k=None,
        truncation=True,
        device=-1,
    )


def executer_scoring(
    dossier_raw: Path | None = None,
    engine: Engine | None = None,
    pipeline_hf: Callable[..., Any] | None = None,
    nom_modele: str = MODELE_SENTIMENT_DEFAUT,
    ecrire: bool = True,
) -> dict:
    """
    Score les articles bruts, agrège par jour, optionnellement écrit en base.
    """
    dossier = dossier_raw if dossier_raw is not None else DOSSIER_RAW_DEFAUT
    articles = charger_articles(dossier)
    if articles.empty:
        logger.info("Aucun article NewsAPI à scorer dans %s.", dossier)
        return {"n_articles": 0, "n_jours": 0, "n_maj": 0, "agregats": {}}

    pipe = pipeline_hf if pipeline_hf is not None else charger_pipeline_sentiment(
        nom_modele
    )
    articles = articles.copy()
    articles["polarite"] = scorer_textes(articles["texte"].tolist(), pipe)
    agregats = agreger_polarite_par_jour(articles)
    n_maj = 0
    if ecrire:
        try:
            n_maj = ecrire_scores(agregats, engine=engine)
        except OperationalError as erreur:
            logger.error("PostgreSQL injoignable pour la mise à jour BERT.")
            raise RuntimeError(
                "PostgreSQL injoignable : impossible d'écrire score_sentiment."
            ) from erreur
    logger.info(
        "Sentiment : %s articles, %s jours, %s lignes dim_news_sentiment mises à jour.",
        len(articles),
        len(agregats),
        n_maj,
    )
    return {
        "n_articles": int(len(articles)),
        "n_jours": int(len(agregats)),
        "n_maj": int(n_maj),
        "agregats": agregats,
    }


def construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Score DistilBERT des JSON NewsAPI locaux, moyenne par jour UTC, "
            "UPDATE dim_news_sentiment.score_sentiment. Pas d'appel NewsAPI."
        )
    )
    parser.add_argument(
        "--modele",
        default=MODELE_SENTIMENT_DEFAUT,
        help="Identifiant HuggingFace du modèle de classification.",
    )
    parser.add_argument(
        "--sans-ecriture",
        action="store_true",
        help="Calcule les agrégats sans UPDATE SQL.",
    )
    return parser


def main(argv: list[str] | None = None) -> dict:
    args = construire_parser().parse_args(argv)
    try:
        return executer_scoring(
            nom_modele=args.modele,
            ecrire=not args.sans_ecriture,
        )
    except RuntimeError as erreur:
        logger.error("%s", erreur)
        raise SystemExit(1) from erreur


if __name__ == "__main__":
    main()
