"""
Tests du ciblage actualités par hub (sans NewsAPI, sans HuggingFace).
"""

import pandas as pd
import pytest

from src.processing.actu_hub import (
    agreger_hub_jour,
    date_id_veille,
    exploser_articles_par_hub,
    flag_atc,
    flag_greve,
    icaos_cites,
)


def test_date_id_veille_traverse_le_mois() -> None:
    """Vérifie que le 1er du mois ne devient pas YYYYMM00."""
    assert date_id_veille(20260901) == 20260831


def test_icaos_cites_heathrow_pas_france() -> None:
    """Vérifie CDG/LHR et l'absence de faux positif FRA sur « France »."""
    assert "EGLL" in icaos_cites("Strike at Heathrow delays flights")
    assert "LFPG" in icaos_cites("Grève à CDG Roissy")
    assert icaos_cites("Travel news from France this week") == ()


def test_flags_greve_et_atc() -> None:
    """Vérifie les deux familles de flags sur des phrases courtes."""
    assert flag_greve("Airport strike at Heathrow")
    assert flag_atc("Air traffic control staff walk out")
    assert not flag_atc("Sunny weather in Spain")


def test_exploser_et_agreger(tmp_path=None) -> None:
    """Vérifie le grain date × ICAO après explosion."""
    articles = pd.DataFrame(
        {
            "date_id": [20260901, 20260901, 20260902],
            "title": ["Heathrow strike", "Unrelated", "CDG ATC delay"],
            "description": ["Workers walk out", "Markets", "Air traffic control"],
            "url": ["u1", "u2", "u3"],
            "texte": [
                "Heathrow strike Workers walk out",
                "Unrelated Markets",
                "CDG ATC delay Air traffic control",
            ],
            "polarite": [0.2, 0.0, -0.5],
        }
    )
    explose = exploser_articles_par_hub(articles)
    assert set(explose["icao"]) <= {"EGLL", "LFPG"}
    assert "u2" not in set(explose["url"])
    agregats = agreger_hub_jour(explose)
    heathrow = agregats.loc[
        (agregats["date_id"] == 20260901) & (agregats["icao"] == "EGLL")
    ]
    assert len(heathrow) == 1
    assert heathrow["flag_greve_hub"].iloc[0] == pytest.approx(1.0)


def test_exploser_utilise_icao_requete_meme_sans_alias_dans_le_texte() -> None:
    """Vérifie le tag code_icao de la requête --par-hub."""
    articles = pd.DataFrame(
        {
            "date_id": [20260901],
            "title": ["Generic delay news"],
            "description": ["No airport name"],
            "url": ["u-hub"],
            "texte": ["Generic delay news No airport name"],
            "icao_requete": ["LFPG"],
            "polarite": [0.0],
        }
    )
    explose = exploser_articles_par_hub(articles)
    assert list(explose["icao"]) == ["LFPG"]


def test_agreger_jour_global_flags() -> None:
    """Vérifie un flag grève journalier sans filtre hub."""
    from src.processing.actu_hub import agreger_jour_global

    articles = pd.DataFrame(
        {
            "date_id": [20260901, 20260901],
            "url": ["a", "b"],
            "texte": ["Airport strike delays", "Markets close mixed"],
            "polarite": [-0.4, 0.1],
        }
    )
    jour = agreger_jour_global(articles)
    assert len(jour) == 1
    assert jour["flag_greve_jour"].iloc[0] == pytest.approx(1.0)
    assert jour["nb_articles_jour"].iloc[0] == 2
