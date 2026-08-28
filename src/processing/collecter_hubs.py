"""
Collecte OpenSky /flights/departure et /flights/arrival pour les hubs, puis
météo OpenWeather Current Weather des mêmes aéroports.
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from src.ingestion.opensky_client import ErreurAPIOpenSky, OpenSkyClient
from src.ingestion.openweather_client import (
    HUBS_AEROPORTUAIRES,
    ErreurAPIOpenWeather,
    HubAeroportuaire,
    OpenWeatherClient,
)
from src.utils.chemins import RACINE_PROJET, chemin_relatif_projet
from src.utils.logger import get_logger

logger = get_logger(__name__)

PAUSE_ENTRE_APPELS_SECONDES = 9.0
FENETRE_VOLS_SECONDES = 24 * 60 * 60
ENDPOINTS_VOLS = ("departure", "arrival")
DOSSIER_RAW_DEFAUT = RACINE_PROJET / "data" / "raw"
# Hubs encore absents après la salve du 26/08 après-midi (429 sur LTFM).
HUBS_PRIORITAIRES = ("LTFM", "EIDW", "EDDM", "LEBL")


def hubs_depuis_codes(
    codes: list[str] | tuple[str, ...] | None,
    catalogue: tuple[HubAeroportuaire, ...] = HUBS_AEROPORTUAIRES,
) -> tuple[HubAeroportuaire, ...]:
    """
    Résout une liste de codes ICAO vers les hubs du catalogue, dans l'ordre
    demandé. ``None`` ou liste vide = tout le catalogue.
    """
    if not codes:
        return catalogue
    index = {hub.code_icao.upper(): hub for hub in catalogue}
    selection: list[HubAeroportuaire] = []
    inconnus: list[str] = []
    for brut in codes:
        code = brut.strip().upper()
        if not code:
            continue
        hub = index.get(code)
        if hub is None:
            inconnus.append(code)
        else:
            selection.append(hub)
    if inconnus:
        connus = ", ".join(hub.code_icao for hub in catalogue)
        raise ValueError(
            f"Hub(s) inconnu(s) : {', '.join(inconnus)}. "
            f"Codes ICAO attendus : {connus}."
        )
    if not selection:
        return catalogue
    return tuple(selection)


def construire_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collecte OpenSky departure/arrival (pause entre appels) puis "
            "météo OpenWeather current. NewsAPI n'est pas appelée."
        )
    )
    parser.add_argument(
        "--hubs",
        default=None,
        help=(
            "Codes ICAO séparés par des virgules "
            f"(ex. {','.join(HUBS_PRIORITAIRES)}). "
            "Sans option : les dix hubs, ordre catalogue."
        ),
    )
    parser.add_argument(
        "--pause",
        type=float,
        default=PAUSE_ENTRE_APPELS_SECONDES,
        help=(
            "Pause en secondes entre deux appels OpenSky "
            f"(défaut {PAUSE_ENTRE_APPELS_SECONDES:.0f})."
        ),
    )
    parser.add_argument(
        "--sans-meteo",
        action="store_true",
        help="Ne pas interroger OpenWeather (vols seulement).",
    )
    return parser


def _est_quota_depasse(erreur: Exception) -> bool:
    return "429" in str(erreur)


def _est_authentification_refusee(erreur: Exception) -> bool:
    return "401" in str(erreur)


def collecter_vols_hubs(
    client: OpenSkyClient | None = None,
    hubs: tuple[HubAeroportuaire, ...] = HUBS_AEROPORTUAIRES,
    debut: int | None = None,
    fin: int | None = None,
    pause_secondes: float = PAUSE_ENTRE_APPELS_SECONDES,
    dossier: str | Path | None = None,
) -> dict:
    """
    Interroge /flights/departure puis /flights/arrival pour chaque hub ICAO.

    Une pause sépare les appels. Un HTTP 429 interrompt la boucle ; les JSON
    déjà écrits restent en place. Un HTTP 404 est une liste vide (géré par le
    module d'ingestion).

    Returns
    -------
    dict
        Fenêtre Unix, liste d'appels (hub, endpoint, statut, nb_vols, fichier)
        et drapeau d'interruption 429.
    """
    client_opensky = client if client is not None else OpenSkyClient()
    dossier_raw = Path(dossier) if dossier is not None else DOSSIER_RAW_DEFAUT

    instant_fin = int(fin if fin is not None else datetime.now(timezone.utc).timestamp())
    instant_debut = int(
        debut if debut is not None else instant_fin - FENETRE_VOLS_SECONDES
    )

    appels: list[dict] = []
    interrompu_429 = False
    premier = True

    for hub in hubs:
        for endpoint in ENDPOINTS_VOLS:
            if interrompu_429:
                break
            if not premier:
                time.sleep(pause_secondes)
            premier = False

            icao = hub.code_icao
            logger.info(
                "Collecte /flights/%s pour %s (%s).",
                endpoint,
                hub.nom,
                icao,
            )
            try:
                if endpoint == "departure":
                    vols = client_opensky.recuperer_vols_depart(
                        icao_aeroport=icao, debut=instant_debut, fin=instant_fin
                    )
                else:
                    vols = client_opensky.recuperer_vols_arrivee(
                        icao_aeroport=icao, debut=instant_debut, fin=instant_fin
                    )
                chemin = client_opensky.sauvegarder_vols(
                    vols,
                    endpoint=endpoint,
                    icao_aeroport=icao,
                    debut=instant_debut,
                    fin=instant_fin,
                    dossier=str(dossier_raw),
                )
                appels.append(
                    {
                        "hub": icao,
                        "endpoint": endpoint,
                        "statut": "OK",
                        "nb_vols": len(vols),
                        "fichier": chemin_relatif_projet(chemin),
                    }
                )
                logger.info(
                    "OK /flights/%s %s : %s vol(s) → '%s'.",
                    endpoint,
                    icao,
                    len(vols),
                    chemin_relatif_projet(chemin),
                )
            except ErreurAPIOpenSky as erreur:
                if _est_quota_depasse(erreur):
                    interrompu_429 = True
                    appels.append(
                        {
                            "hub": icao,
                            "endpoint": endpoint,
                            "statut": "429",
                            "nb_vols": 0,
                            "fichier": None,
                        }
                    )
                    logger.error(
                        "Quota OpenSky (429) sur /flights/%s %s : "
                        "arrêt de la collecte vols. Les fichiers déjà "
                        "sauvegardés restent exploitables par l'ETL.",
                        endpoint,
                        icao,
                    )
                    break
                if _est_authentification_refusee(erreur):
                    appels.append(
                        {
                            "hub": icao,
                            "endpoint": endpoint,
                            "statut": "401",
                            "nb_vols": 0,
                            "fichier": None,
                        }
                    )
                    logger.error(
                        "Authentification OpenSky refusée (401) : arrêt de la "
                        "collecte vols."
                    )
                    return {
                        "debut": instant_debut,
                        "fin": instant_fin,
                        "interrompu_429": False,
                        "appels": appels,
                    }
                appels.append(
                    {
                        "hub": icao,
                        "endpoint": endpoint,
                        "statut": "KO",
                        "nb_vols": 0,
                        "fichier": None,
                        "detail": str(erreur),
                    }
                )
                logger.error(
                    "Échec /flights/%s %s : %s. Poursuite sur l'appel suivant.",
                    endpoint,
                    icao,
                    erreur,
                )
        if interrompu_429:
            break

    return {
        "debut": instant_debut,
        "fin": instant_fin,
        "interrompu_429": interrompu_429,
        "appels": appels,
    }


def collecter_meteo_hubs(
    client: OpenWeatherClient | None = None,
    hubs: tuple[HubAeroportuaire, ...] = HUBS_AEROPORTUAIRES,
    dossier: str | Path | None = None,
) -> dict:
    """
    Interroge OpenWeather Current Weather pour les hubs et sauvegarde un JSON.

    Returns
    -------
    dict
        Statut, nombre de hubs, chemin relatif du fichier (ou None si échec).
    """
    client_meteo = client if client is not None else OpenWeatherClient()
    dossier_raw = Path(dossier) if dossier is not None else DOSSIER_RAW_DEFAUT

    try:
        donnees = client_meteo.recuperer_meteo_hubs_aeroportuaires(hubs=hubs)
        chemin = client_meteo.sauvegarder_donnees_brutes(
            donnees, dossier=str(dossier_raw)
        )
        nb_hubs = len(donnees.get("hubs") or [])
        logger.info(
            "Météo hubs sauvegardée (%s hub(s)) → '%s'.",
            nb_hubs,
            chemin_relatif_projet(chemin),
        )
        return {
            "statut": "OK",
            "nb_hubs": nb_hubs,
            "fichier": chemin_relatif_projet(chemin),
        }
    except ErreurAPIOpenWeather as erreur:
        logger.error("Échec de la capture OpenWeather : %s", erreur)
        return {
            "statut": "KO",
            "nb_hubs": 0,
            "fichier": None,
            "detail": str(erreur),
        }


def executer_collecte(
    client_opensky: OpenSkyClient | None = None,
    client_meteo: OpenWeatherClient | None = None,
    hubs: tuple[HubAeroportuaire, ...] = HUBS_AEROPORTUAIRES,
    hubs_meteo: tuple[HubAeroportuaire, ...] | None = None,
    pause_secondes: float = PAUSE_ENTRE_APPELS_SECONDES,
    dossier: str | Path | None = None,
    avec_meteo: bool = True,
) -> dict:
    """
    Enchaîne la collecte vols multi-hubs puis, dans la même session, la météo.

    NewsAPI n'est pas appelée. La météo porte par défaut sur les dix hubs
    (règle de jointure ±3 h), même si ``hubs`` ne vise qu'un sous-ensemble
    OpenSky (reprise après 429).

    Returns
    -------
    dict
        Rapports OpenSky et OpenWeather.
    """
    rapport_vols = collecter_vols_hubs(
        client=client_opensky,
        hubs=hubs,
        pause_secondes=pause_secondes,
        dossier=dossier,
    )
    rapport_meteo: dict | None = None
    if avec_meteo:
        rapport_meteo = collecter_meteo_hubs(
            client=client_meteo,
            hubs=hubs_meteo if hubs_meteo is not None else HUBS_AEROPORTUAIRES,
            dossier=dossier,
        )
    rapport = {"opensky": rapport_vols, "openweather": rapport_meteo}
    logger.info("Collecte hubs terminée : %s", rapport)
    return rapport


def main(argv: list[str] | None = None) -> dict:
    """Point d'entrée CLI : ``python -m src.processing.collecter_hubs``."""
    args = construire_parser().parse_args(argv)
    codes = (
        [morceau.strip() for morceau in args.hubs.split(",")]
        if args.hubs
        else None
    )
    hubs_vols = hubs_depuis_codes(codes)
    logger.info(
        "Collecte OpenSky sur %s hub(s) : %s (pause %.1f s). "
        "Météo : %s. NewsAPI : non appelée.",
        len(hubs_vols),
        ", ".join(hub.code_icao for hub in hubs_vols),
        args.pause,
        "non" if args.sans_meteo else "dix hubs current",
    )
    return executer_collecte(
        hubs=hubs_vols,
        pause_secondes=args.pause,
        avec_meteo=not args.sans_meteo,
    )


if __name__ == "__main__":
    main()
