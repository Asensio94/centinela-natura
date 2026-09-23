"""Parámetros del centinela. Cada umbral lleva al lado la razón por la que vale lo que vale.

Todo el sistema es determinista: índices espectrales clásicos, compuestos de máximo y
reglas con umbral. No hay ningún modelo entrenado ni ningún modelo de lenguaje, así que
cada alerta se puede reproducir y explicar a mano a partir de las imágenes.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ZONAS_DIR = DATA_DIR / "zonas"
COMPUESTOS_DIR = DATA_DIR / "compuestos"   # caché local; la copia buena vive en la release
CHIPS_DIR = DATA_DIR / "chips"
CACHE_DIR = DATA_DIR / "cache"
SITE_DIR = ROOT / "site"
ALERTAS_JSON = DATA_DIR / "alertas.json"

for _d in (ZONAS_DIR, COMPUESTOS_DIR, CHIPS_DIR, CACHE_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# --- Ámbito -----------------------------------------------------------------------
# Empieza por Cantabria porque es donde el observatorio de alegaciones lee también el
# boletín autonómico, y el cruce con expedientes es la mitad del valor del centinela.
REGION = "Cantabria"
REGION_QUERY = "Cantabria, España"
# Los espacios con código ES13 son los de Cantabria (el prefijo es su código NUTS 2);
# los ES0000 son ZEPA o espacios compartidos que también la tocan. Todos se recortan
# después con el límite de la comunidad.
NATURA_CODIGOS_LIKE = "ES13%"
NATURA_CODIGOS_EXTRA = (
    "ES0000003", "ES0000143", "ES0000198", "ES0000248", "ES0000249",
    "ES0000250", "ES0000251", "ES0000252", "ES0000253",
)
# La EEA sirve las ZEC y las ZEPA en capas distintas: la 0 son los espacios de la
# Directiva Hábitats y la 1 los de la Directiva Aves. Pidiendo solo la 0 se pierden
# todas las ZEPA que no coinciden con una ZEC, que en Cantabria son ocho.
NATURA_URL = (
    "https://bio.discomap.eea.europa.eu/arcgis/rest/services/"
    "ProtectedSites/Natura2000Sites/MapServer/{capa}/query"
)
NATURA_CAPAS = (0, 1)

# --- Satélite -----------------------------------------------------------------------
STAC_URL = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTION = "sentinel-2-l2a"
# WGS84 / UTM 30N, el sistema de las propias teselas de Sentinel-2 que cubren Cantabria.
# Con la malla anclada a múltiplos de 10 m en este sistema, cada píxel del compuesto es un
# píxel original de la escena, sin remuestrear. Frente al ETRS89 / UTM 30N oficial
# (EPSG:25830) la diferencia es inferior a un metro, muy por debajo del píxel.
CRS = "EPSG:32630"
RESOLUCION_M = 10           # la nativa del rojo y del infrarrojo cercano
PIXEL_HA = RESOLUCION_M ** 2 / 10_000
# Una escena casi entera de nube no aporta nada al compuesto y cuesta lo mismo de bajar.
NUBOSIDAD_ESCENA_MAX = 90.0
DASK_HILOS = 8
# Clases de la capa SCL de Sen2Cor que se aceptan: vegetación, suelo, agua y sin
# clasificar. Fuera quedan nube, sombra de nube, cirro, saturación y nieve, y también
# la clase 2 (zonas oscuras), que en invierno son las laderas norte en sombra
# topográfica: su NDVI no es fiable. Sen2Cor clasifica con umbrales físicos, no con un
# modelo entrenado.
SCL_VALIDAS = (4, 5, 6, 7)
SCL_AGUA = 6
# La SCL deja pasar nieve y sombra de relieve en invierno, así que cada observación pasa
# además dos pruebas. Nieve: la de SNOMAP (Hall et al. 1995), NDSI alto con verde e
# infrarrojo cercano claros. Señal: por debajo de este infrarrojo cercano el NDVI es el
# cociente de dos números casi nulos (sombra de ladera) y vale cualquier cosa; el agua,
# que es oscura de verdad, se acepta aparte para que una balsa nueva se vea.
NIEVE_NDSI_MIN = 0.4
NIEVE_NIR_MIN = 0.11
NIEVE_VERDE_MIN = 0.10
NIR_SENAL_MIN = 0.04

# --- Compuestos mensuales ------------------------------------------------------------
# Cada mes se guarda el NDVI máximo de cada píxel (compuesto de valor máximo, Holben
# 1986). El máximo es la pieza que hace funcionar todo lo demás: una nube baja el NDVI,
# así que el máximo la ignora sola, y un prado segado vuelve a crecer en pocas semanas,
# así que el máximo de tres meses lo ve verde. Solo un suelo que ha dejado de tener
# vegetación durante toda la ventana tiene el máximo bajo.
#
# Se guarda en un byte: NDVI = valor / 100 - 1, de 0 (NDVI -1) a 200 (NDVI +1), con 255
# como vacío. La centésima de NDVI sobra para umbrales separados por décimas, y a la
# mitad de tamaño los compuestos caben holgados en una release.
NDVI_NODATA = 255
RELEASE_TAG = "compuestos"

# --- Detección -----------------------------------------------------------------------
VENTANA_MESES = 3           # la ventana actual y las de referencia abarcan tres meses
ANIOS_REFERENCIA = 2        # se compara con la misma ventana de los dos años anteriores
# El píxel tiene que haber sido vegetación en los dos años de referencia. Con dos años y
# no uno, un campo que ya estaba labrado el año pasado no cuenta como cambio nuevo.
NDVI_REF_MIN = 0.60
# Y ahora, en el mejor momento de tres meses, no llega ni a vegetación rala.
NDVI_ACTUAL_MAX = 0.35
CAIDA_MIN = 0.30            # entre la referencia más baja y lo actual
OBS_MIN = 3                 # observaciones válidas mínimas en cada ventana
# Unidad mínima: 20 píxeles de 10 m, 0,2 ha. Una vivienda aislada no se ve; una obra con
# su explanación, una pista ancha, una cantera o una balsa sí.
UMA_PIXELES = 20
# Orillas de embalse y marismas: un píxel que ha estado cubierto de agua un mes entero
# (NDVI máximo del mes por debajo de 0) en este número de meses antes de la ventana
# alterna agua y pasto con el nivel, y no se evalúa. Una balsa nueva sí se ve, porque su
# agua cae dentro de la ventana, no antes.
AGUA_MESES_ATRAS = 24
# El mes anterior se vuelve a calcular durante los primeros días del siguiente, para que
# entren las escenas que Earth Search publica con retraso.
DIAS_CIERRE_MES = 6
