"""Textos de la web y formato de números, un diccionario por idioma.

Cada país se publica en su idioma: Cantabria en castellano, los Pirineos Atlánticos en
francés. Los datos (alertas.json, alertas.geojson, signals.json) no dependen del idioma:
guardan claves (clase, estado, cruce, código CORINE, estado de la autorización) y aquí se
les pone nombre. La excepción es el título y el permiso de cada señal de signals.json, que
el contrato de estado-iba quiere en la lengua del país (signals.py los toma de aquí). Mismo patrón que humedales/i18n.py en vigilancia-humedales.

Tipografía francesa: espacio fino irrompible (U+202F) como separador de miles y ante
«%», «:», «;», «?» y «!», y dentro de las comillas latinas. En los textos franceses se
escribe «~» donde va ese espacio y _fr() lo sustituye.
"""
from __future__ import annotations

LANG_BY_COUNTRY = {"ES": "es", "FR": "fr"}
NNBSP = " "


def lang_of(pais: str) -> str:
    return LANG_BY_COUNTRY.get(pais, "es")


def num(x: float, lang: str, dec: int = 1) -> str:
    """1.234,5 en castellano, 1 234,5 en francés."""
    s = f"{x:,.{dec}f}"
    return s.replace(",", "·").replace(".", ",").replace("·", "." if lang == "es" else NNBSP)


def pct(x: float, lang: str) -> str:
    """Una fracción en porcentaje sin decimales: 15 % / 15 %."""
    return f"{round(100 * x)}{' ' if lang == 'es' else NNBSP}%"


def _fr(v):
    if isinstance(v, str):
        return v.replace("~", NNBSP)
    if isinstance(v, dict):
        return {k: _fr(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return type(v)(_fr(x) for x in v)
    return v


MESES = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "fr": ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre"],
}
# Para las fechas de las fotos: las tres primeras letras en castellano; en francés, las
# abreviaturas de uso, porque «jui» no distingue junio de julio.
MESES_CORTOS = {
    "es": [m[:3] for m in MESES["es"]],
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
}

# El pie común de los proyectos de Terra Aperta, en el orden de su menú. Centinela va como texto,
# sin enlace. En francés, nombres en francés y la página francesa de cada proyecto si la tiene.
HUB = {"es": ("https://asensio94.github.io/terra-aperta/", "← Terra Aperta: todos los proyectos",
              "Proyectos hermanos"),
       "fr": ("https://asensio94.github.io/terra-aperta/fr/", "← Terra Aperta : tous les projets",
              "Projets frères")}
PROYECTOS = [  # (slug, nombre, nom, página francesa)
    ("sub-nocte", "Sub Nocte", "Sub Nocte", ""),
    ("vigia-incendios", "Vigía de incendios", "Vigie des incendies", "fr/"),
    ("centinela-natura", "Centinela Natura", "Centinela Natura", "fr/"),
    ("estado-iba", "Estado de las IBA", "État des IBA", "fr/"),
    ("riesgo-tendidos-aves", "Riesgo de tendidos para aves", "Risque des lignes pour les oiseaux", "regions.fr.html"),
    ("observatorio-alegaciones", "Observatorio de alegaciones", "Observatoire des consultations", ""),
    ("grafo-promotores", "Grafo de promotores", "Graphe des porteurs de projet", ""),
    ("vigilancia-humedales", "Vigilancia de humedales", "Veille des zones humides", "france.html"),
    ("caudal-ecologico", "Caudal ecológico", "Débit écologique", ""),
    ("acuiferos-francia", "Acuíferos de Francia", "Nappes de France", ""),
    ("depuracion-y-bano", "Depuración y baño", "Épuration et baignade", "fr/"),
    ("zona-inundable", "Construir en zona inundable", "Construire en zone inondable", ""),
]


def siblings(lang: str) -> str:
    """La vuelta al hub y la lista de proyectos hermanos del pie."""
    hub, volver, etiqueta = HUB[lang]
    items = []
    for slug, es, fr, pagina_fr in PROYECTOS:
        nombre = fr if lang == "fr" else es
        if slug == "centinela-natura":
            items.append(f'    <li aria-current="page">{nombre}</li>')
        else:
            href = f"https://asensio94.github.io/{slug}/" + (pagina_fr if lang == "fr" else "")
            items.append(f'    <li><a href="{href}">{nombre}</a></li>')
    return (f'  <p><a href="{hub}">{volver}</a></p>\n  <nav aria-label="{etiqueta}"><ul class="siblings">\n'
            + "\n".join(items) + "\n  </ul></nav>")


# ── Castellano: los textos de siempre, letra por letra ───────────────────────────────────

_ES_METODO = """    <h2>Cómo se calcula</h2>
    <ol>
      <li><strong>Zona.</strong> La zona vigilada son los __N_ESPACIOS__ espacios de la Red Natura 2000 que tocan Cantabria, ZEC y ZEPA juntas, recortados al límite de la comunidad: __ZONA_HA__ hectáreas en una malla fija de 10 metros.</li>
      <li><strong>Compuesto mensual.</strong> Cada día se rehace el mes en curso con todas las pasadas de Sentinel-2. De cada píxel se guarda el NDVI más alto del mes, que es el momento más verde que ha tenido. Las nubes bajan el NDVI, así que el máximo las ignora. Un prado segado vuelve a crecer en semanas, así que el máximo de varios meses lo sigue viendo verde. Solo el suelo que ha perdido la vegetación durante toda la ventana tiene el máximo bajo.</li>
      <li><strong>Detección.</strong> La ventana actual se compara con la misma época de los años anteriores. Un píxel es cambio si fue vegetación densa todos esos años y ahora, en su mejor momento, no lo es. Los píxeles contiguos forman un polígono, que tiene que superar la unidad mínima.</li>
      <li><strong>Fotos y tipo.</strong> Para cada alerta nueva se busca la escena despejada más verde de antes y la más verde de después, su mejor momento, que es lo que compara el detector, y se publican las dos (si la nieve o las nubes no dejan ver la ventana en que nació, se usa la última en que se ha visto). Con sus bandas se decide el tipo: agua, quemado, suelo desnudo, superficie oscura o pérdida de vegetación sin más. Son reglas con umbrales publicados en la literatura. No interviene ningún modelo entrenado, y cualquier alerta se puede rehacer a mano desde las imágenes.</li>
      <li><strong>Parcelas.</strong> Cada alerta se superpone a la cartografía del Catastro para saber qué parcelas toca.</li>
      <li><strong>Cruce con expedientes.</strong> De los anuncios y resoluciones de Cantabria que ha leído el <a href="https://asensio94.github.io/observatorio-alegaciones/">observatorio de alegaciones</a>, que cubre desde el __EXPEDIENTES_DESDE__, se sacan las parcelas que citan: referencias catastrales y pares «polígono, parcela» del municipio del expediente. La alerta tiene expediente si alguno cita una de sus parcelas. En monte una sola parcela puede tener cientos de hectáreas, así que coincidir en ella no prueba que sea la misma obra.</li>
    </ol>
    <p>«Sin expediente conocido» quiere decir que ningún texto publicado en ese tiempo cita sus parcelas, no que la obra carezca de permiso: muchas licencias municipales y autorizaciones forestales no pasan por los boletines, y parte de los anuncios solo dan el municipio. Esos se cuentan aparte en cada alerta.</p>
    <h3>Estados</h3>
    <p>Las alertas marcadas como «detectable desde» salieron al reconstruir las ventanas anteriores a la puesta en marcha, con la fecha en que se habrían visto.</p>
    <p><strong>Provisional</strong>: visto una vez. <strong>Confirmada</strong>: sigue ahí en la ventana de un mes posterior. <strong>Descartada</strong>: la vegetación volvió antes de confirmarse, no se volvió a ver, o estaba en la orilla de un embalse o era agua nueva sobre lo que ya era agua (cambios del nivel). <strong>Revertida</strong>: volvió después. <strong>Fusionada</strong>: era un trozo de otra alerta. Cuando la nieve o las nubes dejan parte de un cambio sin evaluar, sale en trozos que luego crecen hasta tocarse. Si están a menos de 15 metros y nacieron en ventanas que se solapan, se unen en la más antigua. Las fusionadas no se muestran aquí, pero siguen en el registro, y su enlace lleva a la alerta que las absorbió.</p>
    <h3>Validación</h3>
    <p>Pendiente: todavía no se ha contrastado con otra fuente. Cada alerta publica las dos fotos que compara el detector, para que se pueda comprobar a simple vista.</p>
    <h3>Qué no ve</h3>
    <p>Todo lo que ocupe menos de la unidad mínima: una casa aislada, una pista estrecha o un vallado. Tampoco ve lo que ocurre bajo cubierta arbórea sin quitarla, ni los cambios en zonas que no eran vegetación densa (roquedo, arenales, láminas de agua), ni las orillas que el agua cubre y descubre (embalses, marismas), ni los meses de nieve, sombra invernal o nube persistente, que se quedan sin evaluar. Las alertas en tierras de cultivo pueden ser rotaciones.</p>"""

ES = {
    "html_lang": "es",
    "description": "Cambios físicos del terreno en la Red Natura 2000 de Cantabria, detectados con Sentinel-2 y cruzados con los expedientes publicados.",
    "feed_alt": "Alertas del Centinela Natura",
    "feed_title": "Centinela Natura: alertas en la Red Natura 2000 de {region}",
    "label": "Red Natura 2000 · Cantabria · Sentinel-2",
    "lede": "Cambios físicos del terreno dentro de los espacios protegidos: obras, explanaciones, balsas, cortas o quemas. Se detectan cada día en imágenes de satélite con reglas fijas y se cruzan con los expedientes que se publican en el BOE y en el Boletín Oficial de Cantabria.",
    "fig_activas": "alertas activas",
    "fig_confirmadas": "confirmadas",
    "fig_ha": "hectáreas afectadas",
    "fig_expediente": "con un expediente que cita sus parcelas",
    "fig_meta": "ventana comparada · __EVALUABLE__ de la zona con cielo suficiente · actualizado el __ACTUALIZADO__",
    "mapa_aria": "Mapa de alertas",
    "filtros": """      <label>Estado <select id="f-estado">
        <option value="activas">Activas</option><option value="confirmada">Confirmadas</option>
        <option value="provisional">Provisionales</option><option value="cerradas">Revertidas y descartadas</option>
        <option value="todas">Todas</option></select></label>
      <label>Expediente <select id="f-cruce"><option value="">Cualquiera</option></select></label>
      <label>Tipo <select id="f-clase"><option value="">Cualquiera</option></select></label>""",
    "metodo": _ES_METODO,
    "parametros": "Parámetros",
    "datos": """    <h3>Datos abiertos</h3>
    <p><a href="alertas.geojson">alertas.geojson</a> con todas las alertas y su historial · <a href="feed.xml">fuente Atom</a> de las activas · compuestos mensuales en GeoTIFF en las <a href="https://github.com/Asensio94/centinela-natura/releases/tag/compuestos">releases del repositorio</a> · <a href="https://github.com/Asensio94/centinela-natura">código</a>.</p>""",
    "principio": "Datos públicos, reglas a la vista y cada cifra enlazada a su fuente. Indicios, no veredictos.",
    "creditos": "Contiene datos modificados de Copernicus Sentinel procesados por Earth Search (Element 84) · Límites de la Red Natura 2000 y CORINE Land Cover 2018: Agencia Europea de Medio Ambiente · Municipios: © colaboradores de OpenStreetMap (ODbL) · Ortofoto PNOA: CC BY 4.0 scne.es · Parcelas: © Dirección General del Catastro · Expedientes: observatorio de alegaciones ambientales, a partir del BOE y el BOC · Código bajo licencia MIT.",
    "estados": {"provisional": "Provisional", "confirmada": "Confirmada", "revertida": "Revertida",
                "descartada": "Descartada", "fusionada": "Fusionada"},
    "cambio": "Cambio",
    "ndvi_de_a": "NDVI de {a} a {b}.",
    "parcelas_feed": " Parcelas: {lista}.",
    "en": "en",
    "parametros_filas": {
        "satelite": ("Satélite", "Sentinel-2 L2A (Copernicus), servido por Earth Search en AWS"),
        "resolucion": ("Resolución", "{r} m por píxel, malla fija en WGS84 / UTM 30N"),
        "validos": ("Píxeles válidos", "clases 4 a 7 de la capa SCL de Sen2Cor: vegetación, suelo, agua y sin clasificar"),
        "nieve": ("Nieve", "fuera si NDSI > {ndsi}, infrarrojo > {nir} y verde > {verde} (SNOMAP, Hall et al. 1995)"),
        "sombra": ("Sombra", "fuera si el infrarrojo cercano es < {nir}, salvo el agua"),
        "orillas": ("Orillas de embalse y marismas", "sin evaluar donde hubo agua un mes entero en los {meses} meses anteriores"),
        "compuesto": ("Compuesto mensual", "NDVI máximo de cada píxel en el mes"),
        "ventana": ("Ventana", "{v} meses, comparada con la misma ventana de los {a} años anteriores"),
        "referencia": ("Vegetación de referencia", "NDVI máximo ≥ {x} en todos los años de referencia"),
        "cambio": ("Cambio", "NDVI máximo actual ≤ {x} y caída ≥ {c}"),
        "obs": ("Observaciones mínimas", "{n} válidas por píxel en cada ventana"),
        "uma": ("Unidad mínima", "{n} píxeles contiguos ({ha} ha)"),
        "vuelta": ("Vuelta de la vegetación", "NDVI máximo medio ≥ {x} en el polígono"),
    },
    "js": {
        "locale": "es-ES",
        "osm": "Mapa (OpenStreetMap)",
        "natura": "Red Natura 2000",
        "en_estudio": "Cambio en estudio",
        "alt_antes": "Imagen de satélite antes del cambio, {f}",
        "alt_despues": "Imagen de satélite después del cambio, {f}",
        "antes": "Antes", "despues": "Después",
        "sin_fotos": "Las fotos se generan en la próxima pasada con cielo despejado.",
        "ha_de": "{a} ha de una parcela de {b}",
        "parc_pend": "Las parcelas catastrales se consultan en la próxima ejecución.",
        "parc_ninguna": "No cae en ninguna parcela del Catastro: dominio público o terreno sin catastrar.",
        "parc_titulo": "Parcelas catastrales",
        "parc_mas": "{n} parcelas más",
        "parc_menores": "Y {n} con menos superficie.",
        "parc_fuera": "El {n} % del cambio cae fuera de toda parcela: cauces, caminos, carreteras, costa o terreno sin catastrar.",
        "ctx_uno": " En {m} hay otro expediente que no identifica parcelas y no se puede cruzar.",
        "ctx_varios": " En {m} hay {n} expedientes más que no identifican parcelas y no se pueden cruzar.",
        "cita": "cita",
        "sin_cruce": "Ningún anuncio ni resolución leído por el <a href=\"{url}\">observatorio</a> cita estas parcelas.",
        "unidas": "Reúne {n} trozos del mismo cambio que se detectaron por separado ({ids}).",
        "ndvi": "NDVI antes → ahora",
        "ultima_veg": "Vegetación vista por última vez",
        "detectable": "Detectable desde", "primera": "Primera detección",
        "corine": "Uso anterior (CORINE 2018)",
        "ver_orto": "Ver en la ortofoto",
        "vacio": "No hay alertas con estos filtros.",
        "alerta": " alerta", "alertas": " alertas",
        "de": " de ",
    },
}

# ── Français ─────────────────────────────────────────────────────────────────────────────

_FR_METODO = """    <h2>Comment c’est calculé</h2>
    <ol>
      <li><strong>Zone.</strong> La zone surveillée réunit les __N_ESPACIOS__ sites Natura 2000 qui touchent les Pyrénées-Atlantiques, ZSC et ZPS ensemble, découpés à la limite du département~: __ZONA_HA__ hectares sur une grille fixe de 10 mètres.</li>
      <li><strong>Composite mensuel.</strong> Chaque jour, le mois en cours est recalculé avec tous les passages de Sentinel-2. Pour chaque pixel on garde le NDVI le plus élevé du mois, c’est-à-dire son moment le plus vert. Les nuages font baisser le NDVI~: le maximum les ignore. Une prairie fauchée repousse en quelques semaines~: le maximum de plusieurs mois la voit toujours verte. Seul un sol qui a perdu sa végétation pendant toute la fenêtre a un maximum bas.</li>
      <li><strong>Détection.</strong> La fenêtre actuelle est comparée à la même période des années précédentes. Un pixel change s’il était en végétation dense toutes ces années et ne l’est plus, même à son meilleur moment. Les pixels voisins forment un polygone, qui doit dépasser l’unité minimale.</li>
      <li><strong>Photos et type.</strong> Pour chaque nouvelle alerte, on cherche la scène dégagée la plus verte d’avant et la plus verte d’après, ce que compare le détecteur, et on publie les deux. Leurs bandes décident du type~: eau, brûlis, sol nu, surface sombre ou simple perte de végétation. Ce sont des règles à seuils publiés dans la littérature. Aucun modèle entraîné n’intervient, et chaque alerte peut être refaite à la main à partir des images.</li>
      <li><strong>Parcelles.</strong> Chaque alerte est superposée au plan cadastral informatisé (PCI vectoriel de la DGFiP, publié par Etalab, édition du __CATASTRO_FECHA__) pour savoir quelles parcelles elle touche. Le cadastre ouvert ne contient aucun propriétaire.</li>
      <li><strong>Usage agricole déclaré.</strong> L’alerte est superposée au Registre parcellaire graphique (RPG) de la dernière campagne PAC déclarée avant le changement. Si plus de la moitié de l’alerte tombe dans des parcelles déclarées, le changement est agricole~: «~terre en rotation~» quand la culture principale est une terre arable ou une prairie temporaire, ce qui peut être un labour normal~; «~sur prairie permanente déclarée~» quand c’est une prairie permanente ou une estive. Son retournement dans les sites Natura 2000 est encadré par la PAC (BCAE~9), mais une perte de végétation sur une prairie permanente peut aussi être un dessèchement d’été ou un écobuage~: l’alerte ne dit pas lequel, les images avant et après aident à trancher, et un dessèchement redevient vert à l’automne et l’alerte est alors écartée ou résorbée.</li>
      <li><strong>Croisement avec les autorisations d’urbanisme.</strong> Sitadel, le fichier des autorisations d’urbanisme du ministère (SDES), donne pour chaque permis de construire, déclaration préalable, permis d’aménager ou de démolir jusqu’à trois parcelles cadastrales. L’alerte a une autorisation connue si l’une d’elles est une de ses parcelles et qu’elle date des trois ans précédant la fenêtre ou d’après. Le fichier gardé couvre depuis le __EXPEDIENTES_DESDE__.</li>
    </ol>
    <p>«~Sans autorisation connue~» veut dire qu’aucune autorisation d’urbanisme de Sitadel ne cite ses parcelles, pas que les travaux sont illégaux~: beaucoup de travaux en zone naturelle ne relèvent pas de l’urbanisme (voir plus bas), Sitadel ne donne que trois parcelles par autorisation et presque jamais le préfixe de section. Le nombre d’autres autorisations dans la même commune sur la période est indiqué dans chaque alerte.</p>
    <h3>Équivalences avec l’Espagne</h3>
    <table class="params">
      <tr><th scope="row">Expedientes publiés au BOE et au BOC</th><td>Autorisations d’urbanisme de Sitadel, par parcelle</td></tr>
      <tr><th scope="row">Catastro (Sede Electrónica)</th><td>Cadastre Etalab (PCI vectoriel)</td></tr>
      <tr><th scope="row">Autorisations forestales</th><td>Autorisations de défrichement~: <strong>sans équivalent</strong>, aucun fichier ouvert par parcelle</td></tr>
      <tr><th scope="row">Évaluation des effets sur Natura 2000</th><td>Évaluations des incidences Natura 2000~: <strong>sans équivalent</strong>, les décisions ne sont pas publiées en données ouvertes</td></tr>
      <tr><th scope="row">Planes de gestión forestal</th><td>Plans simples de gestion~: <strong>sans équivalent</strong>, non publiés</td></tr>
      <tr><th scope="row">Evaluación de impacto ambiental</th><td>Projets soumis à étude d’impact (projets-environnement)~: <strong>sans équivalent</strong> exploitable, seule une archive de 2021 existe, sans API</td></tr>
      <tr><th scope="row">—</th><td>Usage agricole déclaré (RPG)~: <strong>propre à la France</strong></td></tr>
    </table>
    <h3>Ce qui reste hors champ, et pourquoi</h3>
    <p>Les installations classées (ICPE, Géorisques) ne sont pas croisées~: le fichier donne la raison sociale de l’exploitant, qui peut être le nom d’une personne, et ce site ne publie jamais de nom de personne physique. Les données de Sitadel sont lues sans le demandeur~: ni nom ou raison sociale, ni SIREN ou SIRET, ni adresse. Seuls le numéro de l’autorisation, son type, sa date, son état et ses parcelles sont gardés.</p>
    <h3>États</h3>
    <p>Les alertes marquées «~détectable depuis~» sont issues de la reconstruction des fenêtres antérieures à la mise en service, avec la date à laquelle elles auraient été vues.</p>
    <p><strong>Provisoire</strong>~: vue une fois. <strong>Confirmée</strong>~: toujours là dans la fenêtre d’un mois suivant. <strong>Écartée</strong>~: la végétation est revenue avant confirmation, elle n’a plus été revue, ou c’était la rive d’une retenue ou de l’eau nouvelle sur ce qui était déjà de l’eau (variations de niveau). <strong>Résorbée</strong>~: la végétation est revenue ensuite. <strong>Fusionnée</strong>~: c’était un morceau d’une autre alerte~; son lien mène à l’alerte qui l’a absorbée.</p>
    <h3>Validation</h3>
    <p>En attente~: pas encore confrontée à une autre source. Chaque alerte publie les deux images que compare le détecteur, pour qu’on puisse vérifier à l’œil nu.</p>
    <h3>Limites</h3>
    <p>Rien de plus petit que l’unité minimale~: une maison isolée, une piste étroite ou une clôture. Rien sous un couvert arboré qu’on n’enlève pas, ni dans des zones qui n’étaient pas en végétation dense (rochers, sables, plans d’eau), ni sur les rives que l’eau couvre et découvre, ni pendant les mois de neige, d’ombre hivernale ou de nuage persistant, qui restent non évalués. Le RPG ne couvre que les exploitants qui demandent des aides PAC. Dans les estives et les communaux de montagne, une seule parcelle peut faire des centaines d’hectares~: tomber dans la même parcelle qu’une autorisation ne prouve pas qu’il s’agit des mêmes travaux.</p>"""

FR = _fr({
    "html_lang": "fr",
    "description": "Changements physiques du terrain dans le réseau Natura 2000 des Pyrénées-Atlantiques, détectés avec Sentinel-2 et croisés avec le cadastre, la PAC et les autorisations d’urbanisme.",
    "feed_alt": "Alertes de Centinela Natura",
    "feed_title": "Centinela Natura~: alertes dans le réseau Natura 2000 des {region}",
    "label": "Natura 2000 · Pyrénées-Atlantiques · Sentinel-2",
    "lede": "Changements physiques du terrain dans les sites protégés~: travaux, terrassements, retenues, coupes ou brûlis. Ils sont détectés chaque jour sur les images satellite avec des règles fixes, puis croisés avec le cadastre, les déclarations PAC et les autorisations d’urbanisme.",
    "fig_activas": "alertes actives",
    "fig_confirmadas": "confirmées",
    "fig_ha": "hectares touchés",
    "fig_expediente": "avec une autorisation d’urbanisme sur leurs parcelles",
    "fig_meta": "fenêtre comparée · __EVALUABLE__ de la zone avec un ciel suffisant · mis à jour le __ACTUALIZADO__",
    "mapa_aria": "Carte des alertes",
    "filtros": """      <label>État <select id="f-estado">
        <option value="activas">Actives</option><option value="confirmada">Confirmées</option>
        <option value="provisional">Provisoires</option><option value="cerradas">Résorbées et écartées</option>
        <option value="todas">Toutes</option></select></label>
      <label>Autorisation <select id="f-cruce"><option value="">Toutes</option></select></label>
      <label>Type <select id="f-clase"><option value="">Tous</option></select></label>
      <label>Usage déclaré <select id="f-uso"><option value="">Tous</option></select></label>""",
    "metodo": _FR_METODO,
    "parametros": "Paramètres",
    "datos": """    <h3>Données ouvertes</h3>
    <p><a href="alertas.geojson">alertas.geojson</a> avec toutes les alertes et leur historique · <a href="feed.xml">flux Atom</a> des alertes actives · <a href="sitadel_parcelles.json">autorisations d’urbanisme</a> utilisées pour le croisement, sans demandeur · composites mensuels en GeoTIFF dans les <a href="https://github.com/Asensio94/centinela-natura/releases/tag/compuestos">releases du dépôt</a> · <a href="https://github.com/Asensio94/centinela-natura">code</a>.</p>
    <h3>Sources</h3>
    <p>Images~: <a href="https://dataspace.copernicus.eu/">Copernicus Sentinel-2</a> via <a href="https://element84.com/earth-search/">Earth Search</a> · Sites Natura 2000 et CORINE Land Cover~: <a href="https://www.eea.europa.eu/">Agence européenne pour l’environnement</a> · Communes~: <a href="https://geo.api.gouv.fr/decoupage-administratif">API Découpage administratif</a> · Parcelles~: <a href="https://cadastre.data.gouv.fr/">cadastre Etalab</a> (PCI vectoriel, DGFiP) · Usage agricole~: <a href="https://geoservices.ign.fr/rpg">Registre parcellaire graphique</a> (ASP, IGN) · Autorisations~: <a href="https://www.statistiques.developpement-durable.gouv.fr/donnees-des-permis-de-construire-et-autres-autorisations-durbanisme">Sitadel</a> (SDES) · Orthophotos~: <a href="https://geoservices.ign.fr/bdortho">IGN</a>.</p>""",
    "principio": "Données publiques, règles visibles et chaque chiffre relié à sa source. Des indices, pas des verdicts.",
    "creditos": "Contient des données Copernicus Sentinel modifiées, traitées par Earth Search (Element 84) · Sites Natura 2000 et CORINE Land Cover 2018~: Agence européenne pour l’environnement · Communes, orthophotos et RPG~: IGN, Licence Ouverte 2.0 · Parcelles~: DGFiP, cadastre Etalab, Licence Ouverte 2.0 · Autorisations d’urbanisme~: SDES, Sitadel, Licence Ouverte 2.0 · Code sous licence MIT.",
    "estados": {"provisional": "Provisoire", "confirmada": "Confirmée", "revertida": "Résorbée",
                "descartada": "Écartée", "fusionada": "Fusionnée"},
    "cambio": "Changement",
    "ndvi_de_a": "NDVI de {a} à {b}.",
    "parcelas_feed": " Parcelles~: {lista}.",
    "en": "dans",
    "parametros_filas": {
        "satelite": ("Satellite", "Sentinel-2 L2A (Copernicus), servi par Earth Search sur AWS"),
        "resolucion": ("Résolution", "{r} m par pixel, grille fixe en WGS84 / UTM 30N"),
        "validos": ("Pixels valides", "classes 4 à 7 de la couche SCL de Sen2Cor~: végétation, sol, eau et non classé"),
        "nieve": ("Neige", "exclue si NDSI > {ndsi}, proche infrarouge > {nir} et vert > {verde} (SNOMAP, Hall et al. 1995)"),
        "sombra": ("Ombre", "exclue si le proche infrarouge est < {nir}, sauf l’eau"),
        "orillas": ("Rives de retenues et marais", "non évaluées là où il y a eu de l’eau un mois entier dans les {meses} mois précédents"),
        "compuesto": ("Composite mensuel", "NDVI maximal de chaque pixel dans le mois"),
        "ventana": ("Fenêtre", "{v} mois, comparée à la même fenêtre des {a} années précédentes"),
        "referencia": ("Végétation de référence", "NDVI maximal ≥ {x} toutes les années de référence"),
        "cambio": ("Changement", "NDVI maximal actuel ≤ {x} et baisse ≥ {c}"),
        "obs": ("Observations minimales", "{n} valides par pixel dans chaque fenêtre"),
        "uma": ("Unité minimale", "{n} pixels contigus ({ha} ha)"),
        "vuelta": ("Retour de la végétation", "NDVI maximal moyen ≥ {x} dans le polygone"),
        "rpg": ("Usage agricole", "plus de la moitié de l’alerte dans des parcelles du RPG de la dernière campagne avant le changement"),
        "sitadel": ("Autorisation connue", "une parcelle citée par Sitadel, autorisée au plus {meses} mois avant la fenêtre, non annulée"),
    },
    "js": {
        "locale": "fr-FR",
        "osm": "Carte (OpenStreetMap)",
        "natura": "Réseau Natura 2000",
        "en_estudio": "Changement à l’étude",
        "alt_antes": "Image satellite avant le changement, {f}",
        "alt_despues": "Image satellite après le changement, {f}",
        "antes": "Avant", "despues": "Après",
        "sin_fotos": "Les images seront générées au prochain passage par ciel dégagé.",
        "ha_de": "{a} ha d’une parcelle de {b}",
        "parc_pend": "Les parcelles cadastrales seront consultées à la prochaine exécution.",
        "parc_ninguna": "Ne tombe dans aucune parcelle cadastrée~: domaine public non cadastré (cours d’eau, routes, chemins, rivage).",
        "parc_titulo": "Parcelles cadastrales",
        "parc_mas": "{n} parcelles de plus",
        "parc_menores": "Et {n} avec une surface moindre.",
        "parc_fuera": "{n}~% du changement tombe hors de toute parcelle~: cours d’eau, chemins, routes, rivage ou domaine public non cadastré.",
        "ctx_uno": " À {m}, une autre autorisation d’urbanisme de la période ne cite pas ces parcelles.",
        "ctx_varios": " À {m}, {n} autres autorisations d’urbanisme de la période ne citent pas ces parcelles.",
        "cita": "cite",
        "sin_cruce": "Aucune autorisation d’urbanisme de <a href=\"{url}\">Sitadel</a> ne cite ces parcelles.",
        "unidas": "Réunit {n} morceaux du même changement détectés séparément ({ids}).",
        "ndvi": "NDVI avant → maintenant",
        "ultima_veg": "Végétation vue pour la dernière fois",
        "detectable": "Détectable depuis", "primera": "Première détection",
        "corine": "Occupation antérieure (CORINE 2018)",
        "ver_orto": "Voir sur l’orthophoto",
        "vacio": "Aucune alerte avec ces filtres.",
        "alerta": " alerte", "alertas": " alertes",
        "de": " ",
        "notas": {"sin escena despejada para las fotos": "pas de scène dégagée pour les images"},
        "section": "section {s}, n°~{n}",
        "prefixe": " (préfixe {p})",
        "uso_titulo": "Usage déclaré (RPG {a})",
        "uso_sin": "Pas de parcelle déclarée à la PAC sous l’alerte.",
        "uso_frac": "{n}~% de l’alerte dans des parcelles déclarées",
        "uso_nota_pp": "Prairie permanente~: son retournement dans un site Natura 2000 est encadré par la PAC (BCAE~9). Le changement peut aussi être un dessèchement d’été ou un écobuage~; comparez les images.",
        "uso_nota_rot": "Terre en rotation~: le changement peut être un labour normal.",
        "etat": {"2": "autorisée", "4": "annulée", "5": "travaux commencés", "6": "travaux terminés"},
        "dest": {"1": "habitation", "2": "hôtel", "3": "bureaux", "4": "commerce", "6": "industrie",
                 "7": "agriculture", "8": "entrepôt", "9": "service public"},
        "tipo_dau": {"PC": "Permis de construire", "DP": "Déclaration préalable",
                     "PA": "Permis d’aménager", "PD": "Permis de démolir"},
    },
})

UI = {"es": ES, "fr": FR}

# Nombres de lo que la web pinta a partir de claves de los datos.
CRUCES = {
    "es": {"resolucion": "Resolución favorable en la parcela",
           "tramitacion": "Expediente en tramitación en la parcela",
           "sin_expediente": "Sin expediente conocido", "pendiente": "Parcelas por consultar"},
    "fr": _fr({"resolucion": "Autorisation d’urbanisme connue", "sin_expediente": "Sans autorisation connue",
               "pendiente": "Parcelles à consulter"}),
}
CLASES = {
    "fr": {"agua": "Nouveau plan d’eau", "quemado": "Surface brûlée",
           "suelo": "Sol nu ou terrassement", "oscuro": "Surface artificielle sombre",
           "vegetacion": "Perte de végétation"},
}
USOS = {
    "fr": {"rotacion": "Agricole (rotation)", "pradera_permanente": "Sur prairie permanente déclarée",
           "sin_declarar": "Hors RPG"},
}
CLC = {
    "fr": {
        "111": "tissu urbain continu", "112": "tissu urbain discontinu",
        "121": "zone industrielle ou commerciale", "122": "réseau routier ou ferroviaire",
        "123": "zone portuaire", "124": "aéroport", "131": "extraction de matériaux",
        "132": "décharge", "133": "chantier", "141": "espace vert urbain",
        "142": "équipement sportif et de loisirs", "211": "terre arable hors irrigation",
        "212": "périmètre irrigué", "221": "vignoble", "222": "verger",
        "231": "prairies", "242": "systèmes culturaux complexes",
        "243": "agriculture avec espaces naturels", "311": "forêt de feuillus",
        "312": "forêt de conifères", "313": "forêt mélangée", "321": "pelouses et pâturages naturels",
        "322": "landes et broussailles", "323": "végétation sclérophylle",
        "324": "forêt et végétation arbustive en mutation", "331": "plages, dunes et sable",
        "332": "roches nues", "333": "végétation clairsemée", "334": "zone incendiée",
        "411": "marais intérieur", "421": "marais maritime", "423": "zone intertidale",
        "511": "cours d’eau", "512": "plan d’eau", "521": "lagune littorale", "522": "estuaire",
    },
}
