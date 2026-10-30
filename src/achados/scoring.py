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


def compute_deals(db: Database, min_comparables: int = 5,
                  now: datetime | None = None) -> list[Deal]:
    now = now or datetime.now(timezone.utc)
    rows = [dict(r) for r in db.active_listings()]

    # índices de €/m² por grupo
    groups: dict[tuple, list[tuple[int, float]]] = {}
    for i, r in enumerate(rows):
        if not (r["price"] and r["area_m2"]):
            continue
        ppm2 = r["price"] / r["area_m2"]
        base = (r["transaction_type"], r["property_type"])
        keys = []
        if r["municipality"]:
            if r["rooms"] is not None:
                keys.append((*base, "m", r["municipality"], r["rooms"]))
            keys.append((*base, "m", r["municipality"], None))
        if r["district"]:
            keys.append((*base, "d", r["district"], None))
        for k in keys:
            groups.setdefault(k, []).append((i, ppm2))

    deals: list[Deal] = []
    for i, r in enumerate(rows):
        ppm2 = r["price"] / r["area_m2"] if r["price"] and r["area_m2"] else None
        reasons: list[str] = []
        warnings: list[str] = []
        discount = median = None
        n_comps, scope = 0, "-"

        if ppm2:
            base = (r["transaction_type"], r["property_type"])
            candidates = []
            if r["municipality"]:
                if r["rooms"] is not None:
                    candidates.append(((*base, "m", r["municipality"], r["rooms"]),
                                       f"{r['municipality']} T{r['rooms']}"))
                candidates.append(((*base, "m", r["municipality"], None), r["municipality"]))
            if r["district"]:
                candidates.append(((*base, "d", r["district"], None), r["district"]))
            for key, label in candidates:
                comps = [p for j, p in groups.get(key, []) if j != i]
                if len(comps) >= min_comparables:
                    med = statistics.median(comps)
                    comps = [p for p in comps if 0.3 * med <= p <= 3 * med]  # tira outliers
                    if len(comps) >= min_comparables:
                        median, n_comps, scope = statistics.median(comps), len(comps), label
                        break
            if median:
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
