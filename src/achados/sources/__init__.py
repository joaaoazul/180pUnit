from __future__ import annotations

from typing import Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..models import Listing
from . import imovirtual, jsonld

# nome na config -> função parse(html, page_url) -> list[Listing]
PARSERS: dict[str, Callable[[str, str], list[Listing]]] = {
    "imovirtual": imovirtual.parse,
    "jsonld": jsonld.parse,
}


def page_url(base: str, page: int) -> str:
    """Acrescenta ?page=N (a página 1 fica sem parâmetro)."""
    if page <= 1:
        return base
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query["page"] = str(page)
    return urlunsplit(parts._replace(query=urlencode(query)))
