"""signals.json: the current alerts in the common format of the sibling projects.

Estado de las IBA (https://github.com/Asensio94/estado-iba, CONTRATO.md) gathers the facts of
every sibling project by protected area, municipality and region. It reads this file from the
root of the web; each current alert is one `land_change` signal.

Built from the same records as alertas.geojson, and with nothing they do not already publish:
no cadastral parcels, so no owners either.

Each country builds its part (`document`) and leaves it in its cache; the published file joins
the parts of every country (`combine`). Every signal says its `country`; French
municipalities go with their INSEE code, Spanish ones by name only. Spain alone is a version 1
file; with France it is version 2, whose coverage goes by country.

The contract wants each signal's title in its country's language, so French alerts take their
title and permit from i18n, the same names the French web shows. Status and the other values
stay canonical, as in the data files.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import config, i18n

# Pressure on the ground today, as alertas.ACTIVAS: descartada, revertida and fusionada are not.
CURRENT = ("provisional", "confirmada")
COVERAGE_NOTE = {"ES": "Cambios de vegetación con Sentinel-2, revisados cada mes.",
                 "FR": "Changements de végétation avec Sentinel-2, revus chaque mois."}
UNKNOWN_CLASS = {"es": "Cambio de cubierta", "fr": "Changement de couverture"}


def signal(p: dict, web_url: str) -> dict:
    """One alert, from the properties of its alertas.geojson feature."""
    def link(path: str | None) -> str | None:
        return web_url + path if path else None

    lang = i18n.lang_of(config.PAIS)
    if lang == "es":
        title, permit = p.get("clase_nombre"), p.get("cruce_nombre")
    else:
        title = i18n.CLASES[lang].get(p.get("clase") or "")
        permit = i18n.CRUCES[lang].get(p.get("cruce") or "", p.get("cruce_nombre"))

    return {
        "id": p["id"],
        "kind": "land_change",
        "country": config.PAIS,
        "date": p["detectada"],
        "title": title or UNKNOWN_CLASS[lang],
        "url": f"{web_url}#{p['id']}",
        "sites": [{"code": e["codigo"]} for e in p.get("espacios") or []],
        # Spain: only names; the hub turns them into INE codes with the IGN layer. France:
        # the INSEE codes (5 characters, 2A004), which the cadastre layer already carries.
        "municipalities": list(p.get("municipios_insee") or []),
        "municipality_names": list(p.get("municipios") or []),
        "provinces": [config.REGION],            # Cantabria and the 64 are one province each
        "precision": "pixeles",
        "deadline": None,
        "status": p["estado"],
        "value": {"amount": p["ha"], "unit": "ha"},
        "details": {
            "permit": permit,
            "before": link(p.get("foto_antes")),
            "after": link(p.get("foto_despues")),
            "before_date": p.get("fecha_antes"),
            "after_date": p.get("fecha_despues"),
            # centinela stores [lat, lon]; the contract wants [lon, lat].
            "point": p["centro"][::-1] if p.get("centro") else None,
        },
    }


def document(alertas: dict, sites: list[str], now: datetime, web_url: str) -> dict:
    """The whole file: `alertas` is the alertas.geojson collection, `sites` the watched site
    codes (those of espacios.geojson) and `now` the UTC time of the run."""
    current = [f["properties"] for f in alertas["features"] if f["properties"]["estado"] in CURRENT]
    signals = [signal(p, web_url) for p in sorted(current, key=lambda p: (p["detectada"], p["id"]))]
    return {
        "source": "centinela-natura",
        "version": 1,
        "generated": now.strftime("%Y-%m-%dT%H:%MZ"),
        "coverage": {"label": config.REGION, "sites": sorted(set(sites)), "note": COVERAGE_NOTE[config.PAIS]},
        "signals": signals,
    }


def parts() -> dict[str, Path]:
    """Country → its part, for every country that has built its web, Spain first."""
    out = {}
    for k, p in config.PAISES.items():
        d = config.ROOT / "data" / p["subdir"] / "cache" if p["subdir"] else config.ROOT / "data" / "cache"
        if (d / "signals.json").exists():
            out[k] = d / "signals.json"
    return out


def combine(docs: dict[str, dict], now: datetime) -> dict:
    """One file from the parts of each country.

    Spain alone stays version 1, as it always was. With another country the file is version 2:
    the same signals, and `coverage` becomes one entry per country, keyed by its code.
    """
    if list(docs) == ["ES"]:
        return docs["ES"]
    return {
        "source": "centinela-natura",
        "version": 2,
        "generated": now.strftime("%Y-%m-%dT%H:%MZ"),
        "coverage": {k: d["coverage"] for k, d in docs.items()},
        "signals": [s for d in docs.values() for s in d["signals"]],
    }
