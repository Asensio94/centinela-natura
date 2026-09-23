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
    gb = zona.malla()[ys, xs]
    ds = load(items, bands=["red", "nir", "scl"], geobox=gb, groupby="solar_day",
              resampling="nearest", chunks={"x": BLOQUE, "y": BLOQUE, "time": 1},
              fail_on_error=False)
    red = ds["red"].astype("float32")
    nir = ds["nir"].astype("float32")
    ok = ds["scl"].isin(list(config.SCL_VALIDAS)) & (red > 0) & (nir > 0)
    ndvi = ((nir - red) / (nir + red)).where(ok)
    mx = ndvi.max("time", skipna=True)
    n = ok.sum("time")
    mx, n = (v.compute(scheduler="threads", num_workers=config.DASK_HILOS) for v in (mx, n))
    return mx.values, n.values


def construir(mes: str) -> dict:
    t0 = time.time()
    items = stac.escenas_mes(mes)
    malos = [i.id for i in items if not stac.offset_aplicado(i)]
    if malos:
        # El NDVI se calcula sobre los niveles digitales tal cual, lo que solo es válido si
        # ninguna escena arrastra el desplazamiento de -1000. Mejor parar que sesgar.
        raise RuntimeError(f"{len(malos)} escenas sin offset aplicado, p. ej. {malos[0]}")
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
    meta = {"mes": mes, "escenas": len(items), "fechas": fechas,
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
