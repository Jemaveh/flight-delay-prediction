"""
Tests du scoring de sentiment (sans téléchargement HuggingFace, sans réseau).
"""

from pathlib import Path

import pytest

from src.processing.scorer_sentiment import (
    agreger_polarite_par_jour,
    charger_articles,
    executer_scoring,
    polarite_depuis_scores,
    scorer_textes,
    texte_article,
)
from src.utils.chemins import RACINE_PROJET


def test_texte_article_concatene_titre_et_descriptif() -> None:
    """Vérifie que le champ content n'est pas requis pour former le texte."""
    assert texte_article("Grève", "Retards à CDG") == "Grève Retards à CDG"
    assert texte_article("Seul titre", None) == "Seul titre"
    assert texte_article(None, None) == ""


def test_polarite_positive_moins_negative() -> None:
    """Vérifie P(pos) − P(neg) borné dans [-1, 1]."""
    score = polarite_depuis_scores(
        [
            {"label": "positive", "score": 0.7},
            {"label": "neutral", "score": 0.2},
            {"label": "negative", "score": 0.1},
        ]
    )
    assert score == pytest.approx(0.6)


def test_charger_articles_filtre_le_prefixe_newsapi(tmp_path: Path) -> None:
    """Vérifie que seuls les fichiers newsapi_*.json sont lus."""
    brut = (RACINE_PROJET / "tests" / "fixtures" / "news_extrait.json").read_text(
        encoding="utf-8"
    )
    (tmp_path / "newsapi_20260823_test.json").write_text(brut, encoding="utf-8")
    (tmp_path / "autre.json").write_text(brut, encoding="utf-8")
    df = charger_articles(tmp_path)
    assert not df.empty
    assert set(df["date_id"]) <= {20260822, 20260823, 20260824}
    assert df["texte"].str.len().min() > 0


def test_agreger_polarite_par_jour_fait_la_moyenne() -> None:
    """Vérifie la moyenne des polarités par date_id."""
    import pandas as pd

    df = pd.DataFrame(
        {
            "date_id": [20260901, 20260901, 20260902],
            "polarite": [0.5, -0.5, 1.0],
        }
    )
    agregats = agreger_polarite_par_jour(df)
    assert agregats[20260901] == pytest.approx(0.0)
    assert agregats[20260902] == pytest.approx(1.0)


class _PipelineFactice:
    def __call__(self, textes, **_kwargs):
        sorties = []
        for texte in textes:
            if "strike" in texte.lower() or "grève" in texte.lower():
                sorties.append(
                    [
                        {"label": "negative", "score": 0.8},
                        {"label": "positive", "score": 0.1},
                        {"label": "neutral", "score": 0.1},
                    ]
                )
            else:
                sorties.append(
                    [
                        {"label": "positive", "score": 0.6},
                        {"label": "negative", "score": 0.2},
                        {"label": "neutral", "score": 0.2},
                    ]
                )
        return sorties


def test_executer_scoring_sans_huggingface_ni_sql(tmp_path: Path) -> None:
    """Vérifie le pipeline avec un classifieur factice, sans écriture SQL."""
    brut = (RACINE_PROJET / "tests" / "fixtures" / "news_extrait.json").read_text(
        encoding="utf-8"
    )
    (tmp_path / "newsapi_20260823_test.json").write_text(brut, encoding="utf-8")
    rapport = executer_scoring(
        dossier_raw=tmp_path,
        pipeline_hf=_PipelineFactice(),
        ecrire=False,
    )
    assert rapport["n_articles"] >= 1
    assert rapport["n_jours"] >= 1
    assert rapport["n_maj"] == 0
    assert rapport["agregats"]


def test_scorer_textes_delegue_au_pipeline() -> None:
    """Vérifie qu'un item unique (dict) et une liste de labels sont acceptés."""
    def pipe_dict(textes, **_kwargs):
        return [{"label": "positive", "score": 1.0} for _ in textes]

    assert scorer_textes(["ok"], pipe_dict) == [pytest.approx(1.0)]
