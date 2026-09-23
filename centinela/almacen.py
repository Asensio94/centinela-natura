"""Los compuestos se guardan como ficheros de una release de GitHub, no en el repositorio.

Cada mes ocupa unas decenas de megas y se reescribe a diario mientras está en curso. En el
historial de git eso se acumularía sin remedio; en una release se sustituye el fichero y
ya está. Se usa la CLI `gh`, que en Actions ya viene instalada y autenticada.
"""
from __future__ import annotations

import json
import os
import subprocess

from . import compuestos, config

REPO = os.environ.get("GITHUB_REPOSITORY", "Asensio94/centinela-natura")


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args, "-R", REPO], capture_output=True, text=True, check=check)


def disponibles() -> set[str]:
    r = _gh("release", "view", config.RELEASE_TAG, "--json", "assets", check=False)
    if r.returncode != 0:
        return set()
    return {a["name"] for a in json.loads(r.stdout)["assets"]}


def asegurar_release() -> None:
    if _gh("release", "view", config.RELEASE_TAG, check=False).returncode != 0:
        _gh("release", "create", config.RELEASE_TAG, "--title", "Compuestos mensuales de NDVI",
            "--notes", "NDVI máximo mensual sobre la Red Natura 2000 de Cantabria (malla de 10 m, "
            "config.CRS). Banda 1: NDVI = valor/100 - 1, 255 sin dato. Banda 2: observaciones "
            "válidas. Se regeneran solos; ver el README.", "--latest=false")


def subir(mes: str) -> None:
    asegurar_release()
    _gh("release", "upload", config.RELEASE_TAG, str(compuestos.ruta(mes)), "--clobber")


def bajar(meses: list[str]) -> list[str]:
    """Trae los compuestos que falten en local. Devuelve los que no existen en la release."""
    hay = disponibles()
    faltan = []
    for mes in meses:
        p = compuestos.ruta(mes)
        if p.name not in hay:
            if not p.exists():
                faltan.append(mes)
            continue
        if not p.exists():
            _gh("release", "download", config.RELEASE_TAG, "-p", p.name, "-D", str(p.parent), "--clobber")
    return faltan
