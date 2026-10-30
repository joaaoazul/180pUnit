from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import tomllib
from pathlib import Path

from .db import Database
from .fetch import PoliteFetcher
from .scoring import compute_deals
from .scrape import run_all


def _load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        sys.exit(f"Config não encontrada: {path}\nCopia searches.example.toml para {path}.")
    return tomllib.loads(p.read_text(encoding="utf-8"))


def cmd_scrape(args, cfg) -> int:
    db = Database(cfg.get("settings", {}).get("db_path", "achados.db"))
    fetcher = PoliteFetcher(delay=cfg.get("settings", {}).get("delay_seconds", 4.0))
    for r in run_all(cfg, db, fetcher):
        flag = "  [BLOQUEADO]" if r.blocked else ""
        print(f"{r.name}: {r.new} novos, {r.price_changes} com preço alterado, "
              f"{r.seen} inalterados ({r.pages} págs){flag}")
    return 0


def cmd_deals(args, cfg) -> int:
    db = Database(cfg.get("settings", {}).get("db_path", "achados.db"))
    min_comps = cfg.get("scoring", {}).get("min_comparables", 5)
    deals = [d for d in compute_deals(db, min_comps) if d.score >= args.min_score][: args.limit]
    if args.format == "json":
        print(json.dumps([{"score": d.score, **d.row, "discount": d.discount,
                           "reasons": d.reasons, "warnings": d.warnings} for d in deals],
                         ensure_ascii=False, indent=2))
    elif args.format == "csv":
        w = csv.writer(sys.stdout)
        w.writerow(["score", "price", "area_m2", "eur_m2", "discount", "title", "url"])
        for d in deals:
            w.writerow([d.score, d.row["price"], d.row["area_m2"],
                        round(d.price_per_m2 or 0), round(d.discount or 0, 3),
                        d.row["title"], d.row["url"]])
    else:
        for d in deals:
            r = d.row
            price = f"{r['price']:,.0f} €" if r["price"] else "s/ preço"
            print(f"[{d.score:5.1f}] {price} · {r['area_m2'] or '?'} m² · {r['title']}")
            print(f"        {r['url']}")
            for x in d.reasons:
                print(f"        + {x}")
            for x in d.warnings:
                print(f"        ! {x}")
        if not deals:
            print("Sem resultados acima do score mínimo (corre `achados scrape` primeiro?).")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="achados", description=__doc__)
    ap.add_argument("-c", "--config", default="searches.toml")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scrape", help="recolhe anúncios das pesquisas configuradas")
    d = sub.add_parser("deals", help="lista os melhores negócios")
    d.add_argument("--min-score", type=float, default=30)
    d.add_argument("--limit", type=int, default=20)
    d.add_argument("--format", choices=["table", "csv", "json"], default="table")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    cfg = _load(args.config)
    return {"scrape": cmd_scrape, "deals": cmd_deals}[args.cmd](args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
