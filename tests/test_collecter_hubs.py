"""
Tests unitaires de l'orchestration de collecte multi-hubs
(src/processing/collecter_hubs.py).

Aucun appel réseau : les modules d'ingestion sont simulés.
"""

from pathlib import Path

import pytest

from src.ingestion.opensky_client import ErreurAPIOpenSky
from src.ingestion.openweather_client import HUBS_AEROPORTUAIRES, HubAeroportuaire
from src.processing.collecter_hubs import (
    ATTENTE_429_DEFAUT_SECONDES,
    collecter_meteo_hubs,
    collecter_vols_hubs,
    endpoints_deja_presents,
    executer_collecte,
    hubs_depuis_codes,
    main,
)

HUBS_TEST = (
    HubAeroportuaire("Paris Charles-de-Gaulle", "CDG", "LFPG", 49.0, 2.5),
    HubAeroportuaire("Londres Heathrow", "LHR", "EGLL", 51.5, -0.5),
)


class _ClientOpenSkyFictif:
    def __init__(self, reponses: dict, erreurs: dict | None = None) -> None:
        self.reponses = reponses
        self.erreurs = erreurs or {}
        self.appels: list[tuple[str, str]] = []
        self.sauvegardes: list[tuple[str, str, int]] = []

    def _lire(self, endpoint: str, icao: str) -> list[dict]:
        self.appels.append((endpoint, icao))
        cle = (endpoint, icao)
        if cle in self.erreurs:
            raise self.erreurs[cle]
        return list(self.reponses.get(cle, []))

    def recuperer_vols_depart(self, icao_aeroport: str, debut: int, fin: int) -> list[dict]:
        return self._lire("departure", icao_aeroport)

    def recuperer_vols_arrivee(self, icao_aeroport: str, debut: int, fin: int) -> list[dict]:
        return self._lire("arrival", icao_aeroport)

    def sauvegarder_vols(
        self,
        vols: list[dict],
        endpoint: str,
        icao_aeroport: str,
        debut: int,
        fin: int,
        dossier: str = "data/raw",
    ) -> str:
        self.sauvegardes.append((endpoint, icao_aeroport, len(vols)))
        return f"{dossier}/opensky_flights_{endpoint}_{icao_aeroport}_test.json"


class _ClientMeteoFictif:
    def __init__(self) -> None:
        self.appele = False

    def recuperer_meteo_hubs_aeroportuaires(self, hubs=None) -> dict:
        self.appele = True
        return {"hubs": [{"code_icao": h.code_icao} for h in (hubs or [])]}

    def sauvegarder_donnees_brutes(self, donnees: dict, dossier: str = "data/raw") -> str:
        return f"{dossier}/openweather_test.json"


def test_collecter_vols_hubs_boucle_depart_et_arrivee(mocker) -> None:
    """
    Vérifie que chaque hub est interrogé en departure puis arrival, avec pause.
    """
    mock_sleep = mocker.patch("src.processing.collecter_hubs.time.sleep")
    client = _ClientOpenSkyFictif(
        {
            ("departure", "LFPG"): [{"icao24": "a"}],
            ("arrival", "LFPG"): [{"icao24": "b"}],
            ("departure", "EGLL"): [{"icao24": "c"}, {"icao24": "d"}],
            ("arrival", "EGLL"): [],
        }
    )

    rapport = collecter_vols_hubs(
        client=client,
        hubs=HUBS_TEST,
        debut=1000,
        fin=2000,
        pause_secondes=3,
        dossier="data/raw",
    )

    assert rapport["interrompu_429"] is False
    assert [a["statut"] for a in rapport["appels"]] == ["OK", "OK", "OK", "OK"]
    assert rapport["appels"][2]["nb_vols"] == 2
    assert client.appels == [
        ("departure", "LFPG"),
        ("arrival", "LFPG"),
        ("departure", "EGLL"),
        ("arrival", "EGLL"),
    ]
    assert mock_sleep.call_count == 3
    mock_sleep.assert_called_with(3)


def test_collecter_vols_hubs_continue_apres_429_sur_le_hub_suivant(mocker) -> None:
    """
    Vérifie qu'un HTTP 429 sur le premier hub n'empêche pas d'appeler le second.
    """
    mock_sleep = mocker.patch("src.processing.collecter_hubs.time.sleep")
    client = _ClientOpenSkyFictif(
        {
            ("departure", "EGLL"): [{"icao24": "c"}],
            ("arrival", "EGLL"): [{"icao24": "d"}],
        },
        erreurs={
            ("departure", "LFPG"): ErreurAPIOpenSky(
                "Quota d'appels dépassé (429) sur l'API OpenSky Network."
            )
        },
    )

    rapport = collecter_vols_hubs(
        client=client,
        hubs=HUBS_TEST,
        debut=1000,
        fin=2000,
        pause_secondes=0,
        dossier="data/raw",
    )

    assert rapport["interrompu_429"] is True
    assert rapport["appels"][0]["hub"] == "LFPG"
    assert rapport["appels"][0]["statut"] == "429"
    assert [a["hub"] for a in rapport["appels"][1:]] == ["EGLL", "EGLL"]
    assert [a["statut"] for a in rapport["appels"][1:]] == ["OK", "OK"]
    assert ("arrival", "LFPG") not in client.appels
    assert client.appels.count(("departure", "LFPG")) == 2
    assert ("departure", "EGLL") in client.appels
    assert ("arrival", "EGLL") in client.appels
    assert mock_sleep.call_args_list[0].args == (ATTENTE_429_DEFAUT_SECONDES,)


def test_collecter_vols_hubs_sarrete_sur_403(mocker) -> None:
    """Vérifie qu'un HTTP 403 arrête la salve (API Client), sans enchaîner les hubs."""
    mocker.patch("src.processing.collecter_hubs.time.sleep")
    client = _ClientOpenSkyFictif(
        {("departure", "EGLL"): [{"icao24": "c"}]},
        erreurs={
            ("departure", "LFPG"): ErreurAPIOpenSky(
                "Accès refusé (403) par l'API OpenSky Network."
            )
        },
    )
    rapport = collecter_vols_hubs(
        client=client,
        hubs=HUBS_TEST,
        debut=1000,
        fin=2000,
        pause_secondes=0,
        dossier="data/raw",
    )
    assert rapport["appels"][0]["statut"] == "403"
    assert ("departure", "EGLL") not in client.appels


def test_executer_collecte_rappelle_la_meteo_apres_un_429(mocker) -> None:
    """
    Vérifie que la capture OpenWeather a lieu même si OpenSky s'est arrêté (429).
    """
    mocker.patch("src.processing.collecter_hubs.time.sleep")
    client_vols = _ClientOpenSkyFictif(
        {},
        erreurs={
            ("departure", "LFPG"): ErreurAPIOpenSky(
                "Quota d'appels dépassé (429) sur l'API OpenSky Network."
            )
        },
    )
    client_meteo = _ClientMeteoFictif()

    rapport = executer_collecte(
        client_opensky=client_vols,
        client_meteo=client_meteo,
        hubs=HUBS_TEST,
        pause_secondes=0,
        dossier="data/raw",
        avec_meteo=True,
    )

    assert rapport["opensky"]["interrompu_429"] is True
    assert client_meteo.appele is True
    assert rapport["openweather"]["statut"] == "OK"


def test_collecter_meteo_hubs_journalise_un_echec() -> None:
    """
    Vérifie qu'un échec OpenWeather renvoie un statut KO sans lever.
    """
    from src.ingestion.openweather_client import ErreurAPIOpenWeather

    class _ClientKo:
        def recuperer_meteo_hubs_aeroportuaires(self, hubs=None):
            raise ErreurAPIOpenWeather("Quota d'appels dépassé (429) sur l'API OpenWeather.")

        def sauvegarder_donnees_brutes(self, donnees, dossier="data/raw"):
            raise AssertionError("aucune sauvegarde attendue")

    rapport = collecter_meteo_hubs(client=_ClientKo(), hubs=HUBS_TEST, dossier="data/raw")
    assert rapport["statut"] == "KO"
    assert rapport["fichier"] is None


def test_hubs_depuis_codes_preserve_l_ordre_demande() -> None:
    """Vérifie que --hubs LTFM,EIDW ne relance pas LFPG en premier."""
    selection = hubs_depuis_codes(["ltfm", " EIDW ", "EDDM", "LEBL"])
    assert [hub.code_icao for hub in selection] == ["LTFM", "EIDW", "EDDM", "LEBL"]


def test_hubs_depuis_codes_vide_renvoie_le_catalogue() -> None:
    """Vérifie que None / liste vide = les dix hubs du catalogue."""
    assert hubs_depuis_codes(None) == HUBS_AEROPORTUAIRES
    assert hubs_depuis_codes([]) == HUBS_AEROPORTUAIRES


def test_hubs_depuis_codes_refuse_un_icao_inconnu() -> None:
    """Vérifie qu'un code hors catalogue lève ValueError avant tout appel API."""
    with pytest.raises(ValueError, match="KJFK"):
        hubs_depuis_codes(["LTFM", "KJFK"])


def test_executer_collecte_meteo_sur_les_dix_hubs_meme_si_vols_partiels(
    mocker,
) -> None:
    """
    Vérifie que la météo current porte sur les dix hubs (règle ±3 h),
    même si OpenSky ne reprend que les hubs encore manquants.
    """
    mocker.patch("src.processing.collecter_hubs.time.sleep")
    client_vols = _ClientOpenSkyFictif(
        {
            ("departure", "LTFM"): [{"icao24": "a"}],
            ("arrival", "LTFM"): [],
        }
    )
    client_meteo = _ClientMeteoFictif()
    hubs_vols = hubs_depuis_codes(["LTFM"])

    rapport = executer_collecte(
        client_opensky=client_vols,
        client_meteo=client_meteo,
        hubs=hubs_vols,
        pause_secondes=0,
        dossier="data/raw",
        avec_meteo=True,
    )

    assert [a["hub"] for a in rapport["opensky"]["appels"]] == ["LTFM", "LTFM"]
    assert rapport["openweather"]["nb_hubs"] == 10
    assert client_meteo.appele is True


def test_main_cli_filtre_les_hubs_opensky(mocker) -> None:
    """Vérifie que --hubs restreint OpenSky sans toucher NewsAPI."""
    mocker.patch("src.processing.collecter_hubs.time.sleep")
    spy = mocker.patch(
        "src.processing.collecter_hubs.executer_collecte",
        return_value={"opensky": {}, "openweather": {}},
    )

    main(["--hubs", "LTFM,EIDW,EDDM,LEBL", "--pause", "9"])

    kwargs = spy.call_args.kwargs
    assert [hub.code_icao for hub in kwargs["hubs"]] == [
        "LTFM",
        "EIDW",
        "EDDM",
        "LEBL",
    ]
    assert kwargs["pause_secondes"] == 9.0
    assert kwargs["avec_meteo"] is True
    assert kwargs["reprendre"] is False


def test_collecter_vols_hubs_honore_retry_after(mocker) -> None:
    """Vérifie que le backoff 429 utilise Retry-After plutôt que le défaut 60 s."""
    mock_sleep = mocker.patch("src.processing.collecter_hubs.time.sleep")
    client = _ClientOpenSkyFictif(
        {("departure", "EGLL"): [], ("arrival", "EGLL"): []},
        erreurs={
            ("departure", "LFPG"): ErreurAPIOpenSky(
                "Quota d'appels dépassé (429) sur l'API OpenSky Network.",
                retry_after_secondes=15,
            )
        },
    )

    collecter_vols_hubs(
        client=client,
        hubs=HUBS_TEST,
        debut=1000,
        fin=2000,
        pause_secondes=0,
        dossier="data/raw",
    )

    assert mock_sleep.call_args_list[0].args == (15.0,)
    assert ("departure", "EGLL") in client.appels


def test_endpoints_deja_presents_lit_les_json(tmp_path: Path) -> None:
    """Vérifie le scan des fichiers opensky_flights_* déjà écrits."""
    (tmp_path / "opensky_flights_departure_LFPG_20260826_145520.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / "opensky_flights_arrival_LFPG_20260826_145524.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / "opensky_flights_departure_EGLL_20260826_145527.json").write_text(
        "{}", encoding="utf-8"
    )
    assert endpoints_deja_presents(tmp_path) == {
        ("departure", "LFPG"),
        ("arrival", "LFPG"),
        ("departure", "EGLL"),
    }


def test_collecter_vols_hubs_reprendre_saute_les_icao_deja_presents(
    mocker, tmp_path: Path
) -> None:
    """Vérifie que --reprendre n'interroge pas un hub déjà complet en JSON."""
    mocker.patch("src.processing.collecter_hubs.time.sleep")
    (tmp_path / "opensky_flights_departure_LFPG_20260826_145520.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_path / "opensky_flights_arrival_LFPG_20260826_145524.json").write_text(
        "{}", encoding="utf-8"
    )
    client = _ClientOpenSkyFictif(
        {
            ("departure", "EGLL"): [{"icao24": "c"}],
            ("arrival", "EGLL"): [],
        }
    )

    rapport = collecter_vols_hubs(
        client=client,
        hubs=HUBS_TEST,
        debut=1000,
        fin=2000,
        pause_secondes=0,
        dossier=tmp_path,
        reprendre=True,
    )

    assert ("departure", "LFPG") not in client.appels
    assert ("arrival", "LFPG") not in client.appels
    assert client.appels == [("departure", "EGLL"), ("arrival", "EGLL")]
    assert [a["hub"] for a in rapport["appels"]] == ["EGLL", "EGLL"]


def test_main_cli_reprendre(mocker) -> None:
    """Vérifie que --reprendre est transmis à l'orchestration."""
    spy = mocker.patch(
        "src.processing.collecter_hubs.executer_collecte",
        return_value={"opensky": {}, "openweather": {}},
    )

    main(["--hubs", "LTFM,EIDW", "--pause", "9", "--reprendre"])

    assert spy.call_args.kwargs["reprendre"] is True
