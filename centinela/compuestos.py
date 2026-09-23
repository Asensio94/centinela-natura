"""Compuesto mensual de NDVI máximo sobre la malla fija.

Un mes se reconstruye siempre entero y desde cero: el máximo es idempotente, así que
volver a calcular el mes en curso cada día no deja estado intermedio que se pueda
corromper, y las escenas que Earth Search publica con retraso entran solas.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import rasterio
import xarray as xr
from odc.stac import configure_rio, load
from rich.console import Console

from . import config, stac, zona

configure_rio(cloud_defaults=True, aws={"aws_unsigned": True})
con = Console()
BLOQUE = 1024           # píxeles; 10,24 km de lado


def ruta(mes: str) -> Path:
    return config.COMPUESTOS_DIR / f"ndvi_{mes}.tif"


def _bloques():
    """Trozos de la malla que tocan la Red Natura. Los demás no se descargan."""
    gb, m = zona.malla(), zona.mascara()
    ny, nx = gb.shape
    for y0 in range(0, ny, BLOQUE):
        for x0 in range(0, nx, BLOQUE):
            ys, xs = slice(y0, min(y0 + BLOQUE, ny)), slice(x0, min(x0 + BLOQUE, nx))
            if m[ys, xs].any():
                yield ys, xs


def _bloque(items, ys, xs) -> tuple[np.ndarray, np.ndarray]:
    """NDVI máximo y observaciones válidas de un trozo de la malla.

    Las escenas se cargan por grupos según el desplazamiento que haya que restarles, porque
    `load` junta en un mismo día escenas de teselas distintas y no deja corregir cada una.
    Cada grupo da su máximo y su recuento, y se combinan al final.
    """
    gb = zona.malla()[ys, xs]
    grupos: dict[int, list] = {}
    for it in items:
        grupos.setdefault(stac.desplazamiento_nd(it), []).append(it)
    mx_tot = n_tot = None
    for resta, grupo in grupos.items():
        ds = load(grupo, bands=["red", "nir", "scl"], geobox=gb, groupby="solar_day",
                  resampling="nearest", chunks={"x": BLOQUE, "y": BLOQUE, "time": 1},
                  fail_on_error=False)
        # El 0 es sin dato: se mira antes de restar.
        ok = ds["scl"].isin(list(config.SCL_VALIDAS)) & (ds["red"] > resta) & (ds["nir"] > resta)
        red = ds["red"].astype("float32") - resta
        nir = ds["nir"].astype("float32") - resta
        ndvi = ((nir - red) / (nir + red)).where(ok)
        mx, n = ndvi.max("time", skipna=True), ok.sum("time")
        mx, n = (v.compute(scheduler="threads", num_workers=config.DASK_HILOS).values
                 for v in (mx, n))
        # Donde dos teselas se solapan el mismo día en grupos distintos, la pasada cuenta
        # dos veces; es una franja estrecha y solo en los meses con escenas mezcladas.
        mx_tot = mx if mx_tot is None else np.fmax(mx_tot, mx)
        n_tot = n if n_tot is None else n_tot + n
    return mx_tot, n_tot


def construir(mes: str) -> dict:
    t0 = time.time()
    items = stac.escenas_mes(mes)
    corregidas = sum(1 for i in items if stac.desplazamiento_nd(i))
    if corregidas:
        con.log(f"{mes}: {corregidas} escenas con el desplazamiento de -1000 sin restar; se resta aquí")
    gb, m = zona.malla(), zona.mascara()
    ndvi_q = np.full(gb.shape, config.NDVI_NODATA, dtype="uint8")
    nobs = np.zeros(gb.shape, dtype="uint8")
    fechas = sorted({i.datetime.date().isoformat() for i in items})
    if items:
        bloques = list(_bloques())
        for k, (ys, xs) in enumerate(bloques, 1):
            mx, n = _bloque(items, ys, xs)
            q = np.where(np.isnan(mx), config.NDVI_NODATA,
                         np.clip(np.rint((mx + 1) * 100), 0, 200)).astype("uint8")
            ndvi_q[ys, xs] = q
            nobs[ys, xs] = np.clip(n, 0, 254).astype("uint8")
            con.log(f"{mes} bloque {k}/{len(bloques)}")
    ndvi_q[~m] = config.NDVI_NODATA
    nobs[~m] = 0
    meta = {"mes": mes, "escenas": len(items), "corregidas": corregidas, "fechas": fechas,
            "pixeles_con_dato": int((ndvi_q != config.NDVI_NODATA).sum()),
            "pixeles_zona": int(m.sum()), "segundos": round(time.time() - t0)}
    escribir(mes, ndvi_q, nobs, meta)
    return meta


def escribir(mes: str, ndvi_q, nobs, meta) -> Path:
    gb = zona.malla()
    p = ruta(mes)
    perfil = dict(driver="GTiff", width=gb.shape.x, height=gb.shape.y, count=2, dtype="uint8",
                  crs=config.CRS, transform=gb.transform, nodata=None, compress="deflate",
                  predictor=2, zlevel=6, tiled=True, blockxsize=512, blockysize=512)
    tmp = p.with_suffix(".tmp.tif")
    with rasterio.open(tmp, "w", **perfil) as dst:
        dst.write(ndvi_q, 1)
        dst.write(nobs, 2)
        dst.set_band_description(1, "NDVI maximo del mes: valor/100 - 1; 255 sin dato")
        dst.set_band_description(2, "observaciones validas en el mes")
        dst.update_tags(centinela=json.dumps(meta))
    tmp.replace(p)
    return p


def leer(mes: str) -> tuple[np.ndarray, np.ndarray, dict]:
    with rasterio.open(ruta(mes)) as src:
        return src.read(1), src.read(2), json.loads(src.tags().get("centinela", "{}"))


def leer_trozo(mes: str, ys: slice, xs: slice) -> tuple[np.ndarray, np.ndarray] | None:
    """Solo un recuadro del compuesto, sin leer el fichero entero."""
    from rasterio.windows import Window
    if not ruta(mes).exists():
        return None
    with rasterio.open(ruta(mes)) as src:
        w = Window(xs.start, ys.start, xs.stop - xs.start, ys.stop - ys.start)
        return src.read(1, window=w, boundless=True, fill_value=config.NDVI_NODATA),             src.read(2, window=w, boundless=True, fill_value=0)


def a_ndvi(q: np.ndarray) -> np.ndarray:
    out = q.astype("float32") / 100 - 1
    out[q == config.NDVI_NODATA] = np.nan
    return out
