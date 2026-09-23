"""Órdenes del centinela. `diario` es la que corre cada día en GitHub Actions."""
from __future__ import annotations

import json
from datetime import date, timedelta

import typer
from rich.console import Console

from . import config

app = typer.Typer(add_completion=False, no_args_is_help=True)
con = Console()


def _meses(desde: str, hasta: str) -> list[str]:
    y, m = map(int, desde.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= hasta:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def _mes(d: date) -> str:
    return d.strftime("%Y-%m")


@app.command()
def zona():
    """Descarga los límites de la Red Natura, la región y los municipios."""
    from . import zona as z
    con.print(z.descargar())


@app.command()
def compuesto(meses: list[str], subir: bool = False):
    """Construye (y opcionalmente sube) el compuesto de uno o varios meses AAAA-MM."""
    from . import almacen, compuestos
    for mes in meses:
        meta = compuestos.construir(mes)
        con.print({k: v for k, v in meta.items() if k != "fechas"})
        if subir:
            almacen.subir(mes)


@app.command()
def matriz(desde: str, hasta: str, solo_faltan: bool = True):
    """Imprime la lista de meses en JSON para la matriz de Actions."""
    from . import almacen
    meses = _meses(desde, hasta)
    if solo_faltan:
        hay = almacen.disponibles()
        meses = [m for m in meses if f"ndvi_{m}.tif" not in hay]
    print(json.dumps(meses))


@app.command()
def release():
    """Crea la release donde se guardan los compuestos, si no existe."""
    from . import almacen
    almacen.asegurar_release()


def _detectar(mes_fin: str, registros=None, retro: bool = False):
    """Una ventana. Reconstruyendo el pasado (`retro`) las fotos se dejan para el final."""
    from . import alertas, almacen, deteccion, expedientes, stac
    faltan = almacen.bajar(deteccion.meses_necesarios(mes_fin))
    if faltan:
        con.print(f"[yellow]{mes_fin}: faltan compuestos {faltan}; no se detecta")
        return None
    almacen.bajar(deteccion.meses_agua(mes_fin))   # los que no haya se saltan
    cambios, stats, capas = deteccion.detectar(mes_fin)
    con.print(stats)
    # Fecha a la que se habría visto el cambio: hoy, o el último día de la ventana si se
    # está reconstruyendo el pasado.
    hoy = min(date.today(), stac.rango_mes(mes_fin)[1])
    return alertas.procesar(mes_fin, cambios, stats, capas,
                            registros if registros is not None else expedientes.cargar(),
                            hoy=hoy, retro=retro, analizar=not retro)


@app.command()
def detectar(meses_fin: list[str], retro: bool = False):
    """Detecta cambios en las ventanas que acaban en esos meses, en orden."""
    from . import expedientes
    reg = expedientes.cargar()
    for mes in sorted(meses_fin):
        _detectar(mes, reg, retro)


@app.command()
def historico(desde: str, hasta: str):
    """Recorre mes a mes un periodo, como si el centinela hubiera estado vigilando."""
    detectar(_meses(desde, hasta), retro=True)


@app.command()
def diario(subir: bool = True, hoy: str = ""):
    """Rehace el mes en curso (y el anterior los primeros días), detecta y publica."""
    from . import almacen, compuestos, web
    d = date.fromisoformat(hoy) if hoy else date.today()
    actual = _mes(d)
    anterior = _mes(d.replace(day=1) - timedelta(days=1))
    # Earth Search publica algunas escenas con días de retraso: el mes anterior se rehace
    # una última vez durante los primeros días del siguiente.
    rehacer = [anterior, actual] if d.day <= config.DIAS_CIERRE_MES else [actual]
    for mes in rehacer:
        compuestos.construir(mes)
        if subir:
            almacen.subir(mes)
    detectar(rehacer)
    web.construir()


@app.command()
def publicar():
    """Genera la web en site/ a partir de data/alertas.json."""
    from . import web
    web.construir()


if __name__ == "__main__":
    app()
