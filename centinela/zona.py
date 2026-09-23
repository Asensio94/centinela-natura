"""Ámbito vigilado: Red Natura 2000 recortada a la comunidad, y la malla fija de 10 m.

Los límites se descargan una vez (EEA y OpenStreetMap) y se guardan en data/zonas, que va
en el repositorio: así la vigilancia diaria no depende de que esos servicios respondan, y
la malla de píxeles es idéntica mes tras mes, que es lo que permite comparar compuestos
píxel a píxel sin remuestrear nada.
"""
from __future__ import annotations

import json
from functools import lru_cache

import numpy as np
import requests
from odc.geo.geobox import GeoBox
from odc.geo.geom import Geometry
from odc.geo.xr import rasterize
from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.ops import transform, unary_union

from . import config

UA = {"User-Agent": "centinela-natura/0.1 (+https://github.com/Asensio94/centinela-natura)"}
ESPACIOS_GEOJSON = config.ZONAS_DIR / "espacios.geojson"      # EPSG:4326, uno por espacio
REGION_GEOJSON = config.ZONAS_DIR / "region.geojson"
MUNICIPIOS_GEOJSON = config.ZONAS_DIR / "municipios.geojson"
OVERPASS = "https://overpass-api.de/api/interpreter"

_a_utm = Transformer.from_crs("EPSG:4326", config.CRS, always_xy=True).transform
_a_geo = Transformer.from_crs(config.CRS, "EPSG:4326", always_xy=True).transform


def descargar() -> dict:
    """Baja los espacios y el límite regional y los deja en data/zonas."""
    codigos = ",".join(f"'{c}'" for c in config.NATURA_CODIGOS_EXTRA)
    where = f"SITECODE LIKE '{config.NATURA_CODIGOS_LIKE}' OR SITECODE IN ({codigos})"
    espacios: dict[str, dict] = {}
    for capa in config.NATURA_CAPAS:
        r = requests.get(config.NATURA_URL.format(capa=capa), timeout=180, params={
            "where": where, "outFields": "SITECODE,SITENAME,SITETYPE",
            "returnGeometry": "true", "outSR": "4326", "f": "geojson"})
        r.raise_for_status()
        for f in r.json()["features"]:
            p = f["properties"]
            espacios.setdefault(p["SITECODE"], {"props": p, "geoms": []})["geoms"].append(
                shape(f["geometry"]).buffer(0))

    r = requests.get("https://nominatim.openstreetmap.org/search", headers=UA, timeout=60, params={
        "q": config.REGION_QUERY, "polygon_geojson": 1, "format": "json", "limit": 1})
    r.raise_for_status()
    region = shape(r.json()[0]["geojson"]).buffer(0)

    feats = []
    for code, e in sorted(espacios.items()):
        g = unary_union(e["geoms"]).intersection(region)
        if g.is_empty:
            continue
        p = e["props"]
        # SITETYPE: A = ZEPA, B = ZEC, C = ambas figuras sobre el mismo polígono.
        tipo = {"A": "ZEPA", "B": "ZEC", "C": "ZEC y ZEPA"}.get(p.get("SITETYPE"), p.get("SITETYPE"))
        ha = transform(_a_utm, g).area / 1e4
        feats.append({"type": "Feature", "geometry": mapping(g.simplify(0.00002)),
                      "properties": {"codigo": code, "nombre": p["SITENAME"], "tipo": tipo,
                                     "ha": round(ha, 1)}})
    ESPACIOS_GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                           ensure_ascii=False), encoding="utf-8")
    REGION_GEOJSON.write_text(json.dumps({"type": "Feature", "geometry": mapping(region.simplify(0.0002)),
                                          "properties": {"nombre": config.REGION}}), encoding="utf-8")
    return {"espacios": len(feats), "ha": round(sum(f["properties"]["ha"] for f in feats)),
            "municipios": descargar_municipios()}


def descargar_municipios() -> int:
    """Términos municipales (admin_level 8 de OpenStreetMap) con su código INE."""
    from shapely.geometry import LineString
    from shapely.ops import linemerge, polygonize
    q = (f'[out:json][timeout:180];area["name"="{config.REGION}"]["admin_level"="4"]->.a;'
         'rel(area.a)["boundary"="administrative"]["admin_level"="8"];out geom;')
    r = requests.post(OVERPASS, data={"data": q}, headers=UA, timeout=300)
    r.raise_for_status()
    feats = []
    for e in r.json()["elements"]:
        t = e.get("tags", {})
        lineas = [LineString([(p["lon"], p["lat"]) for p in m["geometry"]])
                  for m in e["members"]
                  if m["type"] == "way" and m.get("role") in ("outer", "") and "geometry" in m]
        g = unary_union(list(polygonize(linemerge(lineas))))
        if g.is_empty:
            continue
        feats.append({"type": "Feature", "geometry": mapping(g.simplify(0.00005)),
                      "properties": {"nombre": t.get("name"), "ine": t.get("ine:municipio")}})
    MUNICIPIOS_GEOJSON.write_text(json.dumps({"type": "FeatureCollection", "features": feats},
                                             ensure_ascii=False), encoding="utf-8")
    return len(feats)


@lru_cache
def municipios() -> list[dict]:
    fc = json.loads(MUNICIPIOS_GEOJSON.read_text(encoding="utf-8"))
    return [dict(f["properties"], geom=transform(_a_utm, shape(f["geometry"]))) for f in fc["features"]]


def municipios_de(geom_utm) -> list[str]:
    """Municipios que toca el cambio, de más a menos superficie compartida."""
    hits = [(m["geom"].intersection(geom_utm).area, m["nombre"]) for m in municipios()
            if m["geom"].intersects(geom_utm)]
    if not hits:   # en la costa el polígono del cambio puede quedar fuera del término
        c = geom_utm.centroid
        hits = [(-m["geom"].distance(c), m["nombre"]) for m in municipios()]
        hits = [max(hits)]
    return [n for _, n in sorted(hits, reverse=True)]


@lru_cache
def espacios() -> list[dict]:
    """Espacios con su geometría en config.CRS (clave 'geom')."""
    fc = json.loads(ESPACIOS_GEOJSON.read_text(encoding="utf-8"))
    out = []
    for f in fc["features"]:
        d = dict(f["properties"])
        d["geom"] = transform(_a_utm, shape(f["geometry"]))
        out.append(d)
    return out


@lru_cache
def union():
    """Superficie vigilada (unión de ZEC y ZEPA, que se solapan) en config.CRS."""
    return unary_union([e["geom"] for e in espacios()]).buffer(0)


@lru_cache
def malla() -> GeoBox:
    """La malla de trabajo: 10 m, anclada a múltiplos de 10 m en WGS84 / UTM 30N."""
    r = config.RESOLUCION_M
    x0, y0, x1, y1 = union().bounds
    x0, y0 = np.floor(x0 / r) * r, np.floor(y0 / r) * r
    x1, y1 = np.ceil(x1 / r) * r, np.ceil(y1 / r) * r
    return GeoBox.from_bbox((x0, y0, x1, y1), crs=config.CRS, resolution=r)


@lru_cache
def mascara() -> np.ndarray:
    """True en los píxeles cuyo centro cae dentro de la Red Natura."""
    return rasterize(Geometry(union(), config.CRS), malla()).values.astype(bool)


def espacios_de(geom_utm) -> list[dict]:
    """Espacios que toca una geometría (ZEC y ZEPA pueden coincidir en el mismo sitio)."""
    return [{k: e[k] for k in ("codigo", "nombre", "tipo")}
            for e in espacios() if e["geom"].intersects(geom_utm)]


def a_geo(geom_utm):
    return transform(_a_geo, geom_utm)


def a_utm(geom_geo):
    return transform(_a_utm, geom_geo)
