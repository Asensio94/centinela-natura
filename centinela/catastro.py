"""Parcelas catastrales de cada alerta, del servicio de descargas INSPIRE del Catastro.

Se usa la descarga por municipio (ATOM) y no el WFS: el WFS limita cada consulta a un
kilómetro cuadrado y desde los servidores de GitHub corta la conexión a menudo, mientras
que los ficheros del ATOM se sirven como estáticos. Cada municipio es un zip de unos pocos
megas que el Catastro rehace una vez al mes.

INSPIRE solo trae la geometría, la referencia y la superficie de cada parcela. No hay
titulares ni ningún dato personal.
"""
from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from functools import lru_cache

import numpy as np
import requests
import shapely
from rich.console import Console
from shapely.geometry import Polygon, box

from . import config, zona

con = Console()

ATOM = "https://www.catastro.hacienda.gob.es/INSPIRE/CadastralParcels/39/ES.SDGC.CP.atom_39.xml"
SEDE = "https://www1.sedecatastro.gob.es/Cartografia/mapa.aspx?refcat={}"
_UA = {"User-Agent": "centinela-natura (+https://github.com/Asensio94/centinela-natura)"}
_NS = {"a": "http://www.w3.org/2005/Atom", "georss": "http://www.georss.org/georss"}
_CP = "{http://inspire.ec.europa.eu/schemas/cp/4.0}"
_GML = "{http://www.opengis.net/gml/3.2}"
DIR = config.CACHE_DIR / "catastro"
# Una parcela cuenta si la alerta le quita al menos dos píxeles, o si cae casi entera dentro
# (las urbanas pequeñas). Con menos, es el borde en escalera del polígono de 10 m.
MIN_M2 = 200
MIN_FRACCION_PARCELA = 0.5
MAX_PARCELAS = 40


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


def norm_municipio(s: str) -> str:
    """«Los Corrales de Buelna» y «CORRALES DE BUELNA» quedan iguales."""
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s)
    s = re.sub(r"^(el|la|los|las) ", "", " ".join(s.split()))
    return s


@lru_cache(maxsize=1)
def municipios() -> list[dict]:
    """Municipios del ATOM con su caja en UTM, su zip y la fecha de la última versión."""
    DIR.mkdir(parents=True, exist_ok=True)
    cache = DIR / "atom_39.xml"
    try:
        cache.write_bytes(_get(ATOM).content)
    except requests.RequestException:
        if not cache.exists():
            raise
    raiz = ET.fromstring(cache.read_bytes())
    out = []
    for e in raiz.findall("a:entry", _NS):
        enl = e.find("a:link[@rel='enclosure']", _NS)
        pol = e.find("georss:polygon", _NS)
        if enl is None or pol is None:
            continue
        url = enl.get("href")
        m = re.search(r"/39/(\d{5})-([^/]+)/", url)
        if not m:
            continue
        v = list(map(float, pol.text.split()))
        lat, lon = v[0::2], v[1::2]              # georss va en latitud, longitud
        caja = zona.a_utm(box(min(lon), min(lat), max(lon), max(lat)))
        out.append({"codigo": m.group(1), "nombre": m.group(2).strip(), "url": url,
                    "actualizado": (e.findtext("a:updated", "", _NS) or "")[:10], "caja": caja})
    return out


def nombre_municipio(codigo: str) -> str | None:
    try:
        return next((m["nombre"] for m in municipios() if m["codigo"] == codigo), None)
    except requests.RequestException:
        return None


def _anillo(pos: ET.Element | None) -> np.ndarray | None:
    if pos is None or not pos.text:
        return None
    return np.array(pos.text.split(), dtype=float).reshape(-1, 2)


def _leer_gml(f) -> tuple[list[str], list[float], list]:
    """Referencia, superficie y geometría de cada parcela, leyendo el GML en flujo."""
    refs, areas, geoms = [], [], []
    for _, el in ET.iterparse(f, events=("end",)):
        if el.tag != _CP + "CadastralParcel":
            continue
        ref = el.findtext(_CP + "nationalCadastralReference")
        polis = []
        for patch in el.iter(_GML + "PolygonPatch"):
            ext = _anillo(patch.find(f"{_GML}exterior/{_GML}LinearRing/{_GML}posList"))
            if ext is None or len(ext) < 4:
                continue
            ints = [a for a in (_anillo(i.find(f"{_GML}LinearRing/{_GML}posList"))
                                for i in patch.findall(_GML + "interior")) if a is not None and len(a) >= 4]
            polis.append(Polygon(ext, ints))
        if ref and polis:
            g = shapely.make_valid(shapely.MultiPolygon(polis) if len(polis) > 1 else polis[0])
            refs.append(ref)
            areas.append(float(el.findtext(_CP + "areaValue") or 0))
            geoms.append(g)
        el.clear()
    return refs, areas, geoms


@lru_cache(maxsize=8)
def _parcelas_municipio(codigo: str):
    """Parcelas de un municipio con un índice espacial. Se guarda el zip del mes en caché."""
    m = next(x for x in municipios() if x["codigo"] == codigo)
    zp = DIR / f"{codigo}_{m['actualizado']}.zip"
    if not zp.exists():
        for viejo in DIR.glob(f"{codigo}_*.zip"):
            viejo.unlink()
        con.log(f"catastro: bajando {codigo} {m['nombre']}")
        zp.write_bytes(_get(m["url"]).content)
    with zipfile.ZipFile(zp) as z:
        nombre = next(n for n in z.namelist() if n.endswith("cadastralparcel.gml"))
        with z.open(nombre) as f:
            refs, areas, geoms = _leer_gml(f)
    return refs, areas, geoms, shapely.STRtree(geoms)


def desglosar(ref: str) -> dict:
    """Una referencia rústica lleva municipio, polígono y parcela; una urbana, la manzana."""
    if len(ref) == 14 and ref[5].isalpha() and ref[6:].isdigit():
        d = {"tipo": "rustica", "poligono": int(ref[6:9]), "parcela": int(ref[9:14])}
        # Del 9000 en adelante son parcelas de descuento: caminos, arroyos y demás dominio
        # público que el Catastro dibuja como parcela.
        if 9000 <= d["parcela"] < 10000:
            d["descuento"] = True
        return d
    return {"tipo": "urbana"}


def parcelas_de(geom_utm) -> dict:
    """Parcelas que toca una alerta, de mayor a menor superficie afectada.

    Las coordenadas del Catastro van en ETRS89 / UTM 30N y la malla en WGS84 / UTM 30N:
    los dos marcos difieren en menos de un metro, muy por debajo del píxel de 10 m.
    """
    area = geom_utm.area
    hallado, cubierto, actualizado = [], [], set()
    for m in municipios():
        if not m["caja"].intersects(geom_utm):
            continue
        refs, areas, geoms, arbol = _parcelas_municipio(m["codigo"])
        for i in arbol.query(geom_utm, predicate="intersects"):
            inter = geoms[i].intersection(geom_utm)
            a = inter.area
            if a < MIN_M2 and a < MIN_FRACCION_PARCELA * geoms[i].area:
                continue
            cubierto.append(inter)
            actualizado.add(m["actualizado"])
            hallado.append({"refcat": refs[i], "municipio": m["codigo"], "municipio_nombre": m["nombre"],
                            **desglosar(refs[i]),
                            "ha_parcela": round(areas[i] / 1e4, 2), "ha_alerta": round(a / 1e4, 2)})
    hallado.sort(key=lambda p: -p["ha_alerta"])
    fr = shapely.union_all(cubierto).area / area if cubierto else 0.0
    return {"parcelas": hallado[:MAX_PARCELAS], "n_parcelas": len(hallado),
            # Lo que no cae en ninguna parcela es dominio público sin parcelar: cauces,
            # carreteras, caminos y, en la costa, el dominio marítimo-terrestre.
            "fraccion_parcelada": round(min(fr, 1.0), 3),
            "catastro_fecha": max(actualizado) if actualizado else None}
