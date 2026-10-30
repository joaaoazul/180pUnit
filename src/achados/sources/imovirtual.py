"""Imovirtual (Next.js): os anúncios vêm em <script id="__NEXT_DATA__">.

ATENÇÃO: a estrutura do JSON foi escrita de memória e testada só com fixture;
valida com `achados scrape` contra o site real e ajusta _item_to_listing se preciso.
"""
from __future__ import annotations

import json

from bs4 import BeautifulSoup

from ..models import Listing

BASE = "https://www.imovirtual.com"
ROOMS = {"ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5, "SIX": 6, "SEVEN": 7,
         "EIGHT": 8, "NINE": 9, "TEN": 10, "STUDIO": 0}
TYPES = {"FLAT": "apartamento", "HOUSE": "moradia", "TERRAIN": "terreno",
         "ROOM": "quarto", "COMMERCIAL_PROPERTY": "comercial", "GARAGE": "garagem"}


def _find_key(obj, key):
    """Procura recursivamente a primeira ocorrência de `key`."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = _find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_key(v, key)
            if found is not None:
                return found
    return None


def _get(d, *path):
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(" ", "").replace(",", "."))
        except ValueError:
            return None
    return None


def _item_to_listing(item: dict) -> Listing | None:
    ad_id = item.get("id")
    slug = item.get("slug")
    if not ad_id or not slug:
        return None
    rooms = item.get("roomsNumber")
    if isinstance(rooms, str):
        rooms = ROOMS.get(rooms.upper())
    elif not isinstance(rooms, int):
        rooms = None
    address = _get(item, "location", "address") or {}
    transaction = str(item.get("transaction") or "SELL").upper()
    return Listing(
        source="imovirtual",
        source_id=str(ad_id),
        url=f"{BASE}/pt/anuncio/{slug}",
        title=str(item.get("title") or "").strip(),
        price=_num(_get(item, "totalPrice", "value")),
        area_m2=_num(item.get("areaInSquareMeters")),
        rooms=rooms,
        property_type=TYPES.get(str(item.get("estate") or "").upper()),
        transaction="rent" if transaction == "RENT" else "sale",
        district=_get(address, "province", "name"),
        municipality=_get(address, "city", "name"),
        description=str(item.get("shortDescription") or ""),
    )


def parse(html: str, page_url: str = "") -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        return []
    data = json.loads(tag.string)
    search = _find_key(data, "searchAds")
    items = (search or {}).get("items") or []
    listings = [l for it in items if (l := _item_to_listing(it))]
    return listings
