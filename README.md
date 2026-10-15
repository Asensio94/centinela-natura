# Centinela Natura

Vigilancia diaria de cambios físicos del terreno dentro de la Red Natura 2000 de Cantabria
con imágenes Sentinel-2: obras, explanaciones, pistas anchas, balsas, cortas y quemas. Cada
cambio se cruza con los expedientes publicados en el BOE y el Boletín Oficial de Cantabria
que recoge el [observatorio de alegaciones](https://github.com/Asensio94/observatorio-alegaciones),
y se marca con resolución favorable, en tramitación o **sin expediente conocido**.

**Web:** https://asensio94.github.io/centinela-natura/ · **Fuente Atom:**
https://asensio94.github.io/centinela-natura/feed.xml

También vigila Francia, empezando por los Pirineos Atlánticos, con el mismo detector y su
propia página en francés: https://asensio94.github.io/centinela-natura/fr/ (ver
[Francia](#francia)).

Todo es determinista: índices espectrales clásicos, compuestos de máximo y reglas con
umbral. No hay ningún modelo entrenado ni de lenguaje en la cadena, así que cada alerta se
puede rehacer y explicar a mano desde las imágenes.

## Cómo funciona

1. **Zona.** Los 30 espacios Natura 2000 que tocan Cantabria (ZEC de la capa 0 y ZEPA de la
   capa 1 del servicio de la EEA), unidos y recortados al límite de la comunidad: unas
   147.000 ha. Se rasterizan sobre una malla fija de 10 m en WGS84 / UTM 30N, alineada con
   la de las teselas de Sentinel-2, para que cada píxel sea un píxel original de la escena.
2. **Compuesto mensual.** Con todas las pasadas del mes se guarda, para cada píxel, el NDVI
   máximo sobre observaciones válidas y cuántas hubo. Válida es una observación de
   vegetación, suelo, agua o sin clasificar según la capa SCL que además no sea nieve
   (prueba SNOMAP de Hall et al. 1995, que la SCL deja pasar) ni sombra de relieve
   (infrarrojo cercano casi nulo). Las escenas que Earth Search publica sin restar el
   desplazamiento de -1000 de la baseline 04.00 (las primeras de Sentinel-2C) se
   corrigen al leerlas. Las nubes bajan el NDVI y el máximo las ignora; un prado
   segado rebrota en semanas y el máximo de varios meses lo ve verde. Los compuestos
   (GeoTIFF de dos bandas en un byte) se guardan como ficheros de la release
   [`compuestos`](https://github.com/Asensio94/centinela-natura/releases/tag/compuestos).
3. **Detección.** El máximo de la ventana actual (varios meses) se compara con el de la
   misma ventana en los dos años anteriores. Un píxel es cambio si fue vegetación densa
   todos los años de referencia y ahora, en su mejor momento, no lo es. Los píxeles
   contiguos forman un polígono que tiene que superar la unidad mínima. No se evalúan los
   píxeles que estuvieron cubiertos de agua un mes entero en los dos años anteriores: son
   orillas de embalse y marismas, que alternan agua y pasto con el nivel. Los umbrales están
   en [`centinela/config.py`](centinela/config.py) con su justificación.
4. **Análisis.** Para cada alerta nueva se busca la escena despejada más verde del año
   anterior y la más verde de la ventana actual (su mejor momento, que es lo que compara
   el detector); si la nieve o las nubes no dejan ninguna escena en esa ventana, se usa la
   última en que se ha vuelto a ver. Se publican las dos fotos y se clasifica por
   reglas: agua nueva (MNDWI), quemado (caída de NBR > 0,27, Key y Benson 2006, con el
   infrarrojo hundido y el visible oscuro, que lo separan del suelo removido), suelo
   desnudo (BSI), superficie artificial oscura o pérdida de vegetación. El uso anterior se
   toma de CORINE 2018.
5. **Ciclo de vida.** Provisional → confirmada si sigue en la ventana de un mes posterior.
   Si la vegetación vuelve, descartada (antes de confirmar) o revertida (después). Una
   provisional que no se vuelve a ver hasta la primera ventana que no se solapa con la
   suya también se descarta, igual que cualquier cambio en lo que CORINE cartografía como embalse o lago y el agua
   nueva sobre marismas y estuarios: es el nivel, que sube y baja. Nada se
   borra: `data/alertas.json` es un registro acumulativo con su historial.
   Cuando la nieve o las nubes dejan parte de un cambio sin evaluar, sale en trozos que
   luego crecen hasta tocarse: dos alertas a menos de 15 m nacidas en ventanas que se
   solapan se unen en la más antigua, y las otras quedan como `fusionada`, con
   `fusionada_en`. La unida rehace fotos, clase y parcelas.
6. **Parcelas.** Cada alerta se superpone a la cartografía catastral: de ahí salen las
   parcelas que toca, cuánto ocupa en cada una y qué parte cae fuera de toda parcela
   (cauces, caminos, costa). Se usa la descarga INSPIRE por municipio del Catastro y no su
   WFS, que limita cada consulta a un kilómetro cuadrado y corta la conexión desde Actions.
   INSPIRE no trae titulares ni ningún dato personal.
7. **Cruce.** De los anuncios y resoluciones de Cantabria del observatorio se sacan las
   parcelas que citan, con expresiones fijas: referencias catastrales de 14 o 20
   caracteres y pares «polígono X, parcela Y» del municipio del expediente. Quedan en
   [`data/expedientes_parcelas.json`](data/expedientes_parcelas.json), que se puede
   revisar a mano. Una alerta tiene expediente si alguno cita una de sus parcelas;
   si es una resolución favorable, se marca como tal. Los expedientes del municipio que
   no identifican parcelas se cuentan aparte, porque no se pueden cruzar.

### Francia

Francia es un segundo país del mismo centinela, no un proyecto aparte: el detector, los
umbrales y el ciclo de vida son los mismos, y cada proceso vigila un país
(`python -m centinela --pais FR …`). Lo que cambia son las fuentes de los pasos 6 y 7 y
una capa más:

1. **Zona.** Los 51 espacios Natura 2000 que tocan los Pirineos Atlánticos (64), recortados
   al departamento: unas 231.500 ha, en el mismo huso UTM 30N que Cantabria, así que la
   malla es la misma. Los compuestos van en la misma release con el prefijo `FR64_` y las
   alertas se numeran `CF-AAAAMM-NNN`.
2. **Parcelas.** El plan catastral informatizado (PCI vectoriel de la DGFiP) que publica
   Etalab, por commune. Como el español, no trae propietarios.
3. **Uso declarado.** El [Registre parcellaire graphique](https://geoservices.ign.fr/rpg)
   (RPG) del IGN: las parcelas que los agricultores declaran a la PAC, anonimizadas. Se
   lee el cultivo declarado el año anterior al cambio: si era pradera permanente (grupos
   17 y 18), la alerta se marca «retournement de prairie permanente», que en Natura 2000 la
   PAC restringe (BCAE 9); si era otro cultivo, «agricole (rotation)», la rotación normal
   de una explotación que en España podía parecer un cambio. No se guarda el identificador
   de la parcela PAC.
4. **Cruce.** [Sitadel](https://www.statistiques.developpement-durable.gouv.fr/donnees-des-permis-de-construire-et-autres-autorisations-durbanisme)
   (SDES): los permis de construire, d'aménager y de démolir y las déclarations préalables
   autorizadas desde 2018 en las 428 communes vigiladas, cada una con hasta tres parcelas
   catastrales. Una alerta tiene «autorisation d'urbanisme connue» si una autorización de
   los 36 meses anteriores (o posterior) cita una de sus parcelas. Del fichero solo se
   guarda número, tipo, fecha, estado, destino y parcelas en
   [`data/fr/sitadel_parcelles.json`](data/fr/sitadel_parcelles.json): nunca el
   solicitante (nombre o razón social, SIREN, dirección).

Lo que en España cruza el observatorio y en Francia **no tiene equivalente** abierto y
legible por parcela: autorizaciones de desbroce (défrichement), evaluaciones de
incidencias Natura 2000 y planes simples de gestión forestal. Las instalaciones
clasificadas (ICPE) quedan fuera a propósito, porque su razón social puede ser el nombre de
una persona. La web francesa lo explica todo en su «Comment c'est calculé».

## Contraste / validación

Pendiente: todavía no se ha contrastado con otra fuente. Cada alerta publica las dos fotos
que compara el detector, para que se pueda comprobar a simple vista.

## Límites

Nada por debajo de la unidad mínima (una vivienda aislada, una pista estrecha), nada bajo
cubierta arbórea que no se quite, ningún cambio en lo que no era vegetación densa (roquedo,
arenal, agua), ninguna orilla que el agua cubra y descubra, y ningún píxel sin
observaciones suficientes (nieve, sombra invernal en laderas norte, nube persistente). En
tierras de cultivo, una rotación puede parecer un cambio.

En el cruce, una parcela de monte puede tener cientos de hectáreas: coincidir en ella no
prueba que sea la misma obra. Y «sin expediente conocido» no prueba que falte el permiso:
muchas licencias municipales y autorizaciones forestales no se publican, parte de los
anuncios solo dan el municipio, y el observatorio lee Cantabria desde julio de 2026.

En Francia, Sitadel solo trae autorizaciones concedidas (no las denegadas ni las obras sin
permiso) y como mucho tres parcelas por autorización, y el RPG solo cubre a quien pide
ayudas de la PAC: fuera del RPG no quiere decir que no sea agrícola.

## Uso

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m centinela compuesto 2026-08          # un mes, en data/compuestos
python -m centinela detectar 2026-08           # baja de la release lo que falte y detecta
python -m centinela parcelas                   # parcelas catastrales y cruce
python -m centinela publicar                   # web en site/
python -m centinela --pais FR publicar         # lo mismo en Francia: datos en data/fr, web en site/fr
python -m pytest                               # pruebas
```

### Automatización

- [`diario.yml`](.github/workflows/diario.yml): cada día rehace el mes en curso (y el
  anterior los primeros días), detecta, analiza, cruza, guarda el registro en `main` y
  publica la web en `gh-pages`.
- [`compuestos.yml`](.github/workflows/compuestos.yml): a mano, construye en paralelo los
  compuestos de un periodo (arranque o recálculo del histórico).

Coste cero: GitHub Actions y Pages en un repositorio público, Sentinel-2 del programa de
datos abiertos de AWS sin clave.

## Datos que se guardan

| Fichero | Contenido |
|---|---|
| `data/alertas.json` | Registro acumulativo de alertas, cada una con su historial de estados, y las ejecuciones de cada ventana. Nada se borra. |
| `data/expedientes_parcelas.json` | Parcelas que cita cada anuncio o resolución del observatorio, revisables a mano. |
| `data/fr/` | Lo mismo para Francia, más `sitadel_parcelles.json`: las autorizaciones de urbanismo de Sitadel reducidas a número, tipo, fecha, estado, destino y parcelas, sin solicitante. |
| `data/chips/` | Fotos de antes y después de cada alerta (JPG). |
| `data/zonas/` | Límites de los espacios Natura 2000 (`espacios.geojson`), de la comunidad (`region.geojson`) y de los municipios (`municipios.geojson`). |
| `data/compuestos/` | Caché local de los compuestos mensuales; no se versiona, la copia buena está en la release `compuestos`. |
| `data/cache/` | Caché local de descargas del Catastro y del observatorio; no se versiona. |
| `site/` | La web generada (`index.html`, `alertas.geojson`, `feed.xml`, `espacios.geojson` y las fotos); no se versiona en `main`, se publica en `gh-pages`. También `signals.json`: las alertas activas en el formato común de los proyectos hermanos, el que lee [Estado de las IBA](https://github.com/Asensio94/estado-iba), con las de los dos países: cada señal dice su `country` y las francesas llevan el código INSEE de su commune. |

## Fuentes y licencias

Contiene datos modificados de Copernicus Sentinel, servidos por Earth Search (Element 84).
Red Natura 2000 y CORINE Land Cover 2018: Agencia Europea de Medio Ambiente. Municipios y
límite regional: © colaboradores de OpenStreetMap, ODbL. Parcelas: © Dirección General
del Catastro, servicio de descargas INSPIRE. Ortofoto PNOA en la web:
CC BY 4.0 scne.es. En Francia: communes, ortofotos y RPG del IGN; parcelas de la DGFiP
(cadastre Etalab); autorizaciones de urbanismo de Sitadel (SDES), todo bajo Licence
Ouverte 2.0. Código bajo licencia MIT.

Forma parte de un conjunto de proyectos hermanos: [Observatorio de alegaciones](https://asensio94.github.io/observatorio-alegaciones/) · [Vigía de incendios](https://asensio94.github.io/vigia-incendios/) · [Vigilancia de humedales](https://asensio94.github.io/vigilancia-humedales/) · [Sub Nocte](https://asensio94.github.io/sub-nocte/) · [Riesgo de tendidos para aves](https://asensio94.github.io/riesgo-tendidos-aves/) · [Grafo de promotores](https://asensio94.github.io/grafo-promotores/) · [Cartera de las cotizadas](https://asensio94.github.io/cartera-cotizadas/) · [Cuaderno de campo](https://asensio94.github.io/cuaderno-campo/) · [Caudal ecológico](https://asensio94.github.io/caudal-ecologico/) · [Estado de las IBA](https://asensio94.github.io/estado-iba/).
