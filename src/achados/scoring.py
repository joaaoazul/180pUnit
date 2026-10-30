"""Pontuação de "bom negócio" (0-100).

Componentes:
  * desconto €/m² face à mediana de anúncios comparáveis   (até 60 pts)
  * descida de preço observada no nosso histórico            (até 25 pts)
  * palavras de urgência/oportunidade na descrição           (10 pts)
  * anúncio parado há muito tempo (negociação provável)      (5 pts)
Descontos > 60% são tratados como suspeitos (terreno, ruína, erro de área, preço de renda).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .db import Database

POSITIVE = ("urgente", "oportunidade", "negociável", "negociavel", "herdeiros", "leilão",
            "leilao", "abaixo do valor", "preço reduzido", "preco reduzido", "venda rápida",
            "venda rapida", "investidores")
RISK = ("ruína", "ruina", "para recuperar", "para reconstruir", "ocupado", "penhora",
        "devoluto", "sem licença", "sem licenca")
SUSPECT_DISCOUNT = 0.60
STALE_DAYS = 60


@dataclass
class Deal:
    row: dict
    score: float
    price_per_m2: float | None
    median_ppm2: float | None
    discount: float | None
    price_drop: float
    comparables: int
    comparable_scope: str
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _candidates(r: dict) -> list[tuple[tuple, str]]:
    """Chaves de grupo, do mais específico para o mais genérico."""
    base = (r["transaction_type"], r["property_type"])
    out = []
    if r["municipality"]:
        if r["rooms"] is not None:
            out.append(((*base, "m", r["municipality"], r["rooms"]),
                        f"{r['municipality']} T{r['rooms']}"))
        out.append(((*base, "m", r["municipality"], None), r["municipality"]))
    if r["district"]:
        out.append(((*base, "d", r["district"], None), r["district"]))
    return out


def _build_groups(rows: list[dict]) -> dict[tuple, list[tuple[int, float]]]:
    groups: dict[tuple, list[tuple[int, float]]] = {}
    for i, r in enumerate(rows):
        if not (r["price"] and r["area_m2"]):
            continue
        for key, _ in _candidates(r):
            groups.setdefault(key, []).append((i, r["price"] / r["area_m2"]))
    return groups


def _find_comparables(r: dict, groups: dict, min_comparables: int,
                      exclude: int | None = None) -> tuple[list[float], str]:
    """€/m² dos comparáveis do grupo mais específico com amostra suficiente."""
    for key, label in _candidates(r):
        comps = [p for j, p in groups.get(key, []) if j != exclude]
        if len(comps) >= min_comparables:
            med = statistics.median(comps)
            comps = [p for p in comps if 0.3 * med <= p <= 3 * med]  # tira outliers
            if len(comps) >= min_comparables:
                return comps, label
    return [], "-"


def compute_deals(db: Database, min_comparables: int = 5,
                  now: datetime | None = None) -> list[Deal]:
    now = now or datetime.now(timezone.utc)
    rows = [dict(r) for r in db.active_listings()]
    groups = _build_groups(rows)

    deals: list[Deal] = []
    for i, r in enumerate(rows):
        ppm2 = r["price"] / r["area_m2"] if r["price"] and r["area_m2"] else None
        reasons: list[str] = []
        warnings: list[str] = []
        discount = median = None
        n_comps, scope = 0, "-"

        if ppm2:
            comps, scope = _find_comparables(r, groups, min_comparables, exclude=i)
            if comps:
                median, n_comps = statistics.median(comps), len(comps)
                discount = 1 - ppm2 / median

        score = 0.0
        if discount is not None and discount > 0:
            score += _clamp(discount / 0.40) * 60
            reasons.append(f"{discount:.0%} abaixo da mediana de {scope} "
                           f"({ppm2:,.0f} vs {median:,.0f} €/m², n={n_comps})")
        if discount is not None and discount > SUSPECT_DISCOUNT:
            warnings.append("desconto suspeito: confirmar área/tipo (terreno? ruína? erro?)")

        history = db.price_history(r["source"], r["source_id"])
        drop = 0.0
        if len(history) >= 2 and max(history) > 0:
            drop = (max(history) - history[-1]) / max(history)
            if drop > 0:
                score += _clamp(drop / 0.15) * 25
                reasons.append(f"preço desceu {drop:.0%} (de {max(history):,.0f} para {history[-1]:,.0f} €)")

        text = f"{r['title']} {r['description']}".lower()
        hits = [k for k in POSITIVE if k in text]
        if hits:
            score += 10
            reasons.append("palavras-chave: " + ", ".join(sorted(set(hits))))
        risks = [k for k in RISK if k in text]
        if risks:
            warnings.append("risco: " + ", ".join(sorted(set(risks))))

        first = datetime.fromisoformat(r["first_seen"])
        age = (now - first).days
        if age >= STALE_DAYS:
            score += 5
            reasons.append(f"há {age} dias na base de dados (margem de negociação)")

        deals.append(Deal(r, round(score, 1), ppm2, median, discount, drop,
                          n_comps, scope, reasons, warnings))
    deals.sort(key=lambda d: d.score, reverse=True)
    return deals


@dataclass
class Evaluation:
    price_per_m2: float
    comparables: int
    scope: str
    median_ppm2: float | None = None
    discount: float | None = None
    fair_price: float | None = None
    fair_low: float | None = None  # percentil 25
    fair_high: float | None = None  # percentil 75
    verdict: str = ""
    warnings: list[str] = field(default_factory=list)


def _verdict(discount: float) -> str:
    if discount > SUSPECT_DISCOUNT:
        return "suspeito (barato demais — confirma os dados)"
    if discount >= 0.20:
        return "ÓTIMO negócio"
    if discount >= 0.10:
        return "bom negócio"
    if discount >= -0.05:
        return "preço de mercado"
    if discount >= -0.15:
        return "um pouco caro"
    return "caro"


def evaluate(db: Database, spec: dict, min_comparables: int = 5) -> Evaluation:
    """Avalia um imóvel descrito à mão (municipality, rooms, area_m2, price, ...)."""
    r = {"transaction_type": "sale", "property_type": None, "district": None,
         "municipality": None, "rooms": None, "title": "", "description": "", **spec}
    ppm2 = r["price"] / r["area_m2"]
    rows = [dict(x) for x in db.active_listings()]
    comps, scope = _find_comparables(r, _build_groups(rows), min_comparables)
    ev = Evaluation(ppm2, len(comps), scope)
    text = f"{r['title']} {r['description']}".lower()
    risks = [k for k in RISK if k in text]
    if risks:
        ev.warnings.append("risco: " + ", ".join(sorted(set(risks))))
    if not comps:
        ev.verdict = "sem comparáveis suficientes (corre `achados scrape` ou baixa min_comparables)"
        return ev
    ev.median_ppm2 = statistics.median(comps)
    q = statistics.quantiles(comps, n=4) if len(comps) >= 2 else [ev.median_ppm2] * 3
    ev.fair_price = ev.median_ppm2 * r["area_m2"]
    ev.fair_low, ev.fair_high = q[0] * r["area_m2"], q[2] * r["area_m2"]
    ev.discount = 1 - ppm2 / ev.median_ppm2
    ev.verdict = _verdict(ev.discount)
    return ev
