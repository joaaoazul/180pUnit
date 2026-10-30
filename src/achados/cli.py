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
from .scoring import compute_deals, evaluate
from .scrape import run_all


def _load(path: str, required: bool = True) -> dict:
    p = Path(path)
    if not p.exists():
        if not required:
            return {}
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


def _ask(label: str, cast=str, required: bool = True):
    while True:
        raw = input(f"{label}: ").strip()
        if not raw and not required:
            return None
        try:
            return cast(raw.replace(" ", "").replace(",", ".")) if cast is not str else raw
        except ValueError:
            print("  valor inválido")


def cmd_check(args, cfg) -> int:
    interactive = args.preco is None and args.area is None and args.concelho is None
    if interactive:
        print("Descreve o imóvel (Enter para saltar o que for opcional):")
        args.concelho = _ask("Concelho (ex: Lisboa)")
        args.distrito = _ask("Distrito", required=False)
        args.tipo = _ask("Tipo (apartamento/moradia/terreno)", required=False) or "apartamento"
        args.tipologia = _ask("Tipologia (nº quartos, T2 -> 2)", int, required=False)
        args.area = _ask("Área útil (m²)", float)
        args.preco = _ask("Preço pedido (€)", float)
        args.descricao = _ask("Notas/descrição", required=False) or ""
    missing = [n for n, v in (("--concelho", args.concelho), ("--area", args.area),
                              ("--preco", args.preco)) if v is None]
    if missing:
        sys.exit("Faltam: " + ", ".join(missing) + " (ou corre sem argumentos para modo interativo)")
    if args.area <= 0 or args.preco <= 0:
        sys.exit("Área e preço têm de ser positivos.")

    db = Database(cfg.get("settings", {}).get("db_path", "achados.db"))
    spec = {"municipality": args.concelho, "district": args.distrito,
            "rooms": args.tipologia, "property_type": args.tipo.lower(),
            "transaction_type": "rent" if args.arrendar else "sale",
            "area_m2": args.area, "price": args.preco, "description": args.descricao}
    ev = evaluate(db, spec, cfg.get("scoring", {}).get("min_comparables", 5))
    print(f"\nPreço pedido: {args.preco:,.0f} € · {args.area:g} m² · {ev.price_per_m2:,.0f} €/m²")
    if ev.median_ppm2:
        print(f"Mercado ({ev.scope}, {ev.comparables} comparáveis): mediana {ev.median_ppm2:,.0f} €/m²")
        print(f"Preço justo estimado: {ev.fair_price:,.0f} € "
              f"(intervalo típico {ev.fair_low:,.0f}–{ev.fair_high:,.0f} €)")
        print(f"Diferença: {ev.discount:+.0%} face à mediana (positivo = mais barato)")
    print(f"Veredito: {ev.verdict}")
    for w in ev.warnings:
        print(f"! {w}")
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
    c = sub.add_parser("check", help="avalia um imóvel que descreves (sem argumentos: interativo)")
    c.add_argument("--concelho")
    c.add_argument("--distrito")
    c.add_argument("--tipo", default="apartamento", help="apartamento, moradia, terreno, ...")
    c.add_argument("--tipologia", type=int, help="nº de quartos (T2 -> 2)")
    c.add_argument("--area", type=float, help="área em m²")
    c.add_argument("--preco", type=float, help="preço pedido em €")
    c.add_argument("--descricao", default="")
    c.add_argument("--arrendar", action="store_true", help="avaliar renda em vez de venda")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)s %(message)s")
    cfg = _load(args.config, required=args.cmd != "check")
    return {"scrape": cmd_scrape, "deals": cmd_deals, "check": cmd_check}[args.cmd](args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
