"""Registro de alertas y su ciclo de vida.

Una alerta nace provisional la primera vez que aparece un cambio. Pasa a confirmada si el
cambio sigue ahí en la ventana de un mes posterior: con ventanas que se solapan, eso quiere
decir que el suelo lleva al menos un mes más sin vegetación. Si la vegetación vuelve antes
de confirmarse, se descarta, porque lo normal es que fuera una siega tardía, un cultivo o
un error de nubes; también se descarta si no se vuelve a ver en ninguna ventana hasta la
primera que ya no comparte meses con la suya. Si vuelve después de confirmada, pasa a
revertida. Las alertas no se borran nunca: el registro es acumulativo y cada cambio de
estado lleva su fecha.
"""
from __future__ import annotations

import json
import time
from datetime import date, datetime, timezone

import numpy as np
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from rich.console import Console

from . import clasificacion, compuestos, config, deteccion, expedientes, zona

con = Console()
ACTIVAS = ("provisional", "confirmada")
# NDVI a partir del cual se da por recuperada la vegetación de una alerta: bastante por
# encima del umbral de detección para que un píxel que oscila en el límite no vaya y venga.
NDVI_RECUPERADA = config.NDVI_ACTUAL_MAX + 0.15
# Tiempo de análisis por ejecución (cada alerta lleva de 10 a 20 s de descargas). Lo que
# no quepa se analiza al día siguiente; las más grandes van primero.
ANALISIS_MINUTOS = 45


def cargar() -> dict:
    if config.ALERTAS_JSON.exists():
        return json.loads(config.ALERTAS_JSON.read_text(encoding="utf-8"))
    return {"alertas": [], "ejecuciones": {}}


def guardar(reg: dict) -> None:
    reg["actualizado"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    config.ALERTAS_JSON.write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")


def _geom_utm(a: dict):
    # El GeoJSON va redondeado a 6 decimales en grados: al volver a UTM algún anillo puede
    # quedar cruzado, y shapely no une geometrías inválidas.
    return make_valid(zona.a_utm(shape(a["geometry"])))


def _geojson(geom_utm) -> dict:
    g = zona.a_geo(geom_utm)
    return json.loads(json.dumps(mapping(g), default=float),
                      parse_float=lambda s: round(float(s), 6))


def _nuevo_id(reg: dict, mes: str) -> str:
    pref = f"CN-{mes.replace('-', '')}-"
    n = sum(1 for a in reg["alertas"] if a["id"].startswith(pref))
    return f"{pref}{n + 1:03d}"


def _meses_entre(a: str, b: str) -> int:
    ya, ma = map(int, a.split("-"))
    yb, mb = map(int, b.split("-"))
    return (yb - ya) * 12 + mb - ma


def ultima_vegetacion(geom_utm, mes_fin: str, meses_atras: int = 14) -> str | None:
    """Último mes con vegetación densa en el polígono: acota cuándo ocurrió el cambio."""
    gb = zona.malla()
    r = config.RESOLUCION_M
    x0, y0, x1, y1 = geom_utm.bounds
    xs = slice(int((x0 - gb.transform.c) // r), int((x1 - gb.transform.c) // r) + 1)
    ys = slice(int((gb.transform.f - y1) // r), int((gb.transform.f - y0) // r) + 1)
    from odc.geo.geom import Geometry
    from odc.geo.xr import rasterize
    dentro = rasterize(Geometry(geom_utm, config.CRS), gb[ys, xs]).values.astype(bool)
    umbral = round((config.NDVI_REF_MIN + 1) * 100)
    y, m = map(int, mes_fin.split("-"))
    for k in range(meses_atras + 1):
        mm, yy = m - k, y
        while mm < 1:
            mm, yy = mm + 12, yy - 1
        mes = f"{yy:04d}-{mm:02d}"
        t = compuestos.leer_trozo(mes, ys, xs)
        if t is None:
            continue
        q = t[0][dentro]
        q = q[q != config.NDVI_NODATA]
        if q.size >= dentro.sum() * 0.5 and np.median(q) >= umbral:
            return mes
    return None


# Campos que escribe el análisis: se borran antes de rehacerlo para que no quede una foto
# vieja junto a una clase nueva.
CAMPOS_ANALISIS = ("cubierta_previa", "analisis_v", "clase", "clase_nombre", "clase_nota",
                   "indices_antes", "indices_despues", "fecha_antes", "fecha_despues",
                   "foto_antes", "foto_despues", "ventana_fotos")


def _nivel_del_agua(a: dict) -> bool:
    """Cambio en la orilla de un embalse, o agua nueva donde CORINE ya cartografiaba agua."""
    cod = (a.get("cubierta_previa") or {}).get("codigo")
    return cod in clasificacion.CLC_EMBALSE or (a.get("clase") == "agua" and cod in clasificacion.CLC_AGUA)


def _pendiente(a: dict) -> bool:
    if a["estado"] not in ACTIVAS:
        return False
    if a.get("analisis_v") != clasificacion.VERSION:
        return True
    # Sin fotos en su ventana (nieve, nube persistente): se reintenta cada vez que se vuelve
    # a ver en una ventana nueva.
    return not a.get("foto_despues") and a.get("ventana_fotos") != a["ultima"]


def _ventanas_fotos(a: dict) -> list[str]:
    """La ventana en que nació y, si no dio fotos, la última en que se ha visto.

    La última solo sirve si su «antes», un año atrás, sigue siendo anterior al cambio.
    """
    vs = [a["primera"]] if a.get("analisis_v") != clasificacion.VERSION else []
    if a["ultima"] != a["primera"] and _meses_entre(a["primera"], a["ultima"]) < 12:
        vs.append(a["ultima"])
    return vs


def analizar_pendientes(alertas: list[dict], hoy: date, minutos: float = ANALISIS_MINUTOS) -> int:
    """Fotos y clase para las alertas activas sin analizar o analizadas con reglas viejas.

    Van primero las que no tienen análisis y, dentro de cada grupo, las más grandes.
    """
    t0, hechas = time.monotonic(), 0
    pendientes = [a for a in alertas if _pendiente(a)]
    for a in sorted(pendientes, key=lambda a: ("clase" in a, -a["pixeles"])):
        if time.monotonic() - t0 > minutos * 60:
            con.log(f"[yellow]{len(pendientes) - hechas} alertas sin analizar; siguen mañana")
            break
        hechas += 1
        res = None
        for v in _ventanas_fotos(a):
            try:
                res = clasificacion.analizar(a["id"], _geom_utm(a), v)
            except Exception as e:                  # una escena corrupta no para la vigilancia
                con.log(f"[yellow]{a['id']}: sin análisis en {v} ({e})")
                continue
            res["ventana_fotos"] = v
            if res.get("foto_despues"):
                break
        if res is None:
            a["ventana_fotos"] = a["ultima"]
            continue
        for k in CAMPOS_ANALISIS:
            a.pop(k, None)
        a.update(res)
        a["clase_nombre"] = clasificacion.CLASES[a["clase"]]
    # Sin descargas: vale también para las analizadas antes de existir la regla.
    for a in alertas:
        if a["estado"] in ACTIVAS and "clase" in a and _nivel_del_agua(a):
            a["estado"] = "descartada"
            a["historial"].append({"fecha": hoy.isoformat(), "estado": "descartada",
                                   "motivo": "oscilación del nivel del agua"})
    return hechas


def procesar(mes_fin: str, cambios: list, stats: dict, capas: dict, registros: list[dict],
             hoy: date | None = None, retro: bool = False, analizar: bool = True) -> dict:
    """Actualiza el registro con los cambios de una ventana.

    Al reconstruir el pasado (`analizar=False`) las fotos se dejan para el final: muchas
    alertas se descartan unas ventanas después y analizarlas sería tiempo perdido.
    """
    hoy = hoy or date.today()
    reg = cargar()
    reg["ejecuciones"][mes_fin] = stats
    alertas = reg["alertas"]
    geoms = [_geom_utm(a) for a in alertas]
    tocadas: set[int] = set()
    nuevas = 0

    for c in sorted(cambios, key=lambda c: -c.pixeles):
        idx = [i for i, g in enumerate(geoms) if g.intersects(c.geom)]
        if idx:
            # Un cambio puede tocar varias alertas: todas se dan por vistas en esta ventana,
            # y solo la primera crece si el cambio es mayor.
            tocadas.update(idx)
            for i in idx:
                a = alertas[i]
                if mes_fin not in a["meses"]:
                    a["meses"] = sorted(set(a["meses"]) | {mes_fin})
                a["ultima"] = max(a["meses"])
                if a["estado"] in ("provisional", "descartada", "revertida") and len(a["meses"]) >= 2 \
                        and a["ultima"] > a["primera"] and not _nivel_del_agua(a):
                    a["historial"].append({"fecha": hoy.isoformat(), "estado": "confirmada"})
                    a["estado"] = "confirmada"
                a["ndvi_actual"] = c.ndvi_actual
            i, a = idx[0], alertas[idx[0]]
            if c.pixeles > a["pixeles"]:
                g = unary_union([geoms[i], make_valid(c.geom)])
                geoms[i] = g
                a.update(geometry=_geojson(g), pixeles=c.pixeles, ha=c.ha)
            continue
        aid = _nuevo_id(reg, mes_fin)
        cen = zona.a_geo(c.geom.representative_point())
        alertas.append({
            "id": aid, "estado": "provisional", "primera": mes_fin, "ultima": mes_fin,
            "meses": [mes_fin], "detectada": hoy.isoformat(),
            "historial": [{"fecha": hoy.isoformat(), "estado": "provisional"}],
            "pixeles": c.pixeles, "ha": c.ha, "ndvi_ref": c.ndvi_ref, "ndvi_actual": c.ndvi_actual,
            "obs_actual": c.obs_actual, "centro": [round(cen.y, 5), round(cen.x, 5)],
            "geometry": _geojson(c.geom), "espacios": zona.espacios_de(c.geom),
            "municipios": zona.municipios_de(c.geom),
            "ultima_vegetacion": ultima_vegetacion(c.geom, deteccion.meses_ventana(mes_fin)[0]),
            # Encontrada al reconstruir ventanas pasadas, no vista en su día.
            "reconstruida": retro,
        })
        geoms.append(c.geom)
        tocadas.add(len(alertas) - 1)
        nuevas += 1

    # Alertas activas que esta ventana no ha vuelto a ver: ¿ha vuelto la vegetación?
    for i, a in enumerate(alertas):
        if i in tocadas or a["estado"] not in ACTIVAS or a["ultima"] >= mes_fin:
            continue
        ndvi, n = deteccion.ndvi_actual_en(geoms[i], capas)
        if ndvi is not None and ndvi >= NDVI_RECUPERADA:
            nuevo = "descartada" if a["estado"] == "provisional" else "revertida"
            a["estado"] = nuevo
            a["ndvi_actual"] = ndvi
            a["historial"].append({"fecha": hoy.isoformat(), "estado": nuevo, "ventana": mes_fin,
                                   "motivo": "volvió la vegetación"})
        elif a["estado"] == "provisional" and _meses_entre(a["ultima"], mes_fin) >= config.VENTANA_MESES:
            # Ni se ha vuelto a ver ni se ha recuperado del todo, y la ventana actual ya no
            # comparte ningún mes con la suya: no se puede confirmar.
            a["estado"] = "descartada"
            a["historial"].append({"fecha": hoy.isoformat(), "estado": "descartada", "ventana": mes_fin,
                                   "motivo": "no se volvió a ver"})

    if analizar:
        analizar_pendientes(alertas, hoy)

    for a in alertas:
        cr = expedientes.cruzar(a["municipios"], registros)
        a["cruce"] = cr["estado"]
        a["expedientes"] = cr["expedientes"]

    reg["expedientes_desde"] = expedientes.cobertura(registros)
    reg["ultima_ventana"] = max(reg["ejecuciones"])
    guardar(reg)
    con.log(f"{mes_fin}: {len(cambios)} cambios, {nuevas} alertas nuevas, {len(alertas)} en total")
    return reg
