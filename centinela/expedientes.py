"""Cruce de cada cambio con los expedientes que ha leído el observatorio de alegaciones.

El cruce es por parcela catastral. De cada anuncio o resolución de Cantabria se sacan las
parcelas que cita: referencias catastrales y pares «polígono X, parcela Y» del municipio
del expediente. Una alerta tiene expediente si alguno cita una de las parcelas que toca.

«Sin expediente conocido» quiere decir que ningún anuncio ni resolución leído por el
observatorio cita sus parcelas. No significa que la obra carezca de permiso: muchas
licencias municipales y autorizaciones forestales no se publican, y algunos anuncios
solo dan el municipio. Esos se cuentan aparte, como contexto.
"""
from __future__ import annotations

import json
import re
import unicodedata

import requests

from . import catastro, config

BASE = "https://raw.githubusercontent.com/Asensio94/observatorio-alegaciones/main/data/"
FICHEROS = ("estado.json", "estado_litoral.json")
OBSERVATORIO_WEB = "https://asensio94.github.io/observatorio-alegaciones/"
# Sentidos de resolución que habilitan la actuación, tal y como los etiqueta el observatorio.
HABILITANTES = {"favorable", "condicionada", "parcial", "sin_eia"}
# Parcelas citadas por cada expediente. Se versiona: los textos no cambian y así no hay que
# volver a pedirlos. Si cambian las reglas de extracción, sube HUELLA_V.
HUELLAS_JSON = config.DATA_DIR / "expedientes_parcelas.json"
HUELLA_V = 1

# Referencia de 14 caracteres, sola o con los 6 de control (20). Rústica: provincia y
# municipio, sector, polígono y parcela. Urbana: manzana y hoja, con letras y cifras.
_REF = re.compile(r"(?<![0-9A-Z])(\d{5}[A-Z]\d{8}|\d{7}[0-9A-Z]{7})(?:\d{4}[A-Z]{2})?(?![0-9A-Z])")
# Rústica con la letra de sector estropeada en el boletín (se ha visto un carácter raro en
# su lugar): municipio, un carácter cualquiera, polígono y parcela.
_RUST = re.compile(r"(?<![0-9A-Z])(39\d{3})[^\s\d]?(\d{3})(\d{5})(?:\d{4}[A-Z]{2})?(?![0-9A-Z])")
_N = r"(?:n\.?\s*[ºo°]\.?\s*)?"
_LISTA = r"(\d{1,5}(?:\s*(?:,|y|e)\s*\d{1,5})*)"
_POL_PAR = re.compile(rf"pol(?:[íi]gono|\.)\s*{_N}(\d{{1,3}})\W{{0,6}}(?:y\s+)?parc(?:elas?|\.)\s*{_N}{_LISTA}", re.I)
_PAR_POL = re.compile(rf"parc(?:elas?|\.)\s*{_N}{_LISTA}\s*,?\s*del?\s+pol(?:[íi]gono|\.)\s*{_N}(\d{{1,3}})", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return " ".join(s.replace("-", " ").split())


def cargar() -> list[dict]:
    """Registros de Cantabria del observatorio, con copia local por si GitHub no responde."""
    registros: dict[str, dict] = {}
    for nombre in FICHEROS:
        cache = config.CACHE_DIR / nombre
        try:
            r = requests.get(BASE + nombre, timeout=60)
            r.raise_for_status()
            datos = r.json()
            cache.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        except (requests.RequestException, ValueError):
            if not cache.exists():
                continue
            datos = json.loads(cache.read_text(encoding="utf-8"))
        for grupo in ("anuncios", "resoluciones"):
            for k, a in (datos.get(grupo) or {}).items():
                if config.REGION not in (a.get("provincias") or []):
                    continue
                registros[k] = {
                    "id": k, "grupo": grupo, "fecha": a.get("fecha"), "titulo": a.get("titulo"),
                    "url": a.get("url_html"), "url_xml": a.get("url_xml"),
                    "fuente": a.get("fuente") or "BOE",
                    "municipios": a.get("municipios") or [], "sentido": a.get("sentido", ""),
                    "sentido_etiqueta": a.get("sentido_etiqueta", ""),
                    "categoria": a.get("categoria", ""),
                }
    return sorted(registros.values(), key=lambda r: r["fecha"] or "", reverse=True)


def cobertura(registros: list[dict]) -> str | None:
    fechas = [r["fecha"] for r in registros if r["fecha"]]
    return min(fechas) if fechas else None


# ── Parcelas citadas en cada expediente ──────────────────────────────────────────────────

def extraer(texto: str) -> dict:
    """Referencias catastrales y pares polígono-parcela que cita un texto."""
    t = unicodedata.normalize("NFKC", texto or "")
    refs = sorted({m.group(1) for m in _REF.finditer(t)})
    rust = sorted({(m.group(1), int(m.group(2)), int(m.group(3))) for m in _RUST.finditer(t)})
    pp = set()
    for m in _POL_PAR.finditer(t):
        pp |= {(int(m.group(1)), int(x)) for x in re.findall(r"\d+", m.group(2))}
    for m in _PAR_POL.finditer(t):
        pp |= {(int(m.group(2)), int(x)) for x in re.findall(r"\d+", m.group(1))}
    return {"refs": refs, "rusticas": [list(x) for x in rust], "polparc": sorted(map(list, pp))}


def _texto(r: dict, boc_dias: dict) -> str | None:
    """Texto completo: el volcado diario del BOC que guarda el observatorio, o el XML del BOE."""
    if r["id"].startswith("BOC") and r.get("fecha"):
        dia = r["fecha"].replace("-", "")
        if dia not in boc_dias:
            try:
                q = requests.get(f"{BASE}fuentes/boc_cantabria/{dia}.json", timeout=60)
                boc_dias[dia] = {a["identificador"]: a.get("texto") or "" for a in (q.json() or [])} if q.ok else {}
            except (requests.RequestException, ValueError):
                boc_dias[dia] = None           # sin red: se reintenta en la próxima ejecución
        t = (boc_dias[dia] or {}).get(r["id"])
        if t:
            return t
    if r.get("url_xml") and "boe.es" in r["url_xml"]:
        try:
            q = requests.get(r["url_xml"], timeout=60)
            q.raise_for_status()
            return re.sub(r"<[^>]+>", " ", q.text)
        except requests.RequestException:
            return None
    return None


def huellas(registros: list[dict]) -> dict:
    """Parcelas citadas por cada registro. Solo se piden los textos que faltan."""
    hs = json.loads(HUELLAS_JSON.read_text(encoding="utf-8")) if HUELLAS_JSON.exists() else {}
    boc_dias: dict = {}
    nuevas = 0
    for r in registros:
        if hs.get(r["id"], {}).get("v") == HUELLA_V:
            continue
        t = _texto(r, boc_dias)
        if t is None:
            continue
        hs[r["id"]] = {"v": HUELLA_V, **extraer(t)}
        nuevas += 1
    if nuevas:
        HUELLAS_JSON.write_text(json.dumps(hs, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    return hs


# ── Cruce ────────────────────────────────────────────────────────────────────────────────

def _coincide(p: dict, r: dict, h: dict) -> bool:
    if p["refcat"] in h["refs"]:
        return True
    if p.get("tipo") != "rustica":
        return False
    if [p["municipio"], p["poligono"], p["parcela"]] in h["rusticas"]:
        return True
    # «Polígono 4, parcela 18» sin referencia: vale si el expediente es de ese municipio.
    nombre = catastro.norm_municipio(p.get("municipio_nombre") or catastro.nombre_municipio(p["municipio"]) or "")
    return ([p["poligono"], p["parcela"]] in h["polparc"]
            and nombre in {catastro.norm_municipio(m) for m in r["municipios"]})


def cruzar(alerta: dict, registros: list[dict], hs: dict) -> dict:
    if "parcelas" not in alerta:
        return {"estado": "pendiente", "expedientes": [], "en_municipio": 0}
    hits = []
    for r in registros:
        h = hs.get(r["id"])
        if not h:
            continue
        coinc = [p["refcat"] for p in alerta["parcelas"] if _coincide(p, r, h)]
        if coinc:
            hits.append((r, coinc))
    habil = [r for r, _ in hits if r["grupo"] == "resoluciones" and r["sentido"] in HABILITANTES]
    estado = "resolucion" if habil else "tramitacion" if hits else "sin_expediente"
    # Contexto: expedientes del mismo municipio que no identifican ninguna parcela.
    objetivo = {_norm(m) for m in alerta["municipios"]}
    en_mun = [r for r in registros if objetivo & {_norm(m) for m in r["municipios"]}
              and not any(hs.get(r["id"], {}).get(k) for k in ("refs", "rusticas", "polparc"))]
    return {"estado": estado, "en_municipio": len(en_mun), "expedientes": [
        {**{k: r[k] for k in ("id", "fecha", "titulo", "url", "fuente", "grupo", "sentido_etiqueta")},
         "parcelas": coinc} for r, coinc in hits[:8]]}


ESTADOS = {
    "resolucion": "Resolución favorable en la parcela",
    "tramitacion": "Expediente en tramitación en la parcela",
    "sin_expediente": "Sin expediente conocido",
    "pendiente": "Parcelas por consultar",
}
