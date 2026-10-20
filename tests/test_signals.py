"""signals.json for Estado de las IBA, from small alertas.geojson collections."""
import json
from datetime import datetime, timezone

import pytest

from centinela import signals

WEB = "https://asensio94.github.io/centinela-natura/"
NOW = datetime(2026, 10, 13, 7, 2, 41, tzinfo=timezone.utc)


def _feature(id: str, estado: str, detectada: str = "2026-09-30", **kw) -> dict:
    p = {"id": id, "estado": estado, "detectada": detectada, "ha": 0.5, "centro": [43.1, -3.9],
         "espacios": [{"codigo": "ES1300016", "nombre": "Sierra del Escudo", "tipo": "ZEC"}],
         "municipios": ["Luena"], "cruce": "sin_expediente", "cruce_nombre": "Sin expediente conocido", **kw}
    return {"type": "Feature", "geometry": None, "properties": p}


def _doc(*features: dict, sites=("ES1300016",)) -> dict:
    return signals.document({"type": "FeatureCollection", "features": list(features)}, list(sites), NOW, WEB)


def test_only_current_alerts_become_signals_in_date_order():
    d = _doc(_feature("CN-202609-002", "confirmada"), _feature("CN-202609-001", "provisional"),
             _feature("CN-202608-001", "confirmada", detectada="2026-08-31"),
             _feature("CN-202607-001", "descartada"), _feature("CN-202607-002", "revertida"),
             _feature("CN-202607-003", "fusionada", fusionada_en="CN-202609-001"))
    assert [s["id"] for s in d["signals"]] == ["CN-202608-001", "CN-202609-001", "CN-202609-002"]
    assert {s["status"] for s in d["signals"]} == {"confirmada", "provisional"}


def test_signal_fields():
    s = _doc(_feature("CN-202609-001", "confirmada", clase_nombre="Pérdida de vegetación"))["signals"][0]
    assert s["kind"] == "land_change" and s["precision"] == "pixeles" and s["date"] == "2026-09-30"
    assert s["title"] == "Pérdida de vegetación"
    assert s["url"] == WEB + "#CN-202609-001"
    assert s["sites"] == [{"code": "ES1300016"}]
    assert s["municipalities"] == [] and s["municipality_names"] == ["Luena"] and s["provinces"] == ["Cantabria"]
    assert s["value"] == {"amount": 0.5, "unit": "ha"} and s["deadline"] is None
    assert s["details"]["permit"] == "Sin expediente conocido"
    # The hub adds these itself.
    assert "source" not in s and "regions" not in s
    # Not yet analysed: no class.
    assert _doc(_feature("CN-202609-001", "provisional"))["signals"][0]["title"] == "Cambio de cubierta"


def test_point_is_lon_lat():
    s = _doc(_feature("CN-202609-001", "confirmada", centro=[43.05516, -3.90261]))["signals"][0]
    assert s["details"]["point"] == [-3.90261, 43.05516]


def test_photo_links_are_absolute():
    s = _doc(_feature("CN-202609-001", "confirmada", foto_antes="chips/CN-202609-001_antes.jpg",
                      foto_despues="chips/CN-202609-001_despues.jpg",
                      fecha_antes="2025-07-04", fecha_despues="2026-07-04"))["signals"][0]
    assert s["details"]["before"] == WEB + "chips/CN-202609-001_antes.jpg"
    assert s["details"]["after"] == WEB + "chips/CN-202609-001_despues.jpg"
    assert (s["details"]["before_date"], s["details"]["after_date"]) == ("2025-07-04", "2026-07-04")
    # Photos come with the analysis: until then there are none.
    s = _doc(_feature("CN-202609-001", "provisional"))["signals"][0]
    assert s["details"]["before"] is None and s["details"]["after"] is None


def test_no_parcels_or_owners():
    parcela = {"refcat": "39039A00901478", "municipio": "39039", "poligono": 9, "parcela": 1478}
    s = _doc(_feature("CN-202609-001", "confirmada", parcelas=[parcela], n_parcelas=1))["signals"][0]
    assert "39039A00901478" not in json.dumps(s)


def test_document_header():
    d = _doc(sites=["ES1300016", "ES0000143", "ES1300016"])
    assert (d["source"], d["version"], d["generated"]) == ("centinela-natura", 1, "2026-10-13T07:02Z")
    assert d["coverage"] == {"label": "Cantabria", "sites": ["ES0000143", "ES1300016"],
                             "note": "Cambios de vegetación con Sentinel-2, revisados cada mes."}
    assert d["signals"] == []


def test_current_states_are_the_active_ones():
    alertas = pytest.importorskip("centinela.alertas")   # needs the whole satellite stack
    assert set(signals.CURRENT) == set(alertas.ACTIVAS)


def test_french_alerts_have_their_title_and_permit_in_french(monkeypatch):
    from centinela import config
    monkeypatch.setattr(config, "PAIS", "FR")
    f = _feature("CF-202609-001", "confirmada", clase="quemado", clase_nombre="Superficie quemada",
                 cruce_nombre="Sin autorización conocida", espacios=[{"codigo": "FR7212010"}])
    d = _doc(f, _feature("CF-202609-002", "provisional", cruce="pendiente"), sites=("FR7212010",))
    burnt, unknown = d["signals"]
    assert burnt["title"] == "Surface brûlée" and burnt["details"]["permit"] == "Sans autorisation connue"
    assert unknown["title"] == "Changement de couverture" and unknown["details"]["permit"] == "Parcelles à consulter"
    assert burnt["status"] == "confirmada"  # values stay canonical
    assert d["coverage"]["note"].startswith("Changements de végétation")
