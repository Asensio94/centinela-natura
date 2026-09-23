"""La web pública: mapa, fichas de alerta, fuente Atom y metodología generada desde config."""
from __future__ import annotations

import html
import json
import shutil
from datetime import datetime, timezone

from shapely.geometry import mapping, shape

from . import alertas as al
from . import clasificacion, config, expedientes, zona

REPO_URL = "https://github.com/Asensio94/centinela-natura"
WEB_URL = "https://asensio94.github.io/centinela-natura/"
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


def _mes_largo(mes: str | None) -> str:
    if not mes:
        return "—"
    y, m = map(int, mes.split("-"))
    return f"{MESES[m - 1]} de {y}"


def _ventana_txt(meses: list[str]) -> str:
    """«julio–septiembre de 2026», o con los dos años si la ventana cruza el cambio de año."""
    if not meses:
        return "—"
    (y0, m0), (y1, m1) = (map(int, meses[0].split("-")), map(int, meses[-1].split("-")))
    if y0 == y1:
        return f"{MESES[m0 - 1]}–{MESES[m1 - 1]} de {y1}"
    return f"{MESES[m0 - 1]} de {y0}–{MESES[m1 - 1]} de {y1}"


def _num(x: float, dec: int = 1) -> str:
    s = f"{x:,.{dec}f}"
    return s.replace(",", "·").replace(".", ",").replace("·", ".")


def _espacios_web() -> dict:
    """Límites simplificados para pintar en el mapa (el original pesa 2,6 MB)."""
    fc = json.loads(zona.ESPACIOS_GEOJSON.read_text(encoding="utf-8"))
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
        p["cruce_nombre"] = expedientes.ESTADOS.get(a.get("cruce", ""), "")
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


ESTADOS = {
    "provisional": "Provisional",
    "confirmada": "Confirmada",
    "revertida": "Revertida",
    "descartada": "Descartada",
}


def _atom(reg: dict, ahora: str) -> str:
    activas = [a for a in reg["alertas"] if a["estado"] in al.ACTIVAS]
    activas.sort(key=lambda a: a["detectada"], reverse=True)
    entradas = []
    for a in activas[:100]:
        esp = ", ".join(e["nombre"] for e in a["espacios"]) or "Red Natura 2000"
        mun = ", ".join(a["municipios"])
        titulo = f"{a.get('clase_nombre', 'Cambio')}: {_num(a['ha'], 2)} ha en {esp} ({mun})"
        resumen = (f"{ESTADOS[a['estado']]}. {expedientes.ESTADOS.get(a.get('cruce', ''), '')}. "
                   f"NDVI de {_num(a['ndvi_ref'], 2)} a {_num(a['ndvi_actual'], 2)}.")
        actualizado = a["historial"][-1]["fecha"]
        entradas.append(f"""  <entry>
    <id>{WEB_URL}#{a['id']}</id>
    <title>{html.escape(titulo)}</title>
    <link href="{WEB_URL}#{a['id']}"/>
    <updated>{actualizado}T00:00:00Z</updated>
    <summary>{html.escape(resumen)}</summary>
  </entry>""")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Centinela Natura: alertas en la Red Natura 2000 de {config.REGION}</title>
  <id>{WEB_URL}</id>
  <link href="{WEB_URL}"/>
  <link rel="self" href="{WEB_URL}feed.xml"/>
  <updated>{ahora}</updated>
{chr(10).join(entradas)}
</feed>
"""


def construir() -> None:
    reg = al.cargar()
    site = config.SITE_DIR
    if site.exists():
        shutil.rmtree(site)
    (site / "chips").mkdir(parents=True)
    for p in config.CHIPS_DIR.glob("*.jpg"):
        shutil.copy2(p, site / "chips" / p.name)
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    gj = _geojson_alertas(reg)
    (site / "alertas.geojson").write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    (site / "feed.xml").write_text(_atom(reg, ahora), encoding="utf-8")
    esp = _espacios_web()
    (site / "espacios.geojson").write_text(json.dumps(esp, ensure_ascii=False), encoding="utf-8")

    acts = [a for a in reg["alertas"] if a["estado"] in al.ACTIVAS]
    ult = reg.get("ultima_ventana")
    ej = reg["ejecuciones"].get(ult, {}) if ult else {}
    datos = {
        "alertas": _ligera(gj), "espacios": esp,
        "clases": clasificacion.CLASES, "estados": ESTADOS, "cruces": expedientes.ESTADOS,
        "observatorio": expedientes.OBSERVATORIO_WEB,
    }
    resumen = {
        "activas": len(acts),
        "confirmadas": sum(a["estado"] == "confirmada" for a in acts),
        "sin_expediente": sum(a.get("cruce") == "sin_expediente" for a in acts),
        "ha": _num(sum(a["ha"] for a in acts), 1),
        "ventana": _ventana_txt(ej.get("ventana") or []),
        "evaluable": f"{round(100 * ej.get('fraccion_evaluable', 0))} %" if ej else "—",
        "expedientes_desde": reg.get("expedientes_desde") or "—",
        "actualizado": (reg.get("actualizado") or ahora)[:10],
        "zona_ha": _num(zona.mascara().sum() * config.PIXEL_HA, 0),
        "n_espacios": len(esp["features"]),
    }
    html_txt = (PLANTILLA
                .replace("__DATOS__", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
                .replace("__METODO__", _metodo()))
    for k, v in resumen.items():
        html_txt = html_txt.replace(f"__{k.upper()}__", html.escape(str(v)))
    (site / "index.html").write_text(html_txt, encoding="utf-8")
    (site / ".nojekyll").write_text("", encoding="utf-8")


def _metodo() -> str:
    c = config
    filas = [
        ("Satélite", "Sentinel-2 L2A (Copernicus), servido por Earth Search en AWS"),
        ("Resolución", f"{c.RESOLUCION_M} m por píxel, malla fija en WGS84 / UTM 30N"),
        ("Píxeles válidos", "clases 4 a 7 de la capa SCL de Sen2Cor: vegetación, suelo, agua y sin clasificar"),
        ("Nieve", f"fuera si NDSI > {_num(c.NIEVE_NDSI_MIN, 1)}, infrarrojo > {_num(c.NIEVE_NIR_MIN, 2)} y verde > {_num(c.NIEVE_VERDE_MIN, 2)} (SNOMAP, Hall et al. 1995)"),
        ("Sombra", f"fuera si el infrarrojo cercano es < {_num(c.NIR_SENAL_MIN, 2)}, salvo el agua"),
        ("Orillas de embalse y marismas", f"sin evaluar donde hubo agua un mes entero en los {c.AGUA_MESES_ATRAS} meses anteriores"),
        ("Compuesto mensual", "NDVI máximo de cada píxel en el mes"),
        ("Ventana", f"{c.VENTANA_MESES} meses, comparada con la misma ventana de los {c.ANIOS_REFERENCIA} años anteriores"),
        ("Vegetación de referencia", f"NDVI máximo ≥ {_num(c.NDVI_REF_MIN, 2)} en todos los años de referencia"),
        ("Cambio", f"NDVI máximo actual ≤ {_num(c.NDVI_ACTUAL_MAX, 2)} y caída ≥ {_num(c.CAIDA_MIN, 2)}"),
        ("Observaciones mínimas", f"{c.OBS_MIN} válidas por píxel en cada ventana"),
        ("Unidad mínima", f"{c.UMA_PIXELES} píxeles contiguos ({_num(c.UMA_PIXELES * c.PIXEL_HA, 1)} ha)"),
        ("Vuelta de la vegetación", f"NDVI máximo medio ≥ {_num(al.NDVI_RECUPERADA, 2)} en el polígono"),
    ]
    tabla = "\n".join(f"<tr><th scope=\"row\">{html.escape(a)}</th><td>{html.escape(b)}</td></tr>"
                      for a, b in filas)
    return f'<table class="params">{tabla}</table>'


PLANTILLA = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Centinela Natura</title>
<meta name="description" content="Cambios físicos del terreno en la Red Natura 2000 de Cantabria, detectados con Sentinel-2 y cruzados con los expedientes publicados.">
<link rel="alternate" type="application/atom+xml" title="Alertas del Centinela Natura" href="feed.xml">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='6' fill='%231d2a24'/%3E%3Cpath d='M16 6v20M6 16h20' stroke='%23e0338a' stroke-width='3'/%3E%3Ccircle cx='16' cy='16' r='6' fill='none' stroke='%23e0338a' stroke-width='2.5'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
:root{
  --suelo:#eef1ec; --papel:#f8faf6; --tinta:#1b2721; --gris:#5a6860; --linea:#cfd8d1;
  --sobreimpresion:#c21f78; --natura:#2f7a55; --natura-f:rgba(47,122,85,.10);
  --provisional:#a86a08; --confirmada:#b3261e; --apagado:#6d7d73;
  --sin:#b3261e; --tram:#2856a3; --reso:#2f7a55;
  --sombra:0 1px 0 rgba(27,39,33,.06), 0 6px 18px -10px rgba(27,39,33,.25);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --suelo:#121915; --papel:#18211c; --tinta:#e3ebe5; --gris:#9aaba1; --linea:#2c3a32;
    --sobreimpresion:#f0509f; --natura:#62b88a; --natura-f:rgba(98,184,138,.12);
    --provisional:#e0a23a; --confirmada:#f06b5f; --apagado:#8a9a90;
    --sin:#f06b5f; --tram:#7ea6ec; --reso:#62b88a;
    --sombra:0 1px 0 rgba(0,0,0,.3), 0 8px 22px -12px rgba(0,0,0,.7);
  }
}
:root[data-theme="dark"]{
  --suelo:#121915; --papel:#18211c; --tinta:#e3ebe5; --gris:#9aaba1; --linea:#2c3a32;
  --sobreimpresion:#f0509f; --natura:#62b88a; --natura-f:rgba(98,184,138,.12);
  --provisional:#e0a23a; --confirmada:#f06b5f; --apagado:#8a9a90;
  --sin:#f06b5f; --tram:#7ea6ec; --reso:#62b88a;
  --sombra:0 1px 0 rgba(0,0,0,.3), 0 8px 22px -12px rgba(0,0,0,.7);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--suelo);color:var(--tinta);font:17px/1.55 "Source Serif 4",Georgia,serif}
a{color:inherit;text-decoration-color:var(--sobreimpresion);text-underline-offset:3px}
a:focus-visible,button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--sobreimpresion);outline-offset:2px}
.rotulo{font-family:"Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.08em;font-weight:600}
.dato{font-family:"IBM Plex Mono",ui-monospace,monospace;font-variant-numeric:tabular-nums}
header.cabecera{padding:28px 16px 18px;max-width:1440px;margin:0 auto;display:grid;gap:14px}
.marca{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap}
h1{margin:0;font:700 clamp(40px,6vw,64px)/.9 "Barlow Condensed","Arial Narrow",sans-serif;text-transform:uppercase;letter-spacing:.02em}
h1 .cruz{color:var(--sobreimpresion)}
.marca .rotulo{color:var(--gris);font-size:14px}
.lede{margin:0;max-width:68ch;color:var(--tinta);font-size:18px;text-wrap:pretty}
.cifras{display:flex;flex-wrap:wrap;gap:0;border-top:1.5px solid var(--tinta);border-bottom:1px solid var(--linea)}
.cifra{padding:10px 18px 10px 0;margin-right:18px;display:grid;gap:2px}
.cifra b{font:600 30px/1 "IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.cifra span{font-size:12.5px;color:var(--gris)}
.cifra.alarma b{color:var(--sin)}
.cifra.meta b{font-size:17px;line-height:1.75}
main{max-width:1440px;margin:0 auto;padding:0 16px;display:grid;grid-template-columns:minmax(0,1.35fr) minmax(360px,1fr);gap:18px;align-items:start}
#mapa{position:sticky;top:12px;height:calc(100vh - 24px);min-height:420px;border:1px solid var(--linea);background:var(--papel)}
.lista{display:grid;gap:14px;padding-bottom:40px}
.filtros{display:flex;flex-wrap:wrap;gap:8px 14px;align-items:center;padding:10px 0;border-bottom:1px solid var(--linea);position:sticky;top:0;background:var(--suelo);z-index:5}
.filtros label{font-size:13px;color:var(--gris);display:flex;gap:6px;align-items:center}
.filtros select{font:14px "Source Serif 4",serif;background:var(--papel);color:var(--tinta);border:1px solid var(--linea);padding:4px 6px}
.cuenta{margin-left:auto;font-size:13px;color:var(--gris)}
.ficha{background:var(--papel);border:1px solid var(--linea);box-shadow:var(--sombra);padding:14px 16px 16px;display:grid;gap:10px;scroll-margin-top:60px}
.ficha.sel{border-color:var(--sobreimpresion);box-shadow:0 0 0 1px var(--sobreimpresion),var(--sombra)}
.ficha header{display:flex;flex-wrap:wrap;gap:6px 10px;align-items:center}
.ficha h2{margin:0;font:600 22px/1.15 "Barlow Condensed","Arial Narrow",sans-serif;letter-spacing:.01em;flex:1 1 100%;text-wrap:balance}
.id{font-size:12px;color:var(--gris)}
.sello{font:600 12px/1 "Barlow Condensed",sans-serif;text-transform:uppercase;letter-spacing:.09em;padding:4px 7px 3px;border:1.5px solid currentColor}
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
dl.medidas dd{margin:0;font:500 15px "IBM Plex Mono",monospace;font-variant-numeric:tabular-nums}
.exped{margin:0;padding:0;list-style:none;display:grid;gap:6px;font-size:14.5px}
.exped li{padding-left:12px;border-left:2px solid var(--linea)}
.exped .dato{font-size:12px;color:var(--gris)}
.nota{font-size:13.5px;color:var(--gris);margin:0}
.acciones{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:14px}
.acciones button{font:inherit;background:none;border:0;padding:0;color:inherit;text-decoration:underline;text-decoration-color:var(--sobreimpresion);text-underline-offset:3px;cursor:pointer}
.vacio{padding:28px 16px;border:1px dashed var(--linea);color:var(--gris);text-align:center}
section.metodo{max-width:1440px;margin:24px auto 0;padding:26px 16px 40px;border-top:1.5px solid var(--tinta);display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:28px}
section.metodo h2{margin:0 0 6px;font:700 28px/1 "Barlow Condensed",sans-serif;text-transform:uppercase;letter-spacing:.03em}
section.metodo h3{margin:18px 0 4px;font:600 18px/1.2 "Barlow Condensed",sans-serif;text-transform:uppercase;letter-spacing:.06em}
section.metodo p{margin:0 0 10px;max-width:66ch}
table.params{border-collapse:collapse;width:100%;font-size:14.5px}
table.params th,table.params td{text-align:left;vertical-align:top;padding:7px 10px 7px 0;border-bottom:1px solid var(--linea)}
table.params th{font-weight:600;width:38%}
footer{max-width:1440px;margin:0 auto;padding:16px 16px 40px;font-size:13px;color:var(--gris);border-top:1px solid var(--linea)}
.leaflet-container{background:var(--papel);font:13px "Source Serif 4",serif}
.leaflet-control-layers,.leaflet-bar a{background:var(--papel);color:var(--tinta)}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:var(--papel);color:var(--tinta)}
@media (max-width: 900px){
  main{grid-template-columns:1fr}
  #mapa{position:relative;top:0;height:56vh}
  section.metodo{grid-template-columns:1fr}
}
@media (prefers-reduced-motion: reduce){*{scroll-behavior:auto!important}}
</style>
</head>
<body>
<header class="cabecera">
  <div class="marca">
    <h1>Centinela<span class="cruz">+</span>Natura</h1>
    <span class="rotulo">Red Natura 2000 · Cantabria · Sentinel-2</span>
  </div>
  <p class="lede">Cambios físicos del terreno dentro de los espacios protegidos: obras, explanaciones, balsas, cortas o quemas. Se detectan cada día en imágenes de satélite con reglas fijas y se cruzan con los expedientes que se publican en el BOE y en el Boletín Oficial de Cantabria.</p>
  <div class="cifras">
    <div class="cifra"><b>__ACTIVAS__</b><span>alertas activas</span></div>
    <div class="cifra"><b>__CONFIRMADAS__</b><span>confirmadas</span></div>
    <div class="cifra alarma"><b>__SIN_EXPEDIENTE__</b><span>sin expediente conocido</span></div>
    <div class="cifra"><b>__HA__</b><span>hectáreas afectadas</span></div>
    <div class="cifra meta"><b class="dato">__VENTANA__</b><span>ventana comparada · __EVALUABLE__ de la zona con cielo suficiente</span></div>
    <div class="cifra meta"><b class="dato">__ACTUALIZADO__</b><span>última actualización</span></div>
  </div>
</header>

<main>
  <div id="mapa" role="region" aria-label="Mapa de alertas"></div>
  <div class="lista">
    <div class="filtros">
      <label>Estado <select id="f-estado">
        <option value="activas">Activas</option><option value="confirmada">Confirmadas</option>
        <option value="provisional">Provisionales</option><option value="cerradas">Revertidas y descartadas</option>
        <option value="todas">Todas</option></select></label>
      <label>Expediente <select id="f-cruce"><option value="">Cualquiera</option></select></label>
      <label>Tipo <select id="f-clase"><option value="">Cualquiera</option></select></label>
      <span class="cuenta" id="cuenta" aria-live="polite"></span>
    </div>
    <div id="fichas"></div>
  </div>
</main>

<section class="metodo" id="metodo">
  <div>
    <h2>Cómo vigila</h2>
    <p>La zona vigilada son los __N_ESPACIOS__ espacios de la Red Natura 2000 que tocan Cantabria, ZEC y ZEPA juntas, recortados al límite de la comunidad: __ZONA_HA__ hectáreas en una malla fija de 10 metros.</p>
    <p>Cada día se rehace el mes en curso con todas las pasadas de Sentinel-2. De cada píxel se guarda el NDVI más alto del mes, que es el momento más verde que ha tenido. Las nubes bajan el NDVI, así que el máximo las ignora. Un prado segado vuelve a crecer en semanas, así que el máximo de varios meses lo sigue viendo verde. Solo el suelo que ha perdido la vegetación durante toda la ventana tiene el máximo bajo.</p>
    <p>La ventana actual se compara con la misma época de los años anteriores. Un píxel es cambio si fue vegetación densa todos esos años y ahora, en su mejor momento, no lo es. Los píxeles contiguos forman un polígono, que tiene que superar la unidad mínima.</p>
    <p>Para cada alerta nueva se busca la escena despejada más verde de antes y la más reciente de después, se publican las dos y con sus bandas se decide el tipo: agua, quemado, suelo desnudo, superficie oscura o pérdida de vegetación sin más. Son reglas con umbrales publicados en la literatura. No interviene ningún modelo entrenado ni ninguna inteligencia artificial, y cualquier alerta se puede rehacer a mano desde las imágenes.</p>
    <h3>Cruce con expedientes</h3>
    <p>El municipio de cada alerta se busca entre los anuncios y resoluciones que ha leído el <a href="https://asensio94.github.io/observatorio-alegaciones/">observatorio de alegaciones</a>, que en Cantabria cubre desde el __EXPEDIENTES_DESDE__. Un expediente en el mismo municipio no prueba que sea esa obra. «Sin expediente conocido» quiere decir que no consta ninguno publicado en ese tiempo, no que la obra carezca de permiso: muchas licencias municipales y autorizaciones forestales no pasan por los boletines.</p>
    <h3>Qué no ve</h3>
    <p>Todo lo que ocupe menos de la unidad mínima: una casa aislada, una pista estrecha o un vallado. Tampoco ve lo que ocurre bajo cubierta arbórea sin quitarla, ni los cambios en zonas que no eran vegetación densa (roquedo, arenales, láminas de agua), ni las orillas que el agua cubre y descubre (embalses, marismas), ni los meses de nieve, sombra invernal o nube persistente, que se quedan sin evaluar. Las alertas en tierras de cultivo pueden ser rotaciones.</p>
    <h3>Estados</h3>
    <p>Las alertas marcadas como «detectable desde» salieron al reconstruir las ventanas anteriores a la puesta en marcha, con la fecha en que se habrían visto.</p>
    <p><strong>Provisional</strong>: visto una vez. <strong>Confirmada</strong>: sigue ahí en la ventana de un mes posterior. <strong>Descartada</strong>: la vegetación volvió antes de confirmarse, o no se volvió a ver. <strong>Revertida</strong>: volvió después.</p>
  </div>
  <div>
    <h2>Parámetros</h2>
    __METODO__
    <h3>Datos abiertos</h3>
    <p><a href="alertas.geojson">alertas.geojson</a> con todas las alertas y su historial · <a href="feed.xml">fuente Atom</a> de las activas · compuestos mensuales en GeoTIFF en las <a href="https://github.com/Asensio94/centinela-natura/releases/tag/compuestos">releases del repositorio</a> · <a href="https://github.com/Asensio94/centinela-natura">código</a>.</p>
  </div>
</section>

<footer>
  Contiene datos modificados de Copernicus Sentinel procesados por Earth Search (Element 84) · Límites de la Red Natura 2000 y CORINE Land Cover 2018: Agencia Europea de Medio Ambiente · Municipios: © colaboradores de OpenStreetMap (ODbL) · Ortofoto PNOA: CC BY 4.0 scne.es · Expedientes: observatorio de alegaciones ambientales, a partir del BOE y el BOC.
</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const D = __DATOS__;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const MES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
const mes = m => { if(!m) return "—"; const [y,mm] = m.split("-"); return MES[+mm-1]+" de "+y; };
const fecha = f => { if(!f) return "—"; const [y,m,d] = f.split("-"); return (+d)+" "+MES[+m-1].slice(0,3)+" "+y; };
const num = (x,d=1) => x==null ? "—" : x.toLocaleString("es-ES",{minimumFractionDigits:d,maximumFractionDigits:d});
const esc = s => String(s??"").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

const mapa = L.map("mapa",{zoomControl:true,preferCanvas:false}).setView([43.2,-4.05],9);
const pnoa = L.tileLayer("https://www.ign.es/wmts/pnoa-ma?layer=OI.OrthoimageCoverage&style=default&tilematrixset=GoogleMapsCompatible&Service=WMTS&Request=GetTile&Version=1.0.0&Format=image/jpeg&TileMatrix={z}&TileCol={x}&TileRow={y}",
  {maxZoom:20,attribution:'Ortofoto PNOA <a href="https://www.scne.es/">CC BY 4.0 scne.es</a>'});
const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'});
osm.addTo(mapa);
const capaNatura = L.geoJSON(D.espacios,{style:()=>({color:css("--natura"),weight:1,fillColor:css("--natura"),fillOpacity:.16}),
  onEachFeature:(f,l)=>l.bindTooltip(esc(f.properties.nombre)+" · "+esc(f.properties.tipo),{sticky:true})}).addTo(mapa);
L.control.layers({"Mapa (OpenStreetMap)":osm,"Ortofoto PNOA":pnoa},{"Red Natura 2000":capaNatura},{collapsed:true}).addTo(mapa);
mapa.on("zoomend",()=>{ if(mapa.getZoom()>=15 && mapa.hasLayer(osm)){ mapa.removeLayer(osm); pnoa.addTo(mapa);} });

const colorEstado = e => css(e==="confirmada"?"--confirmada":e==="provisional"?"--provisional":"--apagado");
const capas = {};
const todas = D.alertas.features;
const capaAlertas = L.layerGroup().addTo(mapa);

for (const [k,v] of Object.entries(D.cruces)) document.getElementById("f-cruce").insertAdjacentHTML("beforeend",`<option value="${k}">${esc(v)}</option>`);
for (const [k,v] of Object.entries(D.clases)) document.getElementById("f-clase").insertAdjacentHTML("beforeend",`<option value="${k}">${esc(v)}</option>`);

const ordenEstado = {confirmada:0,provisional:1,revertida:2,descartada:3};
const ordenCruce = {sin_expediente:0,tramitacion:1,resolucion:2};

function ficha(p){
  const esp = p.espacios.map(e=>`${esc(e.nombre)} <span class="dato">${esc(e.codigo)}</span>`).join(" · ") || "Red Natura 2000";
  const titulo = (p.clase_nombre || "Cambio en estudio") + " · " + num(p.ha,2) + " ha";
  const fotos = p.foto_antes ? `<div class="fotos">
      <figure><img loading="lazy" src="${p.foto_antes}" alt="Imagen de satélite antes del cambio, ${fecha(p.fecha_antes)}"><figcaption>Antes · ${fecha(p.fecha_antes)}</figcaption></figure>
      <figure><img loading="lazy" src="${p.foto_despues}" alt="Imagen de satélite después del cambio, ${fecha(p.fecha_despues)}"><figcaption>Después · ${fecha(p.fecha_despues)}</figcaption></figure>
    </div>` : `<p class="nota">${esc(p.clase_nota || "Las fotos se generan en la próxima pasada con cielo despejado.")}</p>`;
  const ex = (p.expedientes||[]).length ? `<ul class="exped">${p.expedientes.map(x=>`<li><a href="${esc(x.url)}">${esc(x.titulo)}</a><br><span class="dato">${esc(x.fuente)} · ${fecha(x.fecha)}${x.sentido_etiqueta && x.grupo==="resoluciones" ? " · "+esc(x.sentido_etiqueta):""}</span></li>`).join("")}</ul>`
    : `<p class="nota">Ningún anuncio ni resolución de ${esc(p.municipios.join(", "))} en los boletines leídos por el <a href="${D.observatorio}">observatorio</a>.</p>`;
  return `<article class="ficha" id="${p.id}" data-id="${p.id}">
    <header>
      <span class="sello ${p.estado}">${esc(D.estados[p.estado])}</span>
      <span class="sello ${p.cruce}">${esc(D.cruces[p.cruce]||"")}</span>
      <span class="id dato">${p.id}</span>
      <h2>${esc(titulo)}</h2>
    </header>
    <p class="donde"><strong>${esc(p.municipios.join(", "))}</strong> · ${esp}</p>
    ${fotos}
    <dl class="medidas">
      <div><dt>NDVI antes → ahora</dt><dd>${num(p.ndvi_ref,2)} → ${num(p.ndvi_actual,2)}</dd></div>
      <div><dt>Vegetación vista por última vez</dt><dd>${mes(p.ultima_vegetacion)}</dd></div>
      <div><dt>${p.reconstruida ? "Detectable desde" : "Primera detección"}</dt><dd>${fecha(p.detectada)}</dd></div>
      <div><dt>Uso anterior (CORINE 2018)</dt><dd style="font-family:inherit">${esc(p.cubierta_previa?.nombre || "—")}</dd></div>
    </dl>
    ${ex}
    <div class="acciones">
      <button type="button" data-zoom="${p.id}">Ver en la ortofoto</button>
      <a href="https://www.openstreetmap.org/?mlat=${p.centro[0]}&mlon=${p.centro[1]}#map=17/${p.centro[0]}/${p.centro[1]}">OpenStreetMap</a>
      <span class="dato" style="color:var(--gris)">${p.centro[0].toFixed(5)}, ${p.centro[1].toFixed(5)}</span>
    </div>
  </article>`;
}

function filtrar(){
  const fe = document.getElementById("f-estado").value, fc = document.getElementById("f-cruce").value, fk = document.getElementById("f-clase").value;
  const ok = todas.filter(f=>{
    const p = f.properties;
    if (fe==="activas" && !(p.estado==="provisional"||p.estado==="confirmada")) return false;
    if (fe==="cerradas" && !(p.estado==="revertida"||p.estado==="descartada")) return false;
    if (["confirmada","provisional"].includes(fe) && p.estado!==fe) return false;
    if (fc && p.cruce!==fc) return false;
    if (fk && p.clase!==fk) return false;
    return true;
  }).sort((a,b)=>{ const p=a.properties,q=b.properties;
    return (ordenEstado[p.estado]-ordenEstado[q.estado]) || (ordenCruce[p.cruce]-ordenCruce[q.cruce]) || (q.ha-p.ha); });
  document.getElementById("fichas").innerHTML = ok.length ? ok.map(f=>ficha(f.properties)).join("")
    : `<div class="vacio">No hay alertas con estos filtros.</div>`;
  document.getElementById("cuenta").textContent = ok.length + (ok.length===1?" alerta":" alertas");
  capaAlertas.clearLayers();
  for (const f of ok){
    const p = f.properties, c = colorEstado(p.estado);
    const l = L.geoJSON(f,{style:{color:css("--sobreimpresion"),weight:2,fillColor:c,fillOpacity:.35}});
    const m = L.circleMarker([p.centro[0],p.centro[1]],{radius:6,color:css("--sobreimpresion"),weight:2,fillColor:c,fillOpacity:.9});
    const g = L.featureGroup([l,m]).on("click",()=>seleccionar(p.id,false));
    g.bindTooltip(esc((p.clase_nombre||"Cambio")+" · "+num(p.ha,2)+" ha · "+p.municipios[0]));
    g.addTo(capaAlertas); capas[p.id] = g;
  }
}

function seleccionar(id, zoom){
  document.querySelectorAll(".ficha.sel").forEach(e=>e.classList.remove("sel"));
  const el = document.getElementById(id);
  if (el){ el.classList.add("sel"); if(!zoom) el.scrollIntoView({block:"start"}); }
  if (zoom && capas[id]){ mapa.fitBounds(capas[id].getBounds(),{maxZoom:17,padding:[40,40]}); if(mapa.hasLayer(osm)){mapa.removeLayer(osm); pnoa.addTo(mapa);} }
  history.replaceState(null,"","#"+id);
}

document.getElementById("fichas").addEventListener("click",e=>{
  const b = e.target.closest("[data-zoom]"); if (b) seleccionar(b.dataset.zoom,true);
});
for (const id of ["f-estado","f-cruce","f-clase"]) document.getElementById(id).addEventListener("change",filtrar);
filtrar();
const h = location.hash.slice(1);
if (h){ if(!capas[h]){ document.getElementById("f-estado").value="todas"; filtrar(); } if(capas[h]) seleccionar(h,true); }
else mapa.fitBounds(capaNatura.getBounds(),{padding:[10,10]});
</script>
</body>
</html>
"""
