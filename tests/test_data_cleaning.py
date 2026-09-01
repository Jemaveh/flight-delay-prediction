"""
Tests unitaires du nettoyage des trois sources (src/processing/data_cleaning.py).

Les fixtures JSON sont des extraits locaux : aucun appel réseau, aucun secret.
"""

import pandas as pd

from src.processing.data_cleaning import (
    aplatir_actualites,
    aplatir_meteo,
    aplatir_vols,
    charger_json,
    nettoyer_actualites,
    nettoyer_meteo,
    nettoyer_vols,
    normaliser_titre,
    proxy_perturbation_texte,
)
from src.utils.chemins import RACINE_PROJET

DOSSIER_FIXTURES = RACINE_PROJET / "tests" / "fixtures"


def test_nettoyer_vols_rejette_doublons_chrono_et_aeroports_tous_nuls() -> None:
    """
    Vérifie le rejet des doublons, des lastSeen < firstSeen et des vols sans
    aucun aéroport, tout en conservant un vol sans destination (en cours).
    """
    brut = charger_json(DOSSIER_FIXTURES / "vols_depart_extrait.json")
    plat = aplatir_vols(brut)
    propre, bilan = nettoyer_vols(plat)

    assert bilan["lues"] == 5
    assert len(propre) == 2
    assert set(propre["icao24"]) == {"abc123", "def456"}
    assert propre.loc[propre["icao24"] == "abc123", "callsign"].iloc[0] == "AFR123"
    dest_en_cours = propre.loc[propre["icao24"] == "def456", "est_arrival_airport"].iloc[0]
    assert pd.isna(dest_en_cours) or dest_en_cours is None


def test_aplatir_vols_accepte_enveloppe_et_liste() -> None:
    """Vérifie que la liste brute et l'enveloppe {vols: [...]} produisent le même grain."""
    liste = charger_json(DOSSIER_FIXTURES / "vols_depart_extrait.json")
    depuis_liste, _ = nettoyer_vols(aplatir_vols(liste))
    depuis_enveloppe, _ = nettoyer_vols(aplatir_vols({"vols": liste}))

    assert len(depuis_liste) == len(depuis_enveloppe)
    assert list(depuis_liste["icao24"]) == list(depuis_enveloppe["icao24"])


def test_nettoyer_meteo_zero_structurel_et_plafond_visibilite() -> None:
    """
    Vérifie rain.1h / wind.gust absents → 0, et visibilité plafonnée à 10 000 m.
    """
    brut = charger_json(DOSSIER_FIXTURES / "meteo_extrait.json")
    plat = aplatir_meteo(brut)
    propre, bilan = nettoyer_meteo(plat)

    assert bilan["conservees"] == 2
    cdg = propre.loc[propre["code_iata"] == "CDG"].iloc[0]
    lhr = propre.loc[propre["code_iata"] == "LHR"].iloc[0]
    assert cdg["rain_1h"] == 0.0
    assert cdg["wind_gust"] == 0.0
    assert cdg["code_icao"] == "LFPG"
    assert lhr["rain_1h"] == 1.4
    assert lhr["wind_gust"] == 8.2
    assert lhr["visibility"] == 10000


def test_nettoyer_actualites_dedup_url_et_titre_sans_content() -> None:
    """
    Vérifie l'exclusion de content et la déduplication URL + titre normalisé.
    """
    brut = charger_json(DOSSIER_FIXTURES / "news_extrait.json")
    plat = aplatir_actualites(brut)
    assert "content" not in plat.columns

    propre, bilan = nettoyer_actualites(plat)
    assert bilan["lues"] == 5
    assert len(propre) == 3
    urls = set(propre["url"])
    assert "https://example.com/unique" in urls
    assert "https://example.com/meme-url" in urls
    assert "https://example.com/article-1" in urls
    assert "https://aggregator.example.com/article-1" not in urls


def test_normaliser_titre_ignore_casse_et_ponctuation() -> None:
    """Vérifie que deux titres équivalents se ramènent à la même clé."""
    assert normaliser_titre("Airport strike delays flights") == normaliser_titre(
        "AIRPORT STRIKE DELAYS FLIGHTS!"
    )


def test_proxy_perturbation_texte_sans_reseau() -> None:
    """Vérifie un score lexical > 0 sur un titre de grève, 0 sur un titre neutre."""
    assert proxy_perturbation_texte("Airport strike delays flights") > 0
    assert proxy_perturbation_texte("Sunny weather in Paris") == 0.0
    assert proxy_perturbation_texte(None) == 0.0
