# Centinela Natura

Vigilancia diaria de cambios físicos del terreno dentro de la Red Natura 2000 de Cantabria
con imágenes Sentinel-2: obras, explanaciones, pistas anchas, balsas, cortas y quemas. Cada
cambio se cruza con los expedientes publicados en el BOE y el Boletín Oficial de Cantabria
que recoge el [observatorio de alegaciones](https://github.com/Asensio94/observatorio-alegaciones),
y se marca con resolución favorable, en tramitación o **sin expediente conocido**.

**Web:** https://asensio94.github.io/centinela-natura/ · **Fuente Atom:**
https://asensio94.github.io/centinela-natura/feed.xml

Todo es determinista: índices espectrales clásicos, compuestos de máximo y reglas con
umbral. No hay ningún modelo entrenado ni de lenguaje en la cadena, así que cada alerta se
puede rehacer y explicar a mano desde las imágenes.

## Cómo funciona

1. **Zona.** Los 30 espacios Natura 2000 que tocan Cantabria (ZEC de la capa 0 y ZEPA de la
   capa 1 del servicio de la EEA), unidos y recortados al límite de la comunidad: unas
   147.000 ha. Se rasterizan sobre una malla fija de 10 m en WGS84 / UTM 30N, alineada con
   la de las teselas de Sentinel-2, para que cada píxel sea un píxel original de la escena.
2. **Compuesto mensual.** Con todas las pasadas del mes se guarda, para cada píxel, el NDVI
   máximo sobre observaciones válidas según la capa SCL (vegetación, suelo, agua y sin
   clasificar) y cuántas hubo. Las nubes bajan el NDVI y el máximo las ignora; un prado
   segado rebrota en semanas y el máximo de varios meses lo ve verde. Los compuestos
   (GeoTIFF de dos bandas en un byte) se guardan como ficheros de la release
   [`compuestos`](https://github.com/Asensio94/centinela-natura/releases/tag/compuestos).
3. **Detección.** El máximo de la ventana actual (varios meses) se compara con el de la
   misma ventana en los dos años anteriores. Un píxel es cambio si fue vegetación densa
   todos los años de referencia y ahora, en su mejor momento, no lo es. Los píxeles
   contiguos forman un polígono que tiene que superar la unidad mínima. Los umbrales están
   en [`centinela/config.py`](centinela/config.py) con su justificación.
4. **Análisis.** Para cada alerta nueva se busca la escena más limpia de antes y de después,
   se publican las dos fotos y se clasifica por reglas: agua nueva (MNDWI), quemado (caída
   de NBR > 0,27, Key y Benson 2006), suelo desnudo (BSI), superficie artificial oscura o
   pérdida de vegetación. El uso anterior se toma de CORINE 2018.
5. **Ciclo de vida.** Provisional → confirmada si sigue en la ventana de un mes posterior.
   Si la vegetación vuelve, descartada (antes de confirmar) o revertida (después). Nada se
   borra: `data/alertas.json` es un registro acumulativo con su historial.
6. **Cruce.** El municipio (límites de OpenStreetMap) se busca entre los anuncios y
   resoluciones de Cantabria del observatorio. Coincidir en municipio no prueba que sea la
   misma obra, y no constar en los boletines no prueba que no tenga permiso: muchas
   licencias municipales y autorizaciones forestales no se publican.

## Qué no ve

Nada por debajo de la unidad mínima (una vivienda aislada, una pista estrecha), nada bajo
cubierta arbórea que no se quite, ningún cambio en lo que no era vegetación densa (roquedo,
arenal, agua) y ningún píxel sin observaciones suficientes (nieve, nube persistente). En
tierras de cultivo, una rotación puede parecer un cambio.

## Automatización

- [`diario.yml`](.github/workflows/diario.yml): cada día rehace el mes en curso (y el
  anterior los primeros días), detecta, analiza, cruza, guarda el registro en `main` y
  publica la web en `gh-pages`.
- [`compuestos.yml`](.github/workflows/compuestos.yml): a mano, construye en paralelo los
  compuestos de un periodo (arranque o recálculo del histórico).

Coste cero: GitHub Actions y Pages en un repositorio público, Sentinel-2 del programa de
datos abiertos de AWS sin clave.

## Uso local

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
python -m centinela compuesto 2026-08          # un mes, en data/compuestos
python -m centinela detectar 2026-08           # baja de la release lo que falte y detecta
python -m centinela publicar                   # web en site/
```

## Fuentes y licencias

Contiene datos modificados de Copernicus Sentinel, servidos por Earth Search (Element 84).
Red Natura 2000 y CORINE Land Cover 2018: Agencia Europea de Medio Ambiente. Municipios y
límite regional: © colaboradores de OpenStreetMap, ODbL. Ortofoto PNOA en la web:
CC BY 4.0 scne.es. Código bajo licencia MIT.
