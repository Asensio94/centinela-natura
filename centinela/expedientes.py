"""Cruce de cada cambio con los expedientes que ha leído el observatorio de alegaciones.

El cruce es por municipio. Un expediente en el mismo municipio no demuestra que el cambio
sea esa obra. Solo dice que hay una tramitación pública que mirar antes de dar la alerta
por buena. Al revés, «sin expediente conocido» significa que el observatorio no ha leído
ningún anuncio ni resolución de ese municipio desde que vigila el boletín. No significa
que la obra no tenga permiso.
"""
from __future__ import annotations

import json
import unicodedata

import requests

from . import config

BASE = "https://raw.githubusercontent.com/Asensio94/observatorio-alegaciones/main/data/"
FICHEROS = ("estado.json", "estado_litoral.json")
OBSERVATORIO_WEB = "https://asensio94.github.io/observatorio-alegaciones/"
# Sentidos de resolución que habilitan la actuación, tal y como los etiqueta el observatorio.
HABILITANTES = {"favorable", "condicionada", "parcial", "sin_eia"}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


def cargar() -> list[dict]:
    """Registros de Cantabria del observatorio, con copia local por si GitHub no responde."""
    registros: dict[str, dict] = {}
    for nombre in FICHEROS:
        cache = config.CACHE_DIR / nombre
        try:
            r = requests.get(BASE + nombre, timeout=60)
            r.raise_for_status()
            datos = r.json()
            cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except (requests.RequestException, ValueError):
            if not cache.exists():
                continue
            datos = json.loads(cache.read_text(encoding="utf-8"))
        for grupo in ("anuncios", "resoluciones"):
            for k, a in (datos.get(grupo) or {}).items():
                if config.REGION not in (a.get("provincias") or []):
                    continue
                registros[k] = {
                    "id": k, "grupo": grupo, "fecha": a.get("fecha"), "titulo": a.get("titulo"),
                    "url": a.get("url_html"), "fuente": a.get("fuente") or "BOE",
                    "municipios": a.get("municipios") or [], "sentido": a.get("sentido", ""),
                    "sentido_etiqueta": a.get("sentido_etiqueta", ""),
                    "categoria": a.get("categoria", ""),
                }
    return sorted(registros.values(), key=lambda r: r["fecha"] or "", reverse=True)


def cobertura(registros: list[dict]) -> str | None:
    fechas = [r["fecha"] for r in registros if r["fecha"]]
    return min(fechas) if fechas else None


def cruzar(municipios: list[str], registros: list[dict]) -> dict:
    objetivo = {_norm(m) for m in municipios}
    hits = [r for r in registros if objetivo & {_norm(m) for m in r["municipios"]}]
    habil = [r for r in hits if r["grupo"] == "resoluciones" and r["sentido"] in HABILITANTES]
    if habil:
        estado = "resolucion"
    elif hits:
        estado = "tramitacion"
    else:
        estado = "sin_expediente"
    return {"estado": estado, "expedientes": [
        {k: r[k] for k in ("id", "fecha", "titulo", "url", "fuente", "grupo", "sentido_etiqueta")}
        for r in hits[:8]]}


ESTADOS = {
    "resolucion": "Resolución favorable en el municipio",
    "tramitacion": "Expediente en tramitación en el municipio",
    "sin_expediente": "Sin expediente conocido",
}

