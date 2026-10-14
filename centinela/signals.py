"""signals.json: the current alerts in the common format of the sibling projects.

Estado de las IBA (https://github.com/Asensio94/estado-iba, CONTRATO.md) gathers the facts of
every sibling project by protected area, municipality and region. It reads this file from the
root of the web; each current alert is one `land_change` signal.

Built from the same records as alertas.geojson, and with nothing they do not already publish:
no cadastral parcels, so no owners either.
"""
from __future__ import annotations

from datetime import datetime

from . import config

# Pressure on the ground today, as alertas.ACTIVAS: descartada, revertida and fusionada are not.
CURRENT = ("provisional", "confirmada")
COVERAGE_NOTE = "Cambios de vegetación con Sentinel-2, revisados cada mes."


def signal(p: dict, web_url: str) -> dict:
    """One alert, from the properties of its alertas.geojson feature."""
    def link(path: str | None) -> str | None:
        return web_url + path if path else None

    return {
        "id": p["id"],
        "kind": "land_change",
        "date": p["detectada"],
        "title": p.get("clase_nombre") or "Cambio de cubierta",
        "url": f"{web_url}#{p['id']}",
        "sites": [{"code": e["codigo"]} for e in p.get("espacios") or []],
        # Only names here: the hub turns them into INE codes with the IGN layer.
        "municipalities": [],
        "municipality_names": list(p.get("municipios") or []),
        "provinces": [config.REGION],            # Cantabria is a single province
        "precision": "pixeles",
        "deadline": None,
        "status": p["estado"],
        "value": {"amount": p["ha"], "unit": "ha"},
        "details": {
            "permit": p.get("cruce_nombre"),
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
        "coverage": {"label": config.REGION, "sites": sorted(set(sites)), "note": COVERAGE_NOTE},
        "signals": signals,
    }
