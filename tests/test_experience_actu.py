"""
Tests de la jointure hub × jour et du split « test avec signal ».
"""

from datetime import datetime, timezone

import pandas as pd
import pytest

from src.models.experience_actu import (
    joindre_actu_hub,
    masque_signal_actu,
    split_test_avec_signal,
)
from src.processing.actu_hub import date_id_veille


def _vol(jour: int, heure: int, icao: str, flight_id: int) -> dict:
    debut = datetime(2026, 8, jour, heure, tzinfo=timezone.utc)
    return {
        "flight_id": flight_id,
        "est_departure_airport": icao,
        "date_id": int(debut.strftime("%Y%m%d")),
        "first_seen": debut,
        "duree_minutes": 80.0,
    }


def test_joindre_prend_la_veille() -> None:
    """Vérifie que le 26/08 récupère l'actu hub du 25/08 en J−1."""
    vols = pd.DataFrame(
        [
            _vol(26, 10, "EGLL", 1),
            _vol(26, 11, "LFPG", 2),
        ]
    )
    agregats = pd.DataFrame(
        {
            "date_id": [20260825],
            "icao": ["EGLL"],
            "nb_articles_hub": [3],
            "flag_greve_hub": [1.0],
            "flag_atc_hub": [0.0],
            "score_bert_hub": [-0.2],
        }
    )
    out = joindre_actu_hub(vols, agregats)
    heathrow = out.loc[out["est_departure_airport"] == "EGLL"].iloc[0]
    assert heathrow["nb_articles_hub"] == 0.0
    assert heathrow["nb_articles_hub_j1"] == 3.0
    assert heathrow["flag_greve_hub_j1"] == pytest.approx(1.0)
    cdg = out.loc[out["est_departure_airport"] == "LFPG"].iloc[0]
    assert cdg["nb_articles_hub_j1"] == 0.0
    assert date_id_veille(20260826) == 20260825


def test_split_filtre_le_test_sans_signal() -> None:
    """Vérifie que le test temporel écarte les lignes sans actu hub."""
    lignes = []
    for i in range(40):
        lignes.append(_vol(25, 8 + (i % 8), "LFPG", i + 1))
        lignes[-1]["nb_articles_hub"] = 0.0
        lignes[-1]["nb_articles_hub_j1"] = 0.0
        lignes[-1]["flag_greve_hub"] = 0.0
        lignes[-1]["flag_atc_hub"] = 0.0
        lignes[-1]["flag_greve_hub_j1"] = 0.0
        lignes[-1]["flag_atc_hub_j1"] = 0.0
    for i in range(40):
        lignes.append(_vol(26, 8, "EGLL", 100 + i))
        lignes[-1]["nb_articles_hub"] = 2.0
        lignes[-1]["nb_articles_hub_j1"] = 0.0
        lignes[-1]["flag_greve_hub"] = 1.0
        lignes[-1]["flag_atc_hub"] = 0.0
        lignes[-1]["flag_greve_hub_j1"] = 0.0
        lignes[-1]["flag_atc_hub_j1"] = 0.0
        lignes[-1]["first_seen"] = datetime(2026, 8, 26, 8, i, tzinfo=timezone.utc)
    df = pd.DataFrame(lignes)
    _train, test, mode = split_test_avec_signal(
        df, fraction_train=0.5, n_test_min=10
    )
    assert masque_signal_actu(test).all()
    assert len(test) >= 10
    assert mode in {
        "temporel_puis_test_filtre_signal",
        "temporel_sur_lignes_avec_signal",
    }
