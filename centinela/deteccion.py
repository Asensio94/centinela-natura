"""Detección de cambios: vegetación estable que deja de estarlo, por reglas fijas.

Para una ventana de meses que acaba en `mes_fin` se compara el NDVI máximo de la ventana
este año con el de la misma ventana en los años anteriores. Un píxel es candidato cuando
fue vegetación densa todos los años de referencia y ahora, en su mejor momento de toda la
ventana, no lo es. Los píxeles candidatos contiguos forman un cambio, que tiene que
superar la unidad mínima.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from rasterio.features import shapes
from scipy import ndimage
from shapely.geometry import shape
from shapely.ops import unary_union

from . import compuestos, config, zona

_q = lambda v: int(round((v + 1) * 100))          # NDVI -> valor guardado en el compuesto


def meses_ventana(mes_fin: str, anios_atras: int = 0, n: int = config.VENTANA_MESES) -> list[str]:
    y, m = map(int, mes_fin.split("-"))
    y -= anios_atras
    out = []
    for k in range(n - 1, -1, -1):
        mm, yy = m - k, y
        while mm < 1:
            mm, yy = mm + 12, yy - 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def meses_necesarios(mes_fin: str) -> list[str]:
    return sorted({mm for a in range(config.ANIOS_REFERENCIA + 1) for mm in meses_ventana(mes_fin, a)})


def _ventana(meses: list[str], m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Máximo y observaciones de la ventana, solo en los píxeles de la zona (vector 1D)."""
    mx = np.full(int(m.sum()), -1, dtype="int16")
    n = np.zeros(int(m.sum()), dtype="int16")
    for mes in meses:
        q, obs, _ = compuestos.leer(mes)
        q, obs = q[m].astype("int16"), obs[m].astype("int16")
        q[q == config.NDVI_NODATA] = -1
        np.maximum(mx, q, out=mx)
        n += obs
    return mx, n


@dataclass
class Cambio:
    geom: object            # polígono en config.CRS
    pixeles: int
    ndvi_ref: float         # media de la referencia (el año más bajo de los dos)
    ndvi_actual: float
    obs_actual: int         # observaciones válidas medianas en la ventana actual

    @property
    def ha(self) -> float:
        return round(self.pixeles * config.PIXEL_HA, 2)


def detectar(mes_fin: str) -> tuple[list[Cambio], dict, dict]:
    m = zona.mascara()
    cur, ncur = _ventana(meses_ventana(mes_fin), m)
    refs = [_ventana(meses_ventana(mes_fin, a), m) for a in range(1, config.ANIOS_REFERENCIA + 1)]
    refmin = np.min([r for r, _ in refs], axis=0)
    ok = (cur >= 0) & (ncur >= config.OBS_MIN)
    for r, nr in refs:
        ok &= (r >= 0) & (nr >= config.OBS_MIN)
    flag1 = (ok & (refmin >= _q(config.NDVI_REF_MIN)) & (cur <= _q(config.NDVI_ACTUAL_MAX))
             & (refmin - cur >= round(config.CAIDA_MIN * 100)))

    stats = {"mes_fin": mes_fin, "ventana": meses_ventana(mes_fin),
             "pixeles_zona": int(m.sum()), "pixeles_evaluables": int(ok.sum()),
             "fraccion_evaluable": round(float(ok.mean()), 3),
             "pixeles_candidatos": int(flag1.sum())}

    flag = np.zeros(m.shape, dtype=bool)
    flag[m] = flag1
    # Se reparten los valores 1D de vuelta a la malla solo para los píxeles marcados.
    ref2d = np.zeros(m.shape, dtype="int16"); ref2d[m] = refmin
    cur2d = np.zeros(m.shape, dtype="int16"); cur2d[m] = cur
    n2d = np.zeros(m.shape, dtype="int16"); n2d[m] = ncur

    lab, nlab = ndimage.label(flag, structure=np.ones((3, 3)))
    tam = np.bincount(lab.ravel())
    gb = zona.malla()
    cambios = []
    for k, sl in enumerate(ndimage.find_objects(lab), 1):
        if sl is None or tam[k] < config.UMA_PIXELES:
            continue
        sub = lab[sl] == k
        tr = gb[sl].transform
        geom = unary_union([shape(g) for g, v in shapes(sub.astype("uint8"), mask=sub, transform=tr) if v])
        cambios.append(Cambio(geom=geom, pixeles=int(tam[k]),
                              ndvi_ref=round(float(ref2d[sl][sub].mean()) / 100 - 1, 3),
                              ndvi_actual=round(float(cur2d[sl][sub].mean()) / 100 - 1, 3),
                              obs_actual=int(np.median(n2d[sl][sub]))))
    stats["cambios"] = len(cambios)
    stats["ha_cambios"] = round(sum(c.ha for c in cambios), 1)
    cur2d[~m] = -1
    return cambios, stats, {"cur": cur2d, "n": n2d}


def ndvi_actual_en(geom_utm, capas: dict) -> tuple[float | None, int]:
    """NDVI máximo medio de la ventana actual dentro de un polígono (para ver si revierte)."""
    from odc.geo.geom import Geometry
    from odc.geo.xr import rasterize
    gb = zona.malla()
    r = config.RESOLUCION_M
    x0, y0, x1, y1 = geom_utm.bounds
    c0 = max(int((x0 - gb.transform.c) // r) - 1, 0)
    f0 = max(int((gb.transform.f - y1) // r) - 1, 0)
    c1 = int((x1 - gb.transform.c) // r) + 2
    f1 = int((gb.transform.f - y0) // r) + 2
    ys, xs = slice(f0, f1), slice(c0, c1)
    dentro = rasterize(Geometry(geom_utm, config.CRS), gb[ys, xs]).values.astype(bool)
    cur, n = capas["cur"][ys, xs], capas["n"][ys, xs]
    sel = dentro & (cur > 0) & (n >= config.OBS_MIN)
    if sel.sum() < max(1, dentro.sum() // 2):
        return None, 0
    return round(float(cur[sel].mean()) / 100 - 1, 3), int(np.median(n[sel]))
