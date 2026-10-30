"""Fonte genérica: lê anúncios de blocos JSON-LD (schema.org) nas páginas de listagem."""
from __future__ import annotations

import hashlib
import json
import re

from bs4 import BeautifulSoup

from ..models import Listing

LISTING_TYPES = {"Product", "Offer", "Residence", "Apartment", "House", "SingleFamilyResidence",
                 "RealEstateListing", "Accommodation"}


def _walk(node):
    if isinstance(node, list):
        for n in node:
            yield from _walk(n)
    elif isinstance(node, dict):
        yield node
        for key in ("@graph", "itemListElement", "item", "mainEntity"):
            if key in node:
                yield from _walk(node[key])


def _types(node) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if t else set()


def _price(node) -> float | None:
    offers = node.get("offers") or node
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    raw = offers.get("price") if isinstance(offers, dict) else None
    try:
        return float(str(raw).replace(" ", "").replace(",", ".")) if raw is not None else None
    except ValueError:
        return None


def _area(node) -> float | None:
    size = node.get("floorSize")
    value = size.get("value") if isinstance(size, dict) else size
    try:
        return float(str(value).replace(",", ".")) if value is not None else None
    except ValueError:
        return None


def parse(html: str, page_url: str = "") -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, Listing] = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        for node in _walk(data):
            if not (_types(node) & LISTING_TYPES):
                continue
            url = node.get("url") or ""
            name = str(node.get("name") or "").strip()
            if not url or not name:
                continue
            addr = node.get("address") or {}
            rooms = node.get("numberOfRooms")
            m = re.search(r"\bT(\d)\b", name, re.I)
            out[url] = Listing(
                source="jsonld",
                source_id=hashlib.sha1(url.encode()).hexdigest()[:16],
                url=url,
                title=name,
                price=_price(node),
                area_m2=_area(node),
                rooms=int(rooms) if str(rooms).isdigit() else int(m.group(1)) if m else None,
                municipality=addr.get("addressLocality") if isinstance(addr, dict) else None,
                district=addr.get("addressRegion") if isinstance(addr, dict) else None,
                description=str(node.get("description") or ""),
            )
    return list(out.values())
