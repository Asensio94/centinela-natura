"""La web pública: mapa, fichas de alerta, fuente Atom y metodología generada desde config.

Una página por país, en su idioma: Cantabria en site/, en castellano; los Pirineos
Atlánticos en site/fr/, en francés. La plantilla es la misma y los textos salen de
i18n.py. Los ficheros de datos que se publican al lado (alertas.geojson, signals.json)
llevan claves y nombres canónicos, no dependen del idioma de la página.
"""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import mapping, shape

from . import alertas as al
from . import cadastre, catastro, clasificacion, config, i18n, signals, sitadel, zona
from .logo import LOGO_SVG, favicon_link

REPO_URL = "https://github.com/Asensio94/centinela-natura"
WEB_URL = "https://asensio94.github.io/centinela-natura/"
# Shared stylesheet of the sibling projects, copied verbatim; it is inlined first in <style>.
COMMON_CSS = (Path(__file__).with_name("common.css")).read_text(encoding="utf-8")
# Encuadre inicial del mapa, antes de ajustarse a los espacios.
VISTA = {"ES": [43.2, -4.05], "FR": [43.2, -0.8]}
ORTO = {
    "ES": {"url": "https://www.ign.es/wmts/pnoa-ma?layer=OI.OrthoimageCoverage&style=default&tilematrixset=GoogleMapsCompatible&Service=WMTS&Request=GetTile&Version=1.0.0&Format=image/jpeg&TileMatrix={z}&TileCol={x}&TileRow={y}",
           "maxZoom": 20, "nombre": "Ortofoto PNOA",
           "atribucion": 'Ortofoto PNOA <a href="https://www.scne.es/">CC BY 4.0 scne.es</a>'},
    "FR": {"url": "https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=image/jpeg",
           "maxZoom": 19, "nombre": "Orthophotos IGN",
           "atribucion": 'Orthophotos <a href="https://geoservices.ign.fr/">IGN</a>, Licence Ouverte 2.0'},
}
# Enlace entre las páginas de los dos países, con el nombre en el idioma de cada página.
PAISES_NAV = {
    "es": ("Países", {"ES": "España (Cantabria)", "FR": "Francia (Pirineos Atlánticos)"}),
    "fr": ("Pays", {"ES": "Espagne (Cantabrie)", "FR": "France (Pyrénées-Atlantiques)"}),
}
# Nombres canónicos de los estados, los que van en los datos.
ESTADOS = i18n.ES["estados"]


def _lang() -> str:
    return i18n.lang_of(config.PAIS)


def _t() -> dict:
    return i18n.UI[_lang()]


def web_url() -> str:
    sub = config.PAISES[config.PAIS]["subdir"]
    return WEB_URL + (f"{sub}/" if sub else "")


def _clases() -> dict:
    return i18n.CLASES.get(_lang(), clasificacion.CLASES)


def _cruces() -> dict:
    return i18n.CRUCES[_lang()]


def _mes_largo(mes: str | None) -> str:
    if not mes:
        return "—"
    y, m = map(int, mes.split("-"))
    return f"{i18n.MESES[_lang()][m - 1]}{_t()['js']['de']}{y}"


def _ventana_txt(meses: list[str]) -> str:
    """«julio–septiembre de 2026», o con los dos años si la ventana cruza el cambio de año."""
    if not meses:
        return "—"
    M, de = i18n.MESES[_lang()], _t()["js"]["de"]
    (y0, m0), (y1, m1) = (map(int, meses[0].split("-")), map(int, meses[-1].split("-")))
    if y0 == y1:
        return f"{M[m0 - 1]}–{M[m1 - 1]}{de}{y1}"
    return f"{M[m0 - 1]}{de}{y0}–{M[m1 - 1]}{de}{y1}"


def _fecha_txt(f: str) -> str:
    y, m, d = map(int, f.split("-"))
    de = _t()["js"]["de"]
    return f"{d}{de}{i18n.MESES[_lang()][m - 1]}{de}{y}"


def _num(x: float, dec: int = 1) -> str:
    return i18n.num(x, _lang(), dec)


def _espacios_web() -> dict:
    """Límites simplificados para pintar en el mapa (el original pesa 2,6 MB)."""
    fc = json.loads(zona.espacios_geojson().read_text(encoding="utf-8"))
    feats = []
    for f in fc["features"]:
        if f["properties"]["ha"] < 5:           # astillas de borde con la comunidad vecina
            continue
        g = shape(f["geometry"]).simplify(0.00025, preserve_topology=True)
        gj = json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), 5))
        feats.append({"type": "Feature", "geometry": gj, "properties": f["properties"]})
    return {"type": "FeatureCollection", "features": feats}


def _geojson_alertas(reg: dict) -> dict:
    feats = []
    for a in reg["alertas"]:
        p = {k: v for k, v in a.items() if k != "geometry"}
        p["estado_nombre"] = ESTADOS[a["estado"]]
        p["cruce_nombre"] = al.permisos().ESTADOS.get(a.get("cruce", ""), "")
        if config.PAIS == "FR":                  # código INSEE de cada commune, en su orden
            p["municipios_insee"] = zona.codigos_de(a["municipios"])
        feats.append({"type": "Feature", "geometry": a["geometry"], "properties": p})
    return {"type": "FeatureCollection", "features": feats}


def _ligera(gj: dict) -> dict:
    """La copia que va dentro de la página: polígonos simplificados a un píxel (unos 9 m).

    El alertas.geojson descargable conserva los polígonos enteros, con sus escalones de
    píxel; en el mapa no se distinguen y multiplican el peso de la página.
    """
    feats = []
    for f in gj["features"]:
        g = shape(f["geometry"]).simplify(0.00009, preserve_topology=True)
        geo = json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), 5))
        feats.append({**f, "geometry": geo})
    return {**gj, "features": feats}


def _atom(reg: dict, ahora: str) -> str:
    t, url = _t(), web_url()
    activas = [a for a in reg["alertas"] if a["estado"] in al.ACTIVAS]
    activas.sort(key=lambda a: a["detectada"], reverse=True)
    entradas = []
    for a in activas[:100]:
        esp = ", ".join(e["nombre"] for e in a["espacios"]) or t["js"]["natura"]
        mun = ", ".join(a["municipios"])
        clase = _clases().get(a.get("clase")) or a.get("clase_nombre")
        titulo = f"{clase or t['cambio']}: {_num(a['ha'], 2)} ha {t['en']} {esp} ({mun})"
        resumen = (f"{t['estados'][a['estado']]}. {_cruces().get(a.get('cruce', ''), '')}. "
                   + t["ndvi_de_a"].format(a=_num(a['ndvi_ref'], 2), b=_num(a['ndvi_actual'], 2)))
        if a.get("parcelas"):
            resumen += t["parcelas_feed"].format(lista=", ".join(p["refcat"] for p in a["parcelas"][:5]))
        actualizado = a["historial"][-1]["fecha"]
        entradas.append(f"""  <entry>
    <id>{url}#{a['id']}</id>
    <title>{html.escape(titulo)}</title>
    <link href="{url}#{a['id']}"/>
    <updated>{actualizado}T00:00:00Z</updated>
    <summary>{html.escape(resumen)}</summary>
  </entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>{html.escape(t['feed_title'].format(region=config.REGION))}</title>
  <id>{url}</id>
  <link href="{url}"/>
  <link rel="self" href="{url}feed.xml"/>
  <updated>{ahora}</updated>
{chr(10).join(entradas)}
</feed>
"""


def _vaciar(site: Path) -> None:
    """Borra la web del país activo sin tocar la de los otros países, que va dentro de la
    de España (site/fr/)."""
    otros = {p["subdir"] for k, p in config.PAISES.items() if k != config.PAIS and p["subdir"]}
    if not site.exists():
        return
    for hijo in site.iterdir():
        if hijo.name in otros:
            continue
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()


def _paises_nav() -> str:
    """Enlaces a la página de cada país; la de España está en la raíz y las demás debajo."""
    etiqueta, nombres = PAISES_NAV[_lang()]
    enlaces = []
    for k, p in config.PAISES.items():
        if k == config.PAIS:
            enlaces.append(f'<a href="./" aria-current="page">{nombres[k]}</a>')
            continue
        sub = config.PAISES[config.PAIS]["subdir"]
        destino = ("../" if sub else "") + (f"{p['subdir']}/" if p["subdir"] else "")
        enlaces.append(f'<a href="{destino}">{nombres[k]}</a>')
    return f'<nav class="paises label" aria-label="{etiqueta}">{" · ".join(enlaces)}</nav>'


def construir() -> None:
    reg = al.cargar()
    site = config.SITE_DIR
    _vaciar(site)
    (site / "chips").mkdir(parents=True)
    for p in config.CHIPS_DIR.glob("*.jpg"):
        shutil.copy2(p, site / "chips" / p.name)
    now = datetime.now(timezone.utc)
    ahora = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    t, lang = _t(), _lang()

    gj = _geojson_alertas(reg)
    (site / "alertas.geojson").write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    (site / "feed.xml").write_text(_atom(reg, ahora), encoding="utf-8")
    esp = _espacios_web()
    (site / "espacios.geojson").write_text(json.dumps(esp, ensure_ascii=False), encoding="utf-8")
    if config.PAIS == "FR" and sitadel.ruta().exists():
        shutil.copy2(sitadel.ruta(), site / sitadel.ruta().name)
    # The current alerts in the sibling projects' common format, for Estado de las IBA. Each
    # country leaves its part in its cache; the published file, at the root of the web,
    # joins the parts of every country.
    doc = signals.document(gj, [f["properties"]["codigo"] for f in esp["features"]], now, web_url())
    (config.CACHE_DIR / "signals.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    partes = {k: json.loads(f.read_text(encoding="utf-8")) for k, f in signals.parts().items()}
    (config.ROOT / "site" / "signals.json").write_text(
        json.dumps(signals.combine(partes, now), ensure_ascii=False), encoding="utf-8")

    acts = [a for a in reg["alertas"] if a["estado"] in al.ACTIVAS]
    ult = reg.get("ultima_ventana")
    ej = reg["ejecuciones"].get(ult, {}) if ult else {}
    # En la página no van las fusionadas: un enlace antiguo a una de ellas lleva a la que
    # la absorbió. El alertas.geojson descargable sí las conserva.
    visibles = {**gj, "features": [f for f in gj["features"] if f["properties"]["estado"] != "fusionada"]}
    datos = {
        "alertas": _ligera(visibles), "espacios": esp,
        "redir": {a["id"]: a["fusionada_en"] for a in reg["alertas"] if a.get("fusionada_en")},
        "clases": _clases(), "estados": t["estados"], "cruces": _cruces(),
        "usos": i18n.USOS.get(lang), "clc": i18n.CLC.get(lang),
        "observatorio": al.permisos().OBSERVATORIO_WEB,
        "sede": cadastre.SEDE if config.PAIS == "FR" else catastro.SEDE,
        "t": t["js"], "meses": i18n.MESES[lang], "meses_cortos": i18n.MESES_CORTOS[lang], "cambio": t["cambio"],
        "vista": VISTA[config.PAIS], "orto": ORTO[config.PAIS],
    }
    fechas_cat = [a["catastro_fecha"] for a in reg["alertas"] if a.get("catastro_fecha")]
    desde = reg.get("expedientes_desde")
    resumen = {
        "activas": len(acts),
        "confirmadas": sum(a["estado"] == "confirmada" for a in acts),
        "con_expediente": sum(a.get("cruce") in ("resolucion", "tramitacion") for a in acts),
        "ha": _num(sum(a["ha"] for a in acts), 1),
        "ventana": _ventana_txt(ej.get("ventana") or []),
        "evaluable": i18n.pct(ej.get("fraccion_evaluable", 0), lang) if ej else "—",
        # En España, la fecha tal cual; en Francia, escrita.
        "expedientes_desde": (_fecha_txt(desde) if lang != "es" else desde) if desde else "—",
        "catastro_fecha": _fecha_txt(max(fechas_cat)) if fechas_cat else "—",
        "actualizado": _fecha_txt((reg.get("actualizado") or ahora)[:10]),
        "zona_ha": _num(zona.mascara().sum() * config.PIXEL_HA, 0),
        "n_espacios": len(esp["features"]),
    }
    textos = {k: t[k] for k in ("html_lang", "description", "feed_alt", "label", "lede", "fig_activas",
                                "fig_confirmadas", "fig_ha", "fig_expediente", "fig_meta", "mapa_aria",
                                "filtros", "metodo", "parametros", "datos", "principio", "creditos")}
    textos["paises"] = _paises_nav()
    textos["siblings"] = i18n.siblings(lang)
    html_txt = PLANTILLA
    for k, v in textos.items():
        html_txt = html_txt.replace(f"__T_{k.upper()}__", v)
    html_txt = (html_txt
                .replace("__LOGO__", LOGO_SVG)
                .replace("__FAVICON__", favicon_link("#2f7a55", "#62b88a"))
                .replace("__COMMON_CSS__", COMMON_CSS)
                .replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__METODO__", _metodo()))
    for k, v in resumen.items():
        html_txt = html_txt.replace(f"__{k.upper()}__", html.escape(str(v)))
    (site / "index.html").write_text(html_txt, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")


def _metodo() -> str:
    c, f = config, _t()["parametros_filas"]
    valores = {
        "satelite": {}, "validos": {}, "compuesto": {},
        "resolucion": {"r": c.RESOLUCION_M},
        "nieve": {"ndsi": _num(c.NIEVE_NDSI_MIN, 1), "nir": _num(c.NIEVE_NIR_MIN, 2), "verde": _num(c.NIEVE_VERDE_MIN, 2)},
        "sombra": {"nir": _num(c.NIR_SENAL_MIN, 2)},
        "orillas": {"meses": c.AGUA_MESES_ATRAS},
        "ventana": {"v": c.VENTANA_MESES, "a": c.ANIOS_REFERENCIA},
        "referencia": {"x": _num(c.NDVI_REF_MIN, 2)},
        "cambio": {"x": _num(c.NDVI_ACTUAL_MAX, 2), "c": _num(c.CAIDA_MIN, 2)},
        "obs": {"n": c.OBS_MIN},
        "uma": {"n": c.UMA_PIXELES, "ha": _num(c.UMA_PIXELES * c.PIXEL_HA, 1)},
        "vuelta": {"x": _num(al.NDVI_RECUPERADA, 2)},
        "rpg": {}, "sitadel": {"meses": sitadel.MESES_ANTES},
    }
    filas = [(a, b.format(**valores[k])) for k, (a, b) in f.items()]
    tabla = "\n".join(f"<tr><th scope=\"row\">{html.escape(a)}</th><td>{html.escape(b)}</td></tr>"
                      for a, b in filas)
    return f'<table class="params">{tabla}</table>'


PLANTILLA = r"""<!doctype html>
<html lang="__T_HTML_LANG__">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Centinela Natura</title>
<meta name="description" content="__T_DESCRIPTION__">
<link rel="alternate" type="application/atom+xml" title="__T_FEED_ALT__" href="feed.xml">
__FAVICON__
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
__COMMON_CSS__
:root{--accent:#2f7a55;--accent-dark:#62b88a}

/* Own tokens: the neutral ones point at the common ones; the ones with meaning stay here. */
:root{
  --suelo:var(--ground); --papel:var(--paper); --tinta:var(--ink); --gris:var(--muted); --linea:var(--line);
  --sombra:var(--shadow);
  --sobreimpresion:#c21f78; --natura-f:rgba(47,122,85,.10);
  --provisional:#a86a08; --confirmada:#b3261e; --apagado:#6d7d73;
  --sin:#b3261e; --tram:#2856a3; --reso:var(--natura);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --sobreimpresion:#f0509f; --natura-f:rgba(98,184,138,.12);
    --provisional:#e0a23a; --confirmada:#f06b5f; --apagado:#8a9a90;
    --sin:#f06b5f; --tram:#7ea6ec;
  }
}
:root[data-theme="dark"]{
  --sobreimpresion:#f0509f; --natura-f:rgba(98,184,138,.12);
  --provisional:#e0a23a; --confirmada:#f06b5f; --apagado:#8a9a90;
  --sin:#f06b5f; --tram:#7ea6ec;
}
html{-webkit-text-size-adjust:100%}
.dato{font-family:var(--font-data);font-variant-numeric:tabular-nums}
.site-header .label{color:var(--muted);font-size:14px}
.site-header .lede{text-wrap:pretty}
.figures div.meta b{font-size:17px;line-height:1.75}
main{max-width:1440px;margin:0 auto;padding:0 16px;display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,1fr);gap:18px;align-items:start}
#mapa{position:sticky;top:12px;height:calc(100vh - 24px);min-height:420px;border:1px solid var(--linea);background:var(--papel)}
.lista{display:grid;gap:14px;padding-bottom:40px}
.filtros{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--linea);position:sticky;top:0;background:var(--suelo);z-index:5}
.filtros label{font-size:13px;color:var(--gris);display:flex;gap:6px;align-items:center}
.filtros select{max-width:min(260px,62vw);font:14px var(--font-text);background:var(--papel);color:var(--tinta);border:1px solid var(--linea);padding:4px 6px}
.cuenta{margin-left:auto;font-size:13px;color:var(--gris)}
.ficha{display:grid;gap:10px;padding:14px 16px 16px;scroll-margin-top:60px}
.ficha.sel{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),var(--sombra)}
.ficha header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.ficha h2{margin:0;font:600 22px/1.15 var(--font-title);letter-spacing:.01em;flex:1 1 100%;text-wrap:balance}
.id{font-size:12px;color:var(--gris)}
.sello.provisional{color:var(--provisional)} .sello.confirmada{color:var(--confirmada)}
.sello.revertida,.sello.descartada{color:var(--apagado)}
.sello.sin_expediente{color:var(--sin);background:color-mix(in srgb,var(--sin) 10%,transparent)}
.sello.tramitacion{color:var(--tram)} .sello.resolucion{color:var(--reso)}
.donde{margin:0;font-size:15px;color:var(--gris)}
.donde strong{color:var(--tinta);font-weight:600}
.fotos{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.fotos figure{margin:0;display:grid;gap:4px}
.fotos img{width:100%;aspect-ratio:1;object-fit:cover;display:block;background:var(--linea)}
.fotos figcaption{font-size:12px;color:var(--gris)}
dl.medidas{margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px 12px}
dl.medidas div{display:grid;gap:1px}
dl.medidas dt{font-size:11.5px;color:var(--gris)}
dl.medidas dd{margin:0;font:500 15px var(--font-data);font-variant-numeric:tabular-nums}
.exped{margin:0;padding:0;list-style:none;display:grid;gap:6px;font-size:14.5px}
.exped li{padding-left:12px;border-left:2px solid var(--linea)}
.exped .dato{font-size:12px;color:var(--gris)}
.nota{font-size:13.5px;color:var(--gris);margin:0}
.parcelas{display:grid;gap:6px}
.parcelas h3{margin:0;font:600 12px/1 var(--font-title);text-transform:uppercase;letter-spacing:.09em;color:var(--gris)}
.parcelas ul{margin:0;padding:0;list-style:none;display:grid;gap:3px;font-size:14px}
.parcelas li{display:flex;flex-wrap:wrap;gap:2px 10px;align-items:baseline}
.parcelas li .dato{font-size:12.5px;color:var(--gris)}
.parcelas details summary{cursor:pointer;font-size:13px;color:var(--gris);width:max-content;max-width:100%}
.parcelas details[open] summary{margin-bottom:3px}
.parcelas li a.dato{color:var(--tinta)}
.acciones{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:14px}
.acciones button{font:inherit;background:none;border:0;padding:0;color:inherit;text-decoration:underline;text-decoration-color:var(--accent);text-underline-offset:3px;cursor:pointer}
.paises{margin:0;font-size:14px;color:var(--muted)}
.paises a[aria-current]{color:var(--ink);text-decoration:none}
.uso{font-size:14px;margin:0}
.uso .dato{font-size:12.5px;color:var(--gris)}
.vacio{padding:28px 16px;border:1px dashed var(--linea);color:var(--gris);text-align:center}
.method{margin-top:24px;padding-bottom:40px;border-top:1px solid var(--line);display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px}
.method p{margin:0 0 10px}
.method ol{margin:0 0 10px;padding-left:1.4em;display:grid;gap:6px}
table.params th{width:38%}
.leaflet-container{background:var(--papel);font:13px var(--font-text)}
.leaflet-control-layers,.leaflet-bar a{background:var(--papel);color:var(--tinta)}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:var(--papel);color:var(--tinta)}
@media (max-width: 900px){
  main{grid-template-columns:1fr}
  #mapa{position:relative;top:0;height:56vh}
  .method{grid-template-columns:1fr}
}
@media (max-width: 640px){
  table.params th{white-space:normal}
}
@media (prefers-reduced-motion: reduce){*{scroll-behavior:auto!important}}
</style>
</head>
<body>
<header class="site-header">
  <h1>__LOGO__Centinela <span>Natura</span></h1>
  <p class="label">__T_LABEL__</p>
  __T_PAISES__
  <p class="lede">__T_LEDE__</p>
  <div class="figures">
    <div><b>__ACTIVAS__</b><span>__T_FIG_ACTIVAS__</span></div>
    <div><b>__CONFIRMADAS__</b><span>__T_FIG_CONFIRMADAS__</span></div>
    <div><b>__HA__</b><span>__T_FIG_HA__</span></div>
    <div><b>__CON_EXPEDIENTE__</b><span>__T_FIG_EXPEDIENTE__</span></div>
    <div class="meta"><b>__VENTANA__</b><span>__T_FIG_META__</span></div>
  </div>
</header>

<main>
  <div id="mapa" role="region" aria-label="__T_MAPA_ARIA__"></div>
  <div class="lista">
    <div class="filtros">
__T_FILTROS__
      <span class="cuenta" id="cuenta" aria-live="polite"></span>
    </div>
    <div id="fichas"></div>
  </div>
</main>

<section class="method" id="metodo">
  <div>
__T_METODO__
  </div>
  <div>
    <h3>__T_PARAMETROS__</h3>
    __METODO__
__T_DATOS__
  </div>
</section>

<footer class="site-footer">
  <p class="principle">__T_PRINCIPIO__</p>
  <p>__T_CREDITOS__</p>
__T_SIBLINGS__
</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const D = __DATOS__;
const T = D.t;
const tr = (s,o) => s.replace(/\{(\w+)\}/g,(m,k)=>o[k]);
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MES = D.meses;
const mes = m => { if(!m) return "—"; const [y,mm] = m.split("-"); return MES[+mm-1]+T.de+y; };
const fecha = f => { if(!f) return "—"; const [y,m,d] = f.split("-"); return (+d)+" "+D.meses_cortos[+m-1]+" "+y; };
const num = (x,d=1) => x==null ? "—" : x.toLocaleString(T.locale,{minimumFractionDigits:d,maximumFractionDigits:d});
const esc = s => String(s??"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const mapa = L.map("mapa",{zoomControl:true,preferCanvas:false}).setView(D.vista,9);
const pnoa = L.tileLayer(D.orto.url,
  {maxZoom:D.orto.maxZoom,attribution:D.orto.atribucion});
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'});
osm.addTo(mapa);
const capaNatura = L.geoJSON(D.espacios,{style:()=>({color:css("--natura"),weight:1,fillColor:css("--natura"),fillOpacity:.16}),
  onEachFeature:(f,l)=>l.bindTooltip(esc(f.properties.nombre)+" · "+esc(f.properties.tipo),{sticky:true})}).addTo(mapa);
L.control.layers({[T.osm]:osm,[D.orto.nombre]:pnoa},{[T.natura]:capaNatura},{collapsed:true}).addTo(mapa);
mapa.on("zoomend",()=>{ if(mapa.getZoom()>=15 && mapa.hasLayer(osm)){ mapa.removeLayer(osm); pnoa.addTo(mapa);} });

const colorEstado = e => css(e==="confirmada"?"--confirmada":e==="provisional"?"--provisional":"--apagado");
const capas = {};
const todas = D.alertas.features;
const capaAlertas = L.layerGroup().addTo(mapa);

// Las opciones llevan cuántas alertas activas hay en cada una; las vacías no se ofrecen.
const activa = p => p.estado==="provisional" || p.estado==="confirmada";
function opciones(sel, nombres, campo){
  const n = {}; for (const f of todas) if (activa(f.properties)) n[f.properties[campo]] = (n[f.properties[campo]]||0)+1;
  for (const [k,v] of Object.entries(nombres)) if (n[k]) document.getElementById(sel).insertAdjacentHTML("beforeend",`<option value="${k}">${esc(v)} (${n[k]})</option>`);
}
opciones("f-cruce", D.cruces, "cruce");
opciones("f-clase", D.clases, "clase");
if (D.usos){ for (const f of todas) f.properties.uso = f.properties.rpg ? f.properties.rpg.uso : ""; opciones("f-uso", D.usos, "uso"); }

const ordenEstado = {confirmada:0,provisional:1,revertida:2,descartada:3};
const ordenCruce = {sin_expediente:0,pendiente:1,tramitacion:2,resolucion:3};

function ficha(p){
  const esp = p.espacios.map(e=>`${esc(e.nombre)} <span class="dato">${esc(e.codigo)}</span>`).join(" · ") || T.natura;
  const titulo = (D.clases[p.clase] || T.en_estudio) + " · " + num(p.ha,2) + " ha";
  const fotos = p.foto_antes ? `<div class="fotos">
      <figure><img loading="lazy" src="${p.foto_antes}" alt="${tr(T.alt_antes,{f:fecha(p.fecha_antes)})}"><figcaption>${T.antes} · ${fecha(p.fecha_antes)}</figcaption></figure>
      <figure><img loading="lazy" src="${p.foto_despues}" alt="${tr(T.alt_despues,{f:fecha(p.fecha_despues)})}"><figcaption>${T.despues} · ${fecha(p.fecha_despues)}</figcaption></figure>
    </div>` : `<p class="nota">${esc((T.notas||{})[p.clase_nota] || p.clase_nota || T.sin_fotos)}</p>`;
  const ha = x => num(x, x < 10 ? 2 : 0);
  const linea = c => `<li>
        <a class="dato" href="${D.sede.replace("{}",encodeURIComponent(c.refcat))}">${esc(c.refcat)}</a>
        <span>${c.section ? tr(T.section,{s:c.section,n:c.numero})+(c.prefixe!=="000" ? tr(T.prefixe,{p:c.prefixe}) : "") : c.tipo==="rustica" ? `polígono ${c.poligono}, parcela ${c.parcela}` : "urbana"}${c.descuento ? " (camino o cauce público)" : ""}</span>
        <span class="dato">${tr(T.ha_de,{a:ha(c.ha_alerta),b:ha(c.ha_parcela)})}</span></li>`;
  const lista = p.parcelas || [], resto = lista.slice(3), mas = (p.n_parcelas||0) - lista.length;
  const parc = !p.parcelas ? `<p class="nota">${T.parc_pend}</p>`
    : !lista.length ? `<p class="nota">${T.parc_ninguna}</p>`
    : `<div class="parcelas"><h3>${T.parc_titulo}</h3><ul>${lista.slice(0,3).map(linea).join("")}</ul>
      ${resto.length ? `<details><summary>${tr(T.parc_mas,{n:resto.length + Math.max(mas,0)})}</summary><ul>${resto.map(linea).join("")}</ul>${mas>0 ? `<p class="nota">${tr(T.parc_menores,{n:mas})}</p>` : ""}</details>` : ""}
      ${p.fraccion_parcelada < .95 ? `<p class="nota">${tr(T.parc_fuera,{n:Math.round(100*(1-p.fraccion_parcelada))})}</p>` : ""}</div>`;
  const nm = p.expedientes_municipio;
  const ctx = nm ? tr(nm===1 ? T.ctx_uno : T.ctx_varios,{m:esc(p.municipios.join(", ")),n:nm}) : "";
  const ex = (p.expedientes||[]).length ? `<ul class="exped">${p.expedientes.map(x=>`<li><a href="${esc(x.url)}">${esc(x.tipo && T.tipo_dau ? T.tipo_dau[x.tipo]+" "+x.titulo : x.titulo)}</a><br><span class="dato">${esc(x.fuente)} · ${fecha(x.fecha)}${x.etat && T.etat ? " · "+esc(T.etat[x.etat]||x.etat)+(T.dest[x.destination] ? " · "+esc(T.dest[x.destination]) : "") : ""}${x.sentido_etiqueta && x.grupo==="resoluciones" ? " · "+esc(x.sentido_etiqueta):""} · ${T.cita} ${x.parcelas.map(esc).join(", ")}</span></li>`).join("")}</ul>`
    : p.parcelas ? `<p class="nota">${tr(T.sin_cruce,{url:D.observatorio})}${ctx}</p>` : "";
  const unidas = (p.unidas||[]).length ? `<p class="nota">${tr(T.unidas,{n:p.unidas.length+1,ids:p.unidas.map(esc).join(", ")})}</p>` : "";
  const r = p.rpg;
  const uso = !T.uso_titulo || !r ? "" : `<div class="parcelas"><h3>${tr(T.uso_titulo,{a:r.anio})}</h3>${r.codigo
    ? `<p class="uso"><strong>${esc(r.libelle)}</strong> <span class="dato">${esc(r.codigo)} · ${tr(T.uso_frac,{n:Math.round(100*r.fraccion)})}</span></p>${r.uso==="pradera_permanente" ? `<p class="nota">${T.uso_nota_pp}</p>` : r.uso==="rotacion" ? `<p class="nota">${T.uso_nota_rot}</p>` : ""}`
    : `<p class="nota">${T.uso_sin}</p>`}</div>`;
  return `<article class="card ficha" id="${p.id}" data-id="${p.id}">
    <header>
      <span class="badge sello ${p.estado}">${esc(D.estados[p.estado])}</span>
      ${p.cruce==="resolucion"||p.cruce==="tramitacion" ? `<span class="badge sello ${p.cruce}">${esc(D.cruces[p.cruce])}</span>` : ""}${D.usos && p.uso && p.uso!=="sin_declarar" ? `
      <span class="badge sello">${esc(D.usos[p.uso])}</span>` : ""}
      <span class="id dato">${p.id}</span>
      <h2>${esc(titulo)}</h2>
    </header>
    <p class="donde"><strong>${esc(p.municipios.join(", "))}</strong> · ${esp}</p>
    ${fotos}
    <dl class="medidas">
      <div><dt>${T.ndvi}</dt><dd>${num(p.ndvi_ref,2)} → ${num(p.ndvi_actual,2)}</dd></div>
      <div><dt>${T.ultima_veg}</dt><dd>${mes(p.ultima_vegetacion)}</dd></div>
      <div><dt>${p.reconstruida ? T.detectable : T.primera}</dt><dd>${fecha(p.detectada)}</dd></div>
      <div><dt>${T.corine}</dt><dd style="font-family:inherit">${esc((D.clc && D.clc[p.cubierta_previa?.codigo]) || p.cubierta_previa?.nombre || "—")}</dd></div>
    </dl>
    ${unidas}
    ${parc}${uso ? "\n    "+uso : ""}
    ${ex}
    <div class="acciones">
      <button type="button" data-zoom="${p.id}">${T.ver_orto}</button>
      <a href="https://www.openstreetmap.org/?mlat=${p.centro[0]}&mlon=${p.centro[1]}#map=17/${p.centro[0]}/${p.centro[1]}">OpenStreetMap</a>
      <span class="dato" style="color:var(--gris)">${p.centro[0].toFixed(5)}, ${p.centro[1].toFixed(5)}</span>
    </div>
  </article>`;
}

function filtrar(){
  const fe = document.getElementById("f-estado").value, fc = document.getElementById("f-cruce").value, fk = document.getElementById("f-clase").value, fu = document.getElementById("f-uso")?.value;
  const ok = todas.filter(f=>{
    const p = f.properties;
    if (fe==="activas" && !(p.estado==="provisional"||p.estado==="confirmada")) return false;
    if (fe==="cerradas" && !(p.estado==="revertida"||p.estado==="descartada")) return false;
    if (["confirmada","provisional"].includes(fe) && p.estado!==fe) return false;
    if (fc && p.cruce!==fc) return false;
    if (fk && p.clase!==fk) return false;
    if (fu && p.uso!==fu) return false;
    return true;
  }).sort((a,b)=>{ const p=a.properties,q=b.properties;
    return (ordenEstado[p.estado]-ordenEstado[q.estado]) || (ordenCruce[p.cruce]-ordenCruce[q.cruce]) || (q.ha-p.ha); });
  document.getElementById("fichas").innerHTML = ok.length ? ok.map(f=>ficha(f.properties)).join("")
    : `<div class="vacio">${T.vacio}</div>`;
  document.getElementById("cuenta").textContent = ok.length + (ok.length===1?T.alerta:T.alertas);
  capaAlertas.clearLayers();
  for (const f of ok){
    const p = f.properties, c = colorEstado(p.estado);
    const l = L.geoJSON(f,{style:{color:css("--sobreimpresion"),weight:2,fillColor:c,fillOpacity:.35}});
    const m = L.circleMarker([p.centro[0],p.centro[1]],{radius:6,color:css("--sobreimpresion"),weight:2,fillColor:c,fillOpacity:.9});
    const g = L.featureGroup([l,m]).on("click",()=>seleccionar(p.id,false));
    g.bindTooltip(esc((D.clases[p.clase]||D.cambio)+" · "+num(p.ha,2)+" ha · "+p.municipios[0]));
    g.addTo(capaAlertas); capas[p.id] = g;
  }
}

function seleccionar(id, zoom, animar=true){
  document.querySelectorAll(".ficha.sel").forEach(e=>e.classList.remove("sel"));
  const el = document.getElementById(id);
  if (el){ el.classList.add("sel"); if(!zoom) el.scrollIntoView({block:"start"}); }
  if (zoom && capas[id]){ mapa.fitBounds(capas[id].getBounds(),{maxZoom:17,padding:[40,40],animate:animar}); if(mapa.hasLayer(osm)){mapa.removeLayer(osm); pnoa.addTo(mapa);} }
  history.replaceState(null,"","#"+id);
}

document.getElementById("fichas").addEventListener("click",e=>{
  const b = e.target.closest("[data-zoom]"); if (b){ tocado = true; seleccionar(b.dataset.zoom,true); }
});
for (const id of ["f-estado","f-cruce","f-clase","f-uso"]) document.getElementById(id)?.addEventListener("change",filtrar);
filtrar();
// El mapa se encuadra cuando ya tiene su tamaño: si la página aún no ha acabado de
// maquetar, Leaflet calcula el zoom para un contenedor sin altura. Mientras nadie lo
// toque, se vuelve a encuadrar cada vez que el contenedor cambia de tamaño, y sin
// animación: un invalidateSize a mitad de la animación la deja en un zoom intermedio.
let h = location.hash.slice(1), tocado = false;
if (D.redir[h]) { h = D.redir[h]; history.replaceState(null,"","#"+h); }
if (h && !capas[h]) { document.getElementById("f-estado").value="todas"; filtrar(); }
const encuadrar = () => capas[h] ? seleccionar(h,true,false) : mapa.fitBounds(capaNatura.getBounds(),{padding:[10,10],animate:false});
for (const ev of ["mousedown","touchstart","wheel","keydown"]) document.getElementById("mapa").addEventListener(ev,()=>{tocado=true},{passive:true});
encuadrar();
new ResizeObserver(()=>{ mapa.invalidateSize(); if(!tocado) encuadrar(); }).observe(document.getElementById("mapa"));
</script>
</body>
</html>
"""
