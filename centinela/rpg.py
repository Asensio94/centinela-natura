"""Uso agrícola declarado antes del cambio, del Registre parcellaire graphique (RPG).

Cada primavera los agricultores que piden ayudas de la PAC dibujan sus parcelas y
declaran el cultivo; el IGN publica esas parcelas, anonimizadas, una capa por año. Sirve
para separar lo que el satélite no distingue: un prado temporal que se labra para
sembrar maíz es la rotación normal de una explotación; una pradera permanente que se
labra es otra cosa, porque en la Red Natura 2000 la PAC prohíbe labrar las praderas
permanentes sensibles (BCAE 9).

Solo se guarda el cultivo y la superficie: el RPG público no trae al declarante, y su
identificador de parcela tampoco se guarda.
"""
from __future__ import annotations

import re
import time
from functools import lru_cache

import requests
import shapely
from shapely.geometry import shape

from . import config, zona

WFS = "https://data.geopf.fr/wfs/ows"
_UA = {"User-Agent": "centinela-natura (+https://github.com/Asensio94/centinela-natura)"}
# Grupos de cultivo que la PAC cuenta como pradera permanente: 18 (prairies permanentes)
# y 17 (estives et landes, pastos de montaña). Los códigos de grupo son los mismos en
# todas las capas anuales; el campo `pp` solo existe en las últimas.
GRUPOS_PRADERA_PERMANENTE = {"17", "18"}
# Por encima de esta fracción de la alerta dentro de parcelas declaradas, el cambio es
# agrícola. Por debajo, la parte declarada es el borde de una parcela vecina.
MIN_FRACCION = 0.5
# Las declaraciones se cierran el 15 de mayo: desde junio, la del año ya está hecha.
MES_DECLARACION = 6


def _get(params: dict) -> requests.Response:
    for intento in range(4):
        try:
            r = requests.get(WFS, params=params, headers=_UA, timeout=120)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if intento == 3:
                raise
            time.sleep(5 * (intento + 1))


@lru_cache(maxsize=1)
def anios() -> tuple[set[int], int]:
    """Años con capa propia, y el de RPG.LATEST (el siguiente al último con capa)."""
    xml = _get({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"}).text
    hay = {int(a) for a in re.findall(r"RPG\.(\d{4}):parcelles_graphiques", xml)}
    return hay, max(hay) + 1


@lru_cache(maxsize=1)
def cultivos() -> dict[str, dict]:
    """Código de cultivo → nombre y grupo, del diccionario que publica el IGN."""
    fc = _get({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
               "TYPENAMES": "RPG.LATEST:codes_cultures", "OUTPUTFORMAT": "application/json"}).json()
    return {f["properties"]["code_culture"]: {"libelle": f["properties"]["libelle_culture"],
                                             "groupe": f["properties"]["libelle_groupe_culture"]}
            for f in fc["features"]}


def anio_previo(primera: str) -> int:
    """Última declaración hecha antes de la ventana en la que apareció el cambio."""
    a, m = map(int, primera.split("-"))
    m -= config.VENTANA_MESES - 1            # primer mes de esa ventana
    if m < 1:
        a, m = a - 1, m + 12
    return a if m >= MES_DECLARACION else a - 1


def _capa(anio: int) -> str | None:
    hay, ultimo = anios()
    if anio in hay:
        return f"RPG.{anio}"
    return "RPG.LATEST" if anio == ultimo else None


def uso_de(geom_utm, primera: str) -> dict | None:
    """Cultivo declarado bajo la alerta el año antes del cambio, o None si no hay capa."""
    # Si la declaración de ese año aún no se ha publicado, la última que hay, que también
    # es anterior al cambio.
    anio = min(anio_previo(primera), anios()[1])
    capa = _capa(anio)
    if capa is None:
        return None
    x0, y0, x1, y1 = zona.a_geo(geom_utm).bounds
    fc = _get({"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
               "TYPENAMES": f"{capa}:parcelles_graphiques", "OUTPUTFORMAT": "application/json",
               # Orden lon,lat con EPSG:4326 a secas; con la forma urn el servidor espera lat,lon.
               "BBOX": f"{x0},{y0},{x1},{y1},EPSG:4326"}).json()
    por_codigo: dict[str, float] = {}
    trozos = []
    for f in fc["features"]:
        if not f.get("geometry"):
            continue
        inter = shapely.make_valid(zona.a_utm(shape(f["geometry"]))).intersection(geom_utm)
        if inter.is_empty:
            continue
        p = f["properties"]
        clave = f'{p.get("code_cultu")}|{p.get("code_group")}'
        por_codigo[clave] = por_codigo.get(clave, 0.0) + inter.area
        trozos.append(inter)
    fraccion = shapely.union_all(trozos).area / geom_utm.area if trozos else 0.0
    out = {"anio": anio, "fraccion": round(min(fraccion, 1.0), 3)}
    if not por_codigo:
        return {**out, "uso": "sin_declarar"}
    codigo, grupo = max(por_codigo, key=por_codigo.get).split("|")
    c = cultivos().get(codigo, {})
    out.update(codigo=codigo, libelle=c.get("libelle", codigo), groupe=c.get("groupe"),
               pradera_permanente=grupo in GRUPOS_PRADERA_PERMANENTE)
    if fraccion < MIN_FRACCION:
        out["uso"] = "sin_declarar"
    else:
        out["uso"] = "pradera_permanente" if out["pradera_permanente"] else "rotacion"
    return out
