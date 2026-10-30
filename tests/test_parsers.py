from pathlib import Path

from achados.sources import imovirtual, jsonld, page_url

FIX = Path(__file__).parent / "fixtures"


def test_imovirtual_parses_next_data():
    ls = imovirtual.parse((FIX / "imovirtual_page.html").read_text())
    assert len(ls) == 7
    first = ls[0]
    assert first.source_id == "1000" and first.rooms == 2
    assert first.price == 300000 and first.area_m2 == 80
    assert first.municipality == "Lisboa" and first.property_type == "apartamento"
    assert first.url.endswith("/pt/anuncio/t2-lisboa-1000")
    assert first.price_per_m2 == 3750


def test_imovirtual_without_next_data_returns_empty():
    assert imovirtual.parse("<html></html>") == []


def test_jsonld_parses_itemlist():
    ls = jsonld.parse((FIX / "jsonld_page.html").read_text())
    assert len(ls) == 1
    l = ls[0]
    assert (l.price, l.area_m2, l.rooms, l.municipality) == (250000, 110, 3, "Porto")


def test_page_url():
    assert page_url("https://x.pt/a", 1) == "https://x.pt/a"
    assert page_url("https://x.pt/a?q=1", 3) == "https://x.pt/a?q=1&page=3"
