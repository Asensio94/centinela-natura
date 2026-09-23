"""Qué ha pasado en cada cambio: fotos antes/después y una clase por reglas espectrales.

Para cada cambio nuevo se busca la escena más limpia sobre ese punto en la ventana actual y
otra del mismo periodo del año anterior. De ellas salen las dos fotos que se publican y
los índices con los que se decide la clase. Las reglas son umbrales publicados en la
literatura, no un clasificador entrenado:

- agua nueva: MNDWI > 0 (Xu 2006) con NDVI bajo;
- quemado: caída de NBR > 0,27, el umbral de severidad moderada de Key y Benson (2006),
  con el infrarrojo cercano hundido y el visible oscuro, que es lo que separa la ceniza
  del suelo desnudo de una explanación;
- suelo desnudo o movimiento de tierras: índice de suelo desnudo (BSI) positivo;
- superficie oscura: NDVI bajo, sin agua y con reflectancia baja en todo el espectro
  (asfalto, placas solares, cubiertas);
- el resto es pérdida de vegetación sin más precisión (corta, desbroce, siega tardía).
"""
from __future__ import annotations

from datetime import date

import numpy as np
import requests
from odc.geo.geobox import GeoBox
from odc.geo.geom import Geometry
from odc.geo.xr import rasterize
from odc.stac import load
from PIL import Image
from scipy.ndimage import binary_erosion

from . import compuestos, config, stac, zona
from .deteccion import meses_ventana

BANDAS = ["blue", "green", "red", "nir", "swir16", "swir22", "scl"]
CLC_URL = ("https://image.discomap.eea.europa.eu/arcgis/rest/services/Corine/"
           "CLC2018_WM/MapServer/0/query")
CLC = {
    "111": "tejido urbano continuo", "112": "tejido urbano discontinuo",
    "121": "zona industrial o comercial", "122": "red viaria o ferroviaria", "123": "zona portuaria",
    "124": "aeropuerto", "131": "extracción minera", "132": "escombrera o vertedero",
    "133": "zona en construcción", "141": "zona verde urbana", "142": "instalación deportiva",
    "211": "labor de secano", "212": "regadío", "221": "viñedo", "222": "frutales",
    "231": "prados y praderas", "242": "mosaico de cultivos",
    "243": "terreno agrícola con vegetación natural", "311": "bosque de frondosas",
    "312": "bosque de coníferas", "313": "bosque mixto", "321": "pastizal natural",
    "322": "landas y matorral", "323": "vegetación esclerófila",
    "324": "matorral boscoso de transición", "331": "playas, dunas y arenales", "332": "roquedo",
    "333": "vegetación escasa", "334": "zona quemada", "411": "humedal continental",
    "421": "marisma", "423": "zona intermareal", "511": "curso de agua", "512": "lámina de agua",
    "521": "laguna costera", "522": "estuario",
}
# Sube cuando cambian las reglas de fotos o clases: las alertas activas analizadas con
# una versión anterior se vuelven a analizar.
VERSION = 2
# Coberturas CORINE que ya eran agua: agua «nueva» sobre ellas es el nivel que sube.
CLC_AGUA = {"411", "421", "423", "511", "512", "521", "522"}
# Embalses y lagos: su orilla es agua, pasto o barro según el nivel, y el barro mojado
# (oscuro, sin infrarrojo) pasa por quemado. Ahí cualquier clase es el nivel. En marismas
# y estuarios no, porque un relleno es justo lo que hay que ver.
CLC_EMBALSE = {"512"}
CLASES = {
    "agua": "Lámina de agua nueva",
    "quemado": "Superficie quemada",
    "suelo": "Suelo desnudo o movimiento de tierras",
    "oscuro": "Superficie artificial oscura",
    "vegetacion": "Pérdida de vegetación",
}


def cubierta_previa(geom_utm) -> dict | None:
    """Clase CORINE 2018 en el cambio: el uso que había antes, con 25 ha de detalle.

    CORINE se hace por fotointerpretación, no con un clasificador automático, así que usarlo
    como contexto no mete ningún modelo entrenado en la cadena.
    """
    c = zona.a_geo(geom_utm.representative_point())
    try:
        r = requests.get(CLC_URL, timeout=60, params={
            "geometry": f"{c.x},{c.y}", "geometryType": "esriGeometryPoint", "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects", "outFields": "Code_18",
            "returnGeometry": "false", "f": "json"})
        feats = r.json().get("features", [])
    except (requests.RequestException, ValueError):
        return None
    if not feats:
        return None
    code = feats[0]["attributes"]["Code_18"]
    return {"codigo": code, "nombre": CLC.get(code, code)}


def _caja(geom_utm) -> GeoBox:
    """Recuadro de la foto: el cambio centrado con su entorno, alineado a la malla."""
    x0, y0, x1, y1 = geom_utm.bounds
    lado = max(x1 - x0, y1 - y0) * 2.2 + 600
    r = config.RESOLUCION_M
    h = np.ceil(lado / 2 / r) * r
    cx, cy = np.round((x0 + x1) / 2 / r) * r, np.round((y0 + y1) / 2 / r) * r
    return GeoBox.from_bbox((cx - h, cy - h, cx + h, cy + h), crs=config.CRS, resolution=r)


def _mejor_escena(items, gb: GeoBox, dentro: np.ndarray, max_dias: int = 16):
    """La escena despejada de NDVI más alto en el cambio: su mejor momento de la ventana.

    Despejada quiere decir lo mismo que en los compuestos (`compuestos.valida`). Elegir la
    más verde reproduce lo que mide el detector, que compara máximos. Antes, así la foto
    no enseña ya hecho un cambio ocurrido dentro de la ventana de referencia. Después,
    cualquier escena de la ventana es posterior al cambio (su máximo ya es bajo), y la más
    verde descarta de paso la nube que la SCL deja pasar, que hunde el NDVI.

    Las bandas de todas las fechas candidatas se leen de una vez y en paralelo: son unos
    pocos kilobytes por fecha, y leerlas de una en una costaba más en esperas de red que en
    datos.
    """
    if not items:
        return None
    por_dia: dict = {}
    for it in items:
        por_dia.setdefault(it.datetime.date(), []).append(it)
    dias = sorted(por_dia, key=lambda d: min(i.properties["eo:cloud_cover"] for i in por_dia[d]))[:max_dias]
    sel = [i for d in dias for i in por_dia[d]]
    bandas = ["scl", "green", "red", "nir", "swir16"]
    ds = load(sel, bands=bandas, geobox=gb, groupby="solar_day", resampling="nearest",
              chunks={}, fail_on_error=False)
    ds = ds.compute(scheduler="threads", num_workers=config.DASK_HILOS)
    candidatos = []
    for k, t in enumerate(ds["time"].values):
        dia = np.datetime64(t, "D").astype(object)
        resta = max((stac.desplazamiento_nd(i) for i in por_dia.get(dia, [])), default=0)
        b = {n: (ds[n].values[k].astype("float32") - resta) * 1e-4
             for n in ("green", "red", "nir", "swir16")}
        with np.errstate(divide="ignore", invalid="ignore"):
            ok = (b["red"] > 0) & compuestos.valida(ds["scl"].values[k], b["green"], b["nir"], b["swir16"])
        f_dentro = float(ok[dentro].mean()) if dentro.any() else 0.0
        ndvi = -1.0
        if (ok & dentro).any():
            v = _nd(b["nir"], b["red"])[ok & dentro]
            ndvi = float(np.median(v)) if v.size else -1.0
        candidatos.append((f_dentro, float(ok.mean()), dia, ndvi))
    limpias = [c for c in candidatos if c[0] >= 0.95 and c[1] >= 0.85]
    if limpias:
        d = max(limpias, key=lambda c: (c[3], c[2]))[2]
    else:
        # De reserva, la menos nublada; si ni así se ve el entorno, mejor sin foto.
        f, f_caja, d, _ = max(candidatos, key=lambda c: (c[0], c[2]))
        if f < 0.8 or f_caja < 0.6:
            return None
    return d, por_dia[d]


def _cargar(items, gb) -> dict:
    """Reflectancias de un día, con el desplazamiento de cada escena restado si hace falta."""
    grupos: dict[int, list] = {}
    for it in items:
        grupos.setdefault(stac.desplazamiento_nd(it), []).append(it)
    out: dict = {}
    for resta, grupo in grupos.items():
        ds = load(grupo, bands=BANDAS, geobox=gb, groupby="solar_day", resampling="nearest",
                  fail_on_error=False).isel(time=0)
        for b in BANDAS:
            if b == "scl":
                continue
            v = ds[b].values.astype("float32")
            v[v <= resta] = np.nan                  # 0 es sin dato
            v = (v - resta) * 1e-4
            out[b] = v if b not in out else np.where(np.isnan(out[b]), v, out[b])
    return out


def _nd(a, b):
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a - b) / (a + b)


def _indices(b: dict, sel: np.ndarray) -> dict:
    ndvi = _nd(b["nir"], b["red"])
    mndwi = _nd(b["green"], b["swir16"])
    nbr = _nd(b["nir"], b["swir22"])
    bsi = _nd(b["swir16"] + b["red"], b["nir"] + b["blue"])
    brillo = (b["blue"] + b["green"] + b["red"]) / 3

    def med(a):
        v = a[sel]
        v = v[np.isfinite(v)]
        return round(float(np.median(v)), 3) if v.size else None

    return {"ndvi": med(ndvi), "mndwi": med(mndwi), "nbr": med(nbr), "bsi": med(bsi),
            "nir": med(b["nir"]), "swir22": med(b["swir22"]), "brillo": med(brillo)}


def clase(antes: dict, despues: dict) -> str:
    if any(v is None for v in (*antes.values(), *despues.values())):
        return "vegetacion"
    if despues["mndwi"] > 0 and despues["ndvi"] < 0.15:
        return "agua"
    # Quemado: caída de NBR de severidad moderada o más, con el infrarrojo cercano hundido
    # y el visible todavía oscuro. Una explanación también baja el NBR, pero aclara la
    # superficie: el brillo es lo que separa la ceniza y la vegetación chamuscada del suelo.
    if (antes["nbr"] - despues["nbr"] > 0.27 and despues["nir"] < 0.8 * antes["nir"]
            and despues["brillo"] < 0.10):
        return "quemado"
    if despues["bsi"] > 0.05 and despues["ndvi"] < 0.25:
        return "suelo"
    if despues["ndvi"] < 0.2 and despues["brillo"] < 0.08 and despues["nir"] < 0.15:
        return "oscuro"
    return "vegetacion"


def _foto(b: dict, dentro: np.ndarray, ruta) -> None:
    rgb = np.dstack([b["red"], b["green"], b["blue"]])
    rgb = np.clip(np.nan_to_num(rgb) / 0.22, 0, 1) ** (1 / 1.6)
    arr = (rgb * 255).astype("uint8")
    borde = dentro & ~binary_erosion(dentro)
    arr[borde] = (255, 214, 0)          # contorno del cambio en amarillo
    img = Image.fromarray(arr)
    escala = max(1, 360 // max(img.size))
    if escala > 1:
        img = img.resize((img.size[0] * escala, img.size[1] * escala), Image.NEAREST)
    img.save(ruta, "JPEG", quality=86)


def analizar(alerta_id: str, geom_utm, mes_fin: str) -> dict:
    """Fotos y clase de un cambio. Devuelve lo que haya podido averiguar."""
    gb = _caja(geom_utm)
    dentro = rasterize(Geometry(geom_utm, config.CRS), gb).values.astype(bool)
    bbox_geo = zona.a_geo(geom_utm.envelope.buffer(50)).bounds
    res: dict = {"cubierta_previa": cubierta_previa(geom_utm), "analisis_v": VERSION}

    def escenas(anios_atras):
        ms = meses_ventana(mes_fin, anios_atras)
        ini = stac.rango_mes(ms[0])[0]
        fin = min(stac.rango_mes(ms[-1])[1], date.today())
        return stac.buscar(bbox_geo, ini, fin)

    esc_d = _mejor_escena(escenas(0), gb, dentro)
    esc_a = _mejor_escena(escenas(1), gb, dentro)
    if not esc_d or not esc_a:
        res["clase"] = "vegetacion"
        res["clase_nota"] = "sin escena despejada para las fotos"
        return res
    bd, ba = _cargar(esc_d[1], gb), _cargar(esc_a[1], gb)
    iv_d, iv_a = _indices(bd, dentro), _indices(ba, dentro)
    res.update({
        "clase": clase(iv_a, iv_d),
        "indices_antes": iv_a, "indices_despues": iv_d,
        "fecha_antes": esc_a[0].isoformat(), "fecha_despues": esc_d[0].isoformat(),
        "foto_antes": f"chips/{alerta_id}_antes.jpg", "foto_despues": f"chips/{alerta_id}_despues.jpg",
    })
    _foto(ba, dentro, config.CHIPS_DIR / f"{alerta_id}_antes.jpg")
    _foto(bd, dentro, config.CHIPS_DIR / f"{alerta_id}_despues.jpg")
    return res
