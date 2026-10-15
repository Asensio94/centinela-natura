"""Parcelas catastrales francesas de cada alerta, del catastro abierto de Etalab.

Etalab publica el plan cadastral informatisé (PCI vectoriel de la DGFiP) en GeoJSON, un
fichero estático por commune, y lo rehace cada trimestre. Como en España, se baja el
fichero entero de cada commune que toca la alerta en vez de consultar un servicio.

Cada parcela trae su identificador de 14 caracteres (commune INSEE, prefijo de la antigua
commune, sección y número: 64024000AB0042), la superficie fiscal y la geometría. No hay
propietarios: la DGFiP no los publica en abierto.
"""
from __future__ import annotations

import gzip
import json
import re
import time
from functools import lru_cache

import requests
import shapely
from rich.console import Console
from shapely.geometry import shape

from . import config, zona

con = Console()

BASE = "https://cadastre.data.gouv.fr/data/etalab-cadastre/latest/geojson/communes/{dep}/{insee}/cadastre-{insee}-parcelles.json.gz"
# Visor oficial de Etalab, centrado en la parcela.
SEDE = "https://cadastre.data.gouv.fr/map?style=ortho&parcelleId={}"
_UA = {"User-Agent": "centinela-natura (+https://github.com/Asensio94/centinela-natura)"}
# Mismos criterios que en España (catastro.py): dos píxeles, o casi toda la parcela.
MIN_M2 = 200
MIN_FRACCION_PARCELA = 0.5
MAX_PARCELAS = 40


def _dir():
    d = config.CACHE_DIR / "cadastre"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _get(url: str, **kw) -> requests.Response:
    for intento in range(4):
        try:
            r = requests.get(url, headers=_UA, timeout=120, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if intento == 3:
                raise
            time.sleep(5 * (intento + 1))


@lru_cache(maxsize=1)
def millesime() -> str:
    """Fecha de la edición vigente: `latest` redirige cada fichero a la carpeta de su edición."""
    insee = zona.municipios()[0]["insee"]
    r = requests.head(BASE.format(dep=insee[:2], insee=insee), headers=_UA, timeout=60, allow_redirects=False)
    m = re.search(r"/(\d{4}-\d{2}-\d{2})/", r.headers.get("location", ""))
    if not m:
        raise RuntimeError(f"edición del catastro desconocida (HTTP {r.status_code})")
    return m.group(1)


def desglosar(pid: str) -> dict:
    """64024000AB0042: commune, prefijo, sección (sin el cero de relleno) y número."""
    return {"prefixe": pid[5:8], "section": pid[8:10].lstrip("0") or "0", "numero": int(pid[10:14])}


@lru_cache(maxsize=16)
def _parcelas_commune(insee: str):
    """Parcelas de una commune con un índice espacial, en config.CRS."""
    ed = millesime()
    f = _dir() / f"{insee}_{ed}.json.gz"
    if not f.exists():
        for viejo in _dir().glob(f"{insee}_*.json.gz"):
            viejo.unlink()
        con.log(f"cadastre: bajando {insee}")
        f.write_bytes(_get(BASE.format(dep=insee[:2], insee=insee)).content)
    fc = json.loads(gzip.decompress(f.read_bytes()))
    ids, areas, geoms = [], [], []
    for feat in fc["features"]:
        if not feat.get("geometry"):
            continue
        g = shapely.make_valid(zona.a_utm(shape(feat["geometry"])))
        ids.append(feat["properties"]["id"])
        # La contenance es la superficie fiscal en m²; si falta, se mide la geometría.
        areas.append(float(feat["properties"].get("contenance") or 0) or g.area)
        geoms.append(g)
    return ids, areas, geoms, shapely.STRtree(geoms), ed


def parcelas_de(geom_utm) -> dict:
    """Parcelas que toca una alerta, de mayor a menor superficie afectada.

    El PCI de Etalab va en WGS84; se pasa a la malla (WGS84 / UTM 30N) sin cambio de marco.
    """
    area = geom_utm.area
    hallado, cubierto, ediciones = [], [], set()
    for m in zona.municipios():
        if not m["geom"].intersects(geom_utm.buffer(20)):
            continue
        ids, areas, geoms, arbol, ed = _parcelas_commune(m["insee"])
        for i in arbol.query(geom_utm, predicate="intersects"):
            inter = geoms[i].intersection(geom_utm)
            a = inter.area
            if a < MIN_M2 and a < MIN_FRACCION_PARCELA * geoms[i].area:
                continue
            cubierto.append(inter)
            ediciones.add(ed)
            hallado.append({"refcat": ids[i], "municipio": m["insee"], "municipio_nombre": m["nombre"],
                            **desglosar(ids[i]),
                            "ha_parcela": round(areas[i] / 1e4, 2), "ha_alerta": round(a / 1e4, 2)})
    hallado.sort(key=lambda p: -p["ha_alerta"])
    fr = shapely.union_all(cubierto).area / area if cubierto else 0.0
    return {"parcelas": hallado[:MAX_PARCELAS], "n_parcelas": len(hallado),
            # Fuera de toda parcela: domaine public non cadastré (ríos, carreteras, caminos
            # rurales, dominio marítimo) o terreno sin catastrar.
            "fraccion_parcelada": round(min(fr, 1.0), 3),
            "catastro_fecha": max(ediciones) if ediciones else None}
