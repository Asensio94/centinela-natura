"""Búsqueda de escenas Sentinel-2 L2A en Earth Search (AWS, sin autenticación)."""
from __future__ import annotations

import calendar
from datetime import date

from pystac import Item
from pystac_client import Client

from . import config, zona

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client.open(config.STAC_URL)
    return _client


def buscar(bbox_geo: tuple[float, float, float, float], inicio: date, fin: date,
           nubosidad_max: float = config.NUBOSIDAD_ESCENA_MAX) -> list[Item]:
    s = client().search(
        collections=[config.STAC_COLLECTION], bbox=list(bbox_geo),
        datetime=f"{inicio.isoformat()}T00:00:00Z/{fin.isoformat()}T23:59:59Z",
        query={"eo:cloud_cover": {"lt": nubosidad_max}}, max_items=None)
    # Earth Search publica a veces el mismo producto dos veces (reprocesados); se queda
    # la versión más reciente de cada granulo y fecha.
    mejores: dict[tuple, Item] = {}
    for it in s.items():
        clave = (it.properties.get("grid:code"), it.datetime.date(), it.properties.get("platform"))
        prev = mejores.get(clave)
        if prev is None or str(it.properties.get("s2:processing_baseline")) > str(prev.properties.get("s2:processing_baseline")):
            mejores[clave] = it
    return sorted(mejores.values(), key=lambda i: i.datetime)


def rango_mes(mes: str) -> tuple[date, date]:
    y, m = map(int, mes.split("-"))
    return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])


def escenas_mes(mes: str) -> list[Item]:
    ini, fin = rango_mes(mes)
    return buscar(zona.a_geo(zona.union()).bounds, ini, fin)


def offset_aplicado(item: Item) -> bool:
    """True si los niveles digitales del COG ya no llevan el desplazamiento de -1000.

    Desde la baseline 04.00 (enero de 2022) los L2A de ESA suman 1000 a cada nivel
    digital. Earth Search lo resta al generar sus COG y lo marca con esta propiedad. Si
    un producto lo lleva todavía, el NDVI calculado sobre los niveles digitales sale
    sesgado hacia cero. Por eso se corrige antes de calcular nada.
    """
    baseline = str(item.properties.get("s2:processing_baseline", "00.00"))
    return baseline < "04.00" or bool(item.properties.get("earthsearch:boa_offset_applied", False))


def desplazamiento_nd(item: Item) -> int:
    """Niveles digitales que hay que restar a las bandas de reflectancia de una escena.

    Cero si Earth Search ya lo restó. Si no (pasa, por ejemplo, con las escenas de
    Sentinel-2C de su puesta en marcha, de diciembre de 2024 a marzo de 2025), se toma del
    offset que declara el propio activo: -0,1 con escala 1e-4 son 1000 niveles.
    """
    if offset_aplicado(item):
        return 0
    try:
        b = item.assets["red"].extra_fields["raster:bands"][0]
        return int(round(-b["offset"] / b["scale"]))
    except (KeyError, IndexError, TypeError, ZeroDivisionError):
        return 1000
