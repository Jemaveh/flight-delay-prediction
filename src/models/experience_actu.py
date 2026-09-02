"""
Expérience actualités : agrégats hub × jour, flags grève/ATC, J−1.

Aucun appel NewsAPI. N'écrit pas models/modele_vol_meteo.joblib.
"""

from __future__ import annotations

import argparse
from datetime import datetime

import pandas as pd

from src.models.entrainer import (
    comparer_a_la_baseline,
    entrainer_lightgbm,
    evaluer_regression,
    predire_baseline_mediane,
    predire_baseline_mediane_horaire,
)
from src.models.jeu import (
    COLONNES_CATEGORIELLES,
    COLONNES_FEATURES,
    FRACTION_TRAIN_DEFAUT,
    SEUIL_MIN_LIGNES_ENTRAINEMENT,
    ajouter_cible_duree,
    aligner_categories,
    charger_vols_meteo,
    exclure_durees_aberrantes,
    filtrer_jeu_modele,
    split_temporel,
)
from src.processing.actu_hub import (
    agreger_hub_jour,
    agreger_jour_global,
    date_id_veille,
    exploser_articles_par_hub,
)
from src.processing.etl import DOSSIER_RAW_DEFAUT
from src.processing.scorer_sentiment import charger_articles, scorer_textes
from src.utils.logger import get_logger

logger = get_logger(__name__)

COLONNES_EXPERIENCE_ACTU = (
    "nb_articles_hub",
    "flag_greve_hub",
    "flag_atc_hub",
    "score_bert_hub",
    "nb_articles_hub_j1",
    "flag_greve_hub_j1",
    "flag_atc_hub_j1",
    "score_bert_hub_j1",
    "nb_articles_jour",
    "flag_greve_jour",
    "flag_atc_jour",
    "score_bert_jour",
    "nb_articles_jour_j1",
    "flag_greve_jour_j1",
    "flag_atc_jour_j1",
    "score_bert_jour_j1",
)


def _colonnes_actu_vides() -> dict[str, float]:
    return {nom: 0.0 for nom in COLONNES_EXPERIENCE_ACTU}


def joindre_actu_hub(
    vols: pd.DataFrame,
    agregats_hub: pd.DataFrame,
    agregats_jour: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Joint les agrégats (date, ICAO origine) au jour J et à la veille.
    """
    travail = vols.copy()
    travail["icao_origine"] = travail["est_departure_airport"]
    travail["date_id_veille"] = travail["date_id"].map(date_id_veille)
    if not agregats_hub.empty:
        jour_hub = agregats_hub.rename(columns={"icao": "icao_origine"})
        veille_hub = agregats_hub.rename(
            columns={
                "icao": "icao_origine",
                "date_id": "date_id_veille_src",
                "nb_articles_hub": "nb_articles_hub_j1",
                "flag_greve_hub": "flag_greve_hub_j1",
                "flag_atc_hub": "flag_atc_hub_j1",
                "score_bert_hub": "score_bert_hub_j1",
            }
        )
        travail = travail.merge(jour_hub, how="left", on=["date_id", "icao_origine"])
        travail = travail.merge(
            veille_hub,
            how="left",
            left_on=["date_id_veille", "icao_origine"],
            right_on=["date_id_veille_src", "icao_origine"],
        )
    if agregats_jour is not None and not agregats_jour.empty:
        jour = agregats_jour.rename(
            columns={
                "nb_articles_jour": "nb_articles_jour",
                "flag_greve_jour": "flag_greve_jour",
                "flag_atc_jour": "flag_atc_jour",
                "score_bert_jour": "score_bert_jour",
            }
        )
        veille = agregats_jour.rename(
            columns={
                "date_id": "date_id_veille_jour",
                "nb_articles_jour": "nb_articles_jour_j1",
                "flag_greve_jour": "flag_greve_jour_j1",
                "flag_atc_jour": "flag_atc_jour_j1",
                "score_bert_jour": "score_bert_jour_j1",
            }
        )
        travail = travail.merge(jour, how="left", on="date_id")
        travail = travail.merge(
            veille,
            how="left",
            left_on="date_id_veille",
            right_on="date_id_veille_jour",
        )
    for nom in COLONNES_EXPERIENCE_ACTU:
        if nom not in travail.columns:
            travail[nom] = 0.0
        travail[nom] = pd.to_numeric(travail[nom], errors="coerce").fillna(0.0)
    return travail


def masque_signal_actu(df: pd.DataFrame) -> pd.Series:
    """Au moins un article (hub ou jour) au jour J ou J−1."""

    def positif(nom: str) -> pd.Series:
        if nom not in df.columns:
            return pd.Series(False, index=df.index)
        return pd.to_numeric(df[nom], errors="coerce").fillna(0) > 0

    return (
        positif("nb_articles_hub")
        | positif("nb_articles_hub_j1")
        | positif("nb_articles_jour")
        | positif("nb_articles_jour_j1")
        | positif("flag_greve_hub")
        | positif("flag_atc_hub")
        | positif("flag_greve_jour")
        | positif("flag_atc_jour")
    )


def split_test_avec_signal(
    df: pd.DataFrame,
    fraction_train: float = FRACTION_TRAIN_DEFAUT,
    n_test_min: int = 50,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    Split temporel, puis le test ne garde que les lignes avec signal actu hub.

    Si le test devient trop petit : split temporel **parmi** les lignes déjà
    pourvues de signal (train et test ont alors des news hub).
    """
    train, test = split_temporel(df, fraction_train=fraction_train)
    test_signal = test.loc[masque_signal_actu(test)].copy()
    if len(test_signal) >= n_test_min:
        return train, test_signal, "temporel_puis_test_filtre_signal"
    avec_signal = df.loc[masque_signal_actu(df)].copy()
    if len(avec_signal) < SEUIL_MIN_LIGNES_ENTRAINEMENT + n_test_min:
        raise ValueError(
            "Pas assez de vols avec actualité hub (J ou J-1) pour un split "
            f"({len(avec_signal)} lignes)."
        )
    train2, test2 = split_temporel(avec_signal, fraction_train=fraction_train)
    return train2, test2, "temporel_sur_lignes_avec_signal"


def _matrice(
    cadre: pd.DataFrame,
    avec_experience: bool,
) -> tuple[pd.DataFrame, pd.Series]:
    from src.models.jeu import NOM_CIBLE, _heure_utc

    travail = cadre.copy()
    travail["hub_origine"] = travail["est_departure_airport"]
    travail["heure_utc"] = _heure_utc(travail["first_seen"])
    colonnes = list(COLONNES_FEATURES)
    if avec_experience:
        colonnes.extend(COLONNES_EXPERIENCE_ACTU)
    X = travail.loc[:, colonnes].copy()
    for colonne in colonnes:
        if colonne in COLONNES_CATEGORIELLES:
            continue
        X[colonne] = pd.to_numeric(X[colonne], errors="coerce")
    y = travail[NOM_CIBLE].astype("float64")
    y.index = X.index
    return X, y


def evaluer_variante(
    train: pd.DataFrame,
    test: pd.DataFrame,
    avec_experience: bool,
) -> dict:
    X_train, y_train = _matrice(train, avec_experience)
    X_test, y_test = _matrice(test, avec_experience)
    X_train, X_test = aligner_categories(X_train, X_test)
    modele = entrainer_lightgbm(X_train, y_train)
    pred = modele.predict(X_test)
    pred_med = predire_baseline_mediane(y_train, len(y_test))
    pred_h = predire_baseline_mediane_horaire(
        y_train, X_train["heure_utc"], X_test["heure_utc"]
    )
    m_mod = evaluer_regression(y_test, pred)
    m_med = evaluer_regression(y_test, pred_med)
    m_h = evaluer_regression(y_test, pred_h)
    importances = {}
    if hasattr(modele, "feature_importances_"):
        importances = {
            nom: int(score)
            for nom, score in zip(X_train.columns, modele.feature_importances_)
        }
    return {
        "avec_experience": avec_experience,
        "n_train": int(len(X_train)),
        "n_test": int(len(X_test)),
        "metriques_modele": m_mod,
        "metriques_baseline": m_med,
        "metriques_baseline_horaire": m_h,
        "bat_la_baseline": comparer_a_la_baseline(m_mod, m_med),
        "bat_la_baseline_horaire": comparer_a_la_baseline(m_mod, m_h),
        "importance_features": importances,
    }


def executer_experience(
    avec_bert: bool = False,
    pipeline_hf=None,
) -> dict:
    """
    Charge l'entrepôt + JSON NewsAPI locaux, joint hub/J−1, compare LightGBM.
    """
    vols = charger_vols_meteo()
    articles = charger_articles(DOSSIER_RAW_DEFAUT)
    n_articles = int(len(articles))
    if avec_bert and not articles.empty:
        if pipeline_hf is None:
            from src.processing.scorer_sentiment import charger_pipeline_sentiment

            pipeline_hf = charger_pipeline_sentiment()
        articles = articles.copy()
        articles["polarite"] = scorer_textes(articles["texte"].tolist(), pipeline_hf)
    explose = exploser_articles_par_hub(articles)
    agregats_hub = agreger_hub_jour(explose)
    agregats_jour = agreger_jour_global(articles)
    logger.info(
        "Articles bruts %s, lignes article×hub %s, couples jour×hub %s, jours globaux %s.",
        n_articles,
        len(explose),
        len(agregats_hub),
        len(agregats_jour),
    )
    enrichi = joindre_actu_hub(vols, agregats_hub, agregats_jour)
    filtre = exclure_durees_aberrantes(
        ajouter_cible_duree(filtrer_jeu_modele(enrichi))
    )
    train, test, mode_split = split_test_avec_signal(filtre)
    logger.info(
        "Split expérience (%s) : train=%s, test=%s, test avec signal=%s.",
        mode_split,
        len(train),
        len(test),
        int(masque_signal_actu(test).sum()),
    )
    sans = evaluer_variante(train, test, avec_experience=False)
    avec = evaluer_variante(train, test, avec_experience=True)
    rapport = {
        "n_articles_json": n_articles,
        "n_article_hub": int(len(explose)),
        "n_couples_jour_hub": int(len(agregats_hub)),
        "n_jours_globaux": int(len(agregats_jour)),
        "mode_split": mode_split,
        "fin_train": pd.to_datetime(train["first_seen"], utc=True).max().isoformat(),
        "debut_test": pd.to_datetime(test["first_seen"], utc=True).min().isoformat(),
        "sans_experience": sans,
        "avec_experience": avec,
        "date_experience": datetime.now().astimezone().isoformat(),
    }
    logger.info(
        "Expérience actu hub. Sans : RMSE=%.2f vs médiane=%.2f / horaire=%.2f. "
        "Avec hub/J-1/flags : RMSE=%.2f vs médiane=%.2f / horaire=%.2f. "
        "Bat médiane : %s.",
        sans["metriques_modele"]["rmse"],
        sans["metriques_baseline"]["rmse"],
        sans["metriques_baseline_horaire"]["rmse"],
        avec["metriques_modele"]["rmse"],
        avec["metriques_baseline"]["rmse"],
        avec["metriques_baseline_horaire"]["rmse"],
        avec["bat_la_baseline"],
    )
    return rapport


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(
        description=(
            "Expérience NewsAPI locale : hub×jour, flags, J-1, test avec signal. "
            "Pas d'appel API. N'écrase pas le joblib de production."
        )
    )
    parser.add_argument(
        "--avec-bert",
        action="store_true",
        help="Rescore DistilBERT sur les articles avant agrégation hub (CPU).",
    )
    args = parser.parse_args(argv)
    return executer_experience(avec_bert=args.avec_bert)


if __name__ == "__main__":
    main()
