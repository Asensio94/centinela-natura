"""Cruce de cada cambio francés con las autorizaciones de urbanismo de Sitadel.

Sitadel es el registro estadístico del ministerio (SDES) de las autorizaciones de
urbanismo: permis de construire, déclarations préalables, permis d'aménager y permis de
démolir. Cada una trae hasta tres parcelas catastrales (sección y número, casi nunca el
prefijo), la fecha de autorización y en qué punto está la obra. Es el equivalente francés
de los expedientes españoles: el cruce es por parcela, igual que allí.

Lo que Sitadel no tiene: las solicitudes denegadas o abandonadas (solo entran las
autorizadas), más de tres parcelas por autorización, y todo lo que no es urbanismo
(desbroces forestales, evaluaciones de incidencias Natura 2000, planes de gestión
forestal). «Sans autorisation connue» quiere decir eso: ninguna autorización de
urbanismo de Sitadel cita sus parcelas.

Del fichero solo se guarda el número de autorización, su tipo, fecha, estado, destino y
parcelas. Nunca el solicitante: ni su nombre o razón social (DENOM_DEM), ni su SIREN o
SIRET, ni su dirección o localidad.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import date, timedelta

import requests
import shapely
from rich.console import Console

from . import config, zona

con = Console()

API = "https://data.statistiques.developpement-durable.gouv.fr/dido/api/v1/datafiles/{rid}"
WEB = "https://www.statistiques.developpement-durable.gouv.fr/donnees-des-permis-de-construire-et-autres-autorisations-durbanisme"
OBSERVATORIO_WEB = WEB
# Un fichero por clase de autorización. Las de construcción vienen partidas por destino
# (vivienda o local) y cada fila dice si es permis de construire (PC) o déclaration
# préalable (DP); las de urbanizar (PA) y demoler (PD) van solas.
FICHEROS = {
    "PA": ("96883f50-538b-41f9-a059-c6eb97e6a23a", "NUM_PA", "ETAT_PA"),
    "PD": ("1a9a2f0c-56fe-4e69-84a7-fbbda2121f02", "NUM_PD", "ETAT_PD"),
    "locaux": ("f8f0700f-806c-40a7-83b1-f21cf507e7c4", "NUM_DAU", "ETAT_DAU"),
    "logements": ("8b35affb-55fc-4c1f-915b-7750f974446a", "NUM_DAU", "ETAT_DAU"),
}
# Columnas que se leen. Todo lo demás, y en particular las del solicitante, se descarta.
_SECCIONES = [(f"SEC_CADASTRE{i}", f"NUM_CADASTRE{i}") for i in (1, 2, 3)]
# ETAT: 2 autorizada, 4 anulada, 5 obra empezada, 6 obra terminada.
ANULADA = "4"
# Desde cuándo se guardan: una autorización puede tener tres años de validez antes de
# empezar la obra, y las alertas más antiguas son de 2023.
DESDE = "2018-01-01"
# Antes de la ventana del cambio, una autorización cuenta si es de estos meses atrás.
MESES_ANTES = 36
# Communes que se guardan: las que tocan la Red Natura o quedan a menos de esto.
MARGEN_M = 1000
# Sitadel se publica cada mes; más allá de esto se vuelve a bajar.
DIAS_VIGENCIA = 30

ESTADOS = {
    "resolucion": "Autorización de urbanismo en la parcela",
    "sin_expediente": "Sin autorización conocida",
    "pendiente": "Parcelas por consultar",
}


def ruta():
    return config.DATA_DIR / "sitadel_parcelles.json"


def _get(url: str, **kw) -> requests.Response:
    for intento in range(4):
        try:
            r = requests.get(url, timeout=300, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException:
            if intento == 3:
                raise
            time.sleep(10 * (intento + 1))


def parcela(seccion: str, numero: str) -> str | None:
    """Sección sin ceros de relleno y número de cuatro cifras: AB0042, A0151.

    Sitadel escribe a veces el número con una letra detrás («151P», parcela en parte).
    """
    s = (seccion or "").strip().upper().lstrip("0")
    n = re.sub(r"\D", "", numero or "")
    if not s or not n or int(n) == 0:
        return None
    return f"{s}{int(n):04d}"


def numero_oficial(tipo: str, num: str) -> str:
    """06400117P0001 → PC 064 001 17 P0001, como se ve en el cartel de obra."""
    if len(num) >= 13:
        return f"{tipo} {num[:3]} {num[3:6]} {num[6:8]} {num[8:]}"
    return f"{tipo} {num}"


def communes_vigiladas() -> set[str]:
    cerca = zona.union().buffer(MARGEN_M)
    return {m["insee"] for m in zona.municipios() if m["geom"].intersects(cerca)}


def descargar() -> dict:
    """Baja los cuatro ficheros del departamento y guarda solo lo que hace falta."""
    dep = config.PAISES["FR"]["departamento"]
    vigiladas = communes_vigiladas()
    communes: dict[str, list] = {}
    millesimes = {}
    for clase, (rid, col_num, col_etat) in FICHEROS.items():
        millesimes[clase] = _get(API.format(rid=rid)).json().get("millesime")
        texto = _get(API.format(rid=rid) + "/csv", params={"DEP_CODE": f"eq:{dep}"}).content.decode("utf-8-sig")
        for f in csv.DictReader(io.StringIO(texto), delimiter=";"):
            insee, fecha = f["COMM"].strip(), (f["DATE_REELLE_AUTORISATION"] or "").strip()
            if insee not in vigiladas or not fecha or fecha < DESDE:
                continue
            parcelas = sorted({p for s, n in _SECCIONES if (p := parcela(f.get(s), f.get(n)))})
            if not parcelas:
                continue
            tipo = f.get("TYPE_DAU") or clase
            communes.setdefault(insee, []).append(
                [numero_oficial(tipo, f[col_num].strip()), tipo, fecha, f[col_etat].strip(),
                 f.get("DESTINATION_PRINCIPALE") or ("1" if clase == "logements" else ""), parcelas])
    for v in communes.values():
        v.sort(key=lambda x: (x[2], x[0]))
    datos = {"fuente": WEB, "descargado": date.today().isoformat(), "millesimes": millesimes,
             "desde": DESDE, "campos": ["numero", "tipo", "fecha", "etat", "destination", "parcelles"],
             "communes": dict(sorted(communes.items()))}
    ruta().write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    con.log(f"sitadel: {sum(map(len, communes.values()))} autorizaciones en {len(communes)} communes")
    return datos


def cargar() -> list[dict]:
    """Autorizaciones guardadas; se renuevan si la copia tiene más de un mes."""
    datos = json.loads(ruta().read_text(encoding="utf-8")) if ruta().exists() else None
    if not datos or date.fromisoformat(datos["descargado"]) < date.today() - timedelta(days=DIAS_VIGENCIA):
        try:
            datos = descargar()
        except requests.RequestException as e:      # sin Sitadel, se cruza con la copia
            con.log(f"[yellow]sitadel: no se pudo renovar ({e})")
            if not datos:
                return []
    return [{"commune": insee, "numero": n, "tipo": t, "fecha": fe, "etat": et, "destination": d,
             "parcelles": ps}
            for insee, filas in datos["communes"].items() for n, t, fe, et, d, ps in filas]


def cobertura(registros: list[dict]) -> str | None:
    fechas = [r["fecha"] for r in registros]
    return min(fechas) if fechas else None


def huellas(registros: list[dict]) -> dict:
    """Índice (commune, parcela) → autorizaciones que la citan."""
    idx: dict[tuple, list[dict]] = {}
    for r in registros:
        for p in r["parcelles"]:
            idx.setdefault((r["commune"], p), []).append(r)
    return idx


def _desde(alerta: dict) -> str:
    a, m = map(int, alerta["primera"].split("-"))
    m -= MESES_ANTES
    a, m = a + (m - 1) // 12, (m - 1) % 12 + 1
    return f"{a:04d}-{m:02d}-01"


def cruzar(alerta: dict, registros: list[dict], hs: dict) -> dict:
    if "parcelas" not in alerta:
        return {"estado": "pendiente", "expedientes": [], "en_municipio": 0}
    desde = _desde(alerta)
    hits: dict[str, dict] = {}
    for p in alerta["parcelas"]:
        clave = parcela(p.get("section"), str(p.get("numero")))
        for r in hs.get((p["municipio"], clave), []):
            if r["fecha"] < desde:
                continue
            h = hits.setdefault(r["numero"], {"r": r, "parcelas": []})
            h["parcelas"].append(p["refcat"])
    vivas = [h for h in hits.values() if h["r"]["etat"] != ANULADA]
    estado = "resolucion" if vivas else "sin_expediente"
    # Contexto: cuántas autorizaciones del periodo hay en las communes de la alerta.
    comms = {p["municipio"] for p in alerta["parcelas"]}
    en_mun = sum(1 for r in registros if r["commune"] in comms and r["fecha"] >= desde)
    orden = sorted(hits.values(), key=lambda h: (h["r"]["etat"] == ANULADA, h["r"]["fecha"]), reverse=False)
    return {"estado": estado, "en_municipio": en_mun, "expedientes": [
        {"id": h["r"]["numero"], "fecha": h["r"]["fecha"], "titulo": h["r"]["numero"], "url": WEB,
         "fuente": "Sitadel", "grupo": "resoluciones", "tipo": h["r"]["tipo"], "etat": h["r"]["etat"],
         "destination": h["r"]["destination"], "parcelas": h["parcelas"]} for h in orden[:8]]}
