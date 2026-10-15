"""France as a second country: paths, typography, cadastre ids, RPG year, Sitadel and signals."""
import json
from datetime import datetime, timezone

import pytest

from centinela import cadastre, config, i18n, rpg, signals, sitadel

WEB = "https://asensio94.github.io/centinela-natura/fr/"
NOW = datetime(2026, 10, 13, 7, 2, 41, tzinfo=timezone.utc)


@pytest.fixture
def francia():
    config.activar("FR")
    yield
    config.activar("ES")


def test_each_country_keeps_its_own_paths(francia):
    assert config.DATA_DIR == config.ROOT / "data" / "fr"
    assert config.SITE_DIR == config.ROOT / "site" / "fr"
    assert config.PREFIJO_COMPUESTO == "FR64_" and config.PREFIJO_ID == "CF"
    config.activar("ES")
    assert config.DATA_DIR == config.ROOT / "data" and config.SITE_DIR == config.ROOT / "site"
    assert config.PREFIJO_COMPUESTO == "" and config.PREFIJO_ID == "CN"


def test_french_numbers_use_narrow_no_break_spaces():
    assert i18n.num(1234.5, "es") == "1.234,5"
    assert i18n.num(1234.5, "fr") == "1 234,5"
    assert i18n.pct(0.854, "es") == "85 %"
    assert i18n.pct(0.854, "fr") == "85 %"
    assert i18n.FR["feed_title"].startswith("Centinela Natura :")
    assert "~" not in json.dumps(i18n.FR, ensure_ascii=False)


def test_both_languages_have_the_same_texts():
    assert i18n.ES.keys() <= i18n.FR.keys()
    assert i18n.ES["js"].keys() <= i18n.FR["js"].keys()
    assert i18n.ES["parametros_filas"].keys() <= i18n.FR["parametros_filas"].keys()
    assert "juil." in i18n.MESES_CORTOS["fr"] and i18n.MESES_CORTOS["es"][6] == "jul"


def test_cadastre_id_is_split_into_section_and_number():
    assert cadastre.desglosar("64024000AB0042") == {"prefixe": "000", "section": "AB", "numero": 42}
    assert cadastre.desglosar("640240000A0151") == {"prefixe": "000", "section": "A", "numero": 151}


@pytest.mark.parametrize("primera, anio", [
    ("2026-09", 2026),     # window from July: the 2026 declaration is already made
    ("2026-08", 2026),     # window from June
    ("2026-07", 2025),     # window from May, before the 15 May deadline closes
    ("2026-02", 2025),     # window from December 2025
])
def test_rpg_year_is_the_last_declaration_before_the_window(primera, anio):
    assert rpg.anio_previo(primera) == anio


def test_sitadel_parcel_keys():
    assert sitadel.parcela("AB", "42") == "AB0042"
    assert sitadel.parcela("0A", "151P") == "A0151"
    assert sitadel.parcela("", "12") is None and sitadel.parcela("A", "0") is None
    assert sitadel.numero_oficial("PC", "06400524X1001") == "PC 064 005 24 X1001"


def test_sitadel_keeps_no_applicant(francia, monkeypatch, tmp_path):
    cabecera = ("COMM;DATE_REELLE_AUTORISATION;NUM_DAU;ETAT_DAU;TYPE_DAU;DESTINATION_PRINCIPALE;"
                "DENOM_DEM;SIREN_DEM;SIRET_DEM;ADR_LOCALITE_TER;SEC_CADASTRE1;NUM_CADASTRE1;"
                "SEC_CADASTRE2;NUM_CADASTRE2;SEC_CADASTRE3;NUM_CADASTRE3\n")
    fila = "64024;2024-05-02;06402424X1001;5;PC;1;DUPONT JEAN;123456789;12345678900011;ANGLET;AB;42;;;;\n"
    viejo = "64024;2016-05-02;06402416X0001;6;PC;1;MARTIN;;;ANGLET;AB;43;;;;\n"

    class R:
        def __init__(self, texto):
            self.content = texto.encode("utf-8")

        def json(self):
            return {"millesime": "2026-09"}

    def falso(url, **kw):
        if url.endswith("/csv"):
            return R(cabecera + (fila + viejo if "f8f0700f" in url else ""))
        return R("")

    monkeypatch.setattr(sitadel, "_get", falso)
    monkeypatch.setattr(sitadel, "communes_vigiladas", lambda: {"64024"})
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    sitadel.descargar()
    texto = sitadel.ruta().read_text(encoding="utf-8")
    for dato in ("DUPONT", "MARTIN", "123456789", "ANGLET", "DENOM"):
        assert dato not in texto
    datos = json.loads(texto)
    assert datos["communes"] == {"64024": [["PC 064 024 24 X1001", "PC", "2024-05-02", "5", "1", ["AB0042"]]]}

    regs = sitadel.cargar()
    alerta = {"primera": "2026-09", "parcelas": [
        {"refcat": "64024000AB0042", "municipio": "64024", "section": "AB", "numero": 42}]}
    c = sitadel.cruzar(alerta, regs, sitadel.huellas(regs))
    assert c["estado"] == "resolucion" and c["expedientes"][0]["parcelas"] == ["64024000AB0042"]
    assert sitadel.cruzar({**alerta, "primera": "2028-09"}, regs, sitadel.huellas(regs))["estado"] == "sin_expediente"


def _feature(id, municipios, insee=None, codigo="FR7200787"):
    p = {"id": id, "estado": "confirmada", "detectada": "2026-09-30", "ha": 0.5, "centro": [43.5, -1.5],
         "espacios": [{"codigo": codigo}], "municipios": municipios, "cruce": "sin_expediente"}
    if insee is not None:
        p["municipios_insee"] = insee
    return {"type": "Feature", "geometry": None, "properties": p}


def test_french_signals_carry_country_and_insee(francia):
    d = signals.document({"features": [_feature("CF-202609-001", ["Anglet"], ["64024"])]},
                         ["FR7200787"], NOW, WEB)
    s = d["signals"][0]
    assert s["country"] == "FR" and s["municipalities"] == ["64024"]
    assert s["municipality_names"] == ["Anglet"] and s["provinces"] == ["Pyrénées-Atlantiques"]
    assert s["url"] == WEB + "#CF-202609-001"


def test_spanish_signals_say_es_and_keep_names_only():
    d = signals.document({"features": [_feature("CN-202609-001", ["Luena"], codigo="ES1300016")]},
                         ["ES1300016"], NOW, "https://x/")
    assert d["signals"][0]["country"] == "ES" and d["signals"][0]["municipalities"] == []


def test_combined_file_joins_both_countries():
    es = signals.document({"features": [_feature("CN-202609-001", ["Luena"], codigo="ES1300016")]},
                          ["ES1300016"], NOW, "https://x/")
    assert signals.combine([es], NOW) is es
    config.activar("FR")
    try:
        fr = signals.document({"features": [_feature("CF-202609-001", ["Anglet"], ["64024"])]},
                              ["FR7200787"], NOW, WEB)
    finally:
        config.activar("ES")
    d = signals.combine([es, fr], NOW)
    assert [s["country"] for s in d["signals"]] == ["ES", "FR"]
    assert d["coverage"]["label"] == "Cantabria · Pyrénées-Atlantiques"
    assert d["coverage"]["sites"] == ["ES1300016", "FR7200787"]
    assert d["version"] == 1 and d["source"] == "centinela-natura"
