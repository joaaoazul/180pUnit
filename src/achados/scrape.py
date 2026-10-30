from __future__ import annotations

import logging
from dataclasses import dataclass

from .db import Database, now_iso
from .fetch import Blocked, PoliteFetcher
from .sources import PARSERS, page_url

log = logging.getLogger(__name__)


@dataclass
class SearchStats:
    name: str
    new: int = 0
    price_changes: int = 0
    seen: int = 0
    pages: int = 0
    blocked: bool = False


def run_search(search: dict, db: Database, fetcher: PoliteFetcher,
               max_pages: int) -> SearchStats:
    parser = PARSERS[search["source"]]
    stats = SearchStats(search.get("name", search["url"]))
    seen_ids: set[str] = set()
    for page in range(1, max_pages + 1):
        url = page_url(search["url"], page)
        try:
            html = fetcher.get(url)
        except Blocked as exc:
            log.error("%s", exc)
            stats.blocked = True
            break
        listings = [l for l in parser(html, url) if l.source_id not in seen_ids]
        if not listings:  # fim da paginação (ou a estrutura do site mudou)
            if page == 1:
                log.warning("0 anúncios em %s — o parser pode estar desatualizado", url)
            break
        stats.pages += 1
        for l in listings:
            seen_ids.add(l.source_id)
            outcome = db.upsert(l)
            if outcome == "new":
                stats.new += 1
            elif outcome == "price_change":
                stats.price_changes += 1
            else:
                stats.seen += 1
    return stats


def run_all(config: dict, db: Database, fetcher: PoliteFetcher) -> list[SearchStats]:
    started = now_iso()
    max_pages = config.get("settings", {}).get("max_pages", 5)
    results = [run_search(s, db, fetcher, max_pages) for s in config.get("search", [])]
    # só desativa anúncios de fontes que correram sem bloqueio
    ok_sources = {s["source"] for s, r in zip(config.get("search", []), results) if not r.blocked}
    for source in ok_sources:
        db.mark_inactive(source, started)
    return results
