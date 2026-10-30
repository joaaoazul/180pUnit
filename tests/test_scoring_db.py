from datetime import datetime, timedelta, timezone

from achados.db import Database
from achados.models import Listing
from achados.scoring import compute_deals


def mk(i, price, desc="", area=80.0):
    return Listing("t", str(i), f"https://x/{i}", f"T2 {i}", price, area, 2, "apartamento",
                   "sale", "Lisboa", "Lisboa", desc)


def seeded(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    for i in range(6):
        db.upsert(mk(i, 300_000 + i * 5_000))
    return db


def test_upsert_tracks_price_changes(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    assert db.upsert(mk(1, 200_000)) == "new"
    assert db.upsert(mk(1, 200_000)) == "seen"
    assert db.upsert(mk(1, 180_000)) == "price_change"
    assert db.price_history("t", "1") == [200_000, 180_000]


def test_mark_inactive(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    db.upsert(mk(1, 100_000), seen_at="2026-01-01T00:00:00+00:00")
    assert db.mark_inactive("t", "2026-02-01T00:00:00+00:00") == 1
    assert db.active_listings() == []


def test_cheap_listing_ranks_first_with_reasons(tmp_path):
    db = seeded(tmp_path)
    db.upsert(mk(99, 190_000, "Venda urgente"))
    top = compute_deals(db)[0]
    assert top.row["source_id"] == "99"
    assert top.discount > 0.35
    assert top.score > 60
    assert any("urgente" in r for r in top.reasons)


def test_price_drop_adds_score(tmp_path):
    db = seeded(tmp_path)
    db.upsert(mk(2, 320_000))
    before = next(d for d in compute_deals(db) if d.row["source_id"] == "2").score
    db.upsert(mk(2, 272_000))
    after = next(d for d in compute_deals(db) if d.row["source_id"] == "2")
    assert after.price_drop > 0.1 and after.score > before


def test_too_few_comparables_gives_no_discount(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    for i in range(3):
        db.upsert(mk(i, 100_000 + i))
    assert all(d.discount is None for d in compute_deals(db))


def test_absurd_discount_is_flagged_and_risk_keywords_warn(tmp_path):
    db = seeded(tmp_path)
    db.upsert(mk(77, 40_000, "Ruína para recuperar"))
    d = next(x for x in compute_deals(db) if x.row["source_id"] == "77")
    assert any("suspeito" in w for w in d.warnings)
    assert any("risco" in w for w in d.warnings)


def test_stale_listing_bonus(tmp_path):
    db = Database(str(tmp_path / "t.db"))
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
    db.upsert(mk(1, 100_000), seen_at=old)
    d = compute_deals(db)[0]
    assert d.score == 5 and "dias" in d.reasons[0]


def test_evaluate_manual_spec(tmp_path):
    from achados.scoring import evaluate
    db = seeded(tmp_path)  # T2 Lisboa, 3750-4062 €/m²
    spec = {"municipality": "Lisboa", "rooms": 2, "property_type": "apartamento",
            "area_m2": 80.0, "price": 240_000.0}
    ev = evaluate(db, spec)
    assert ev.comparables == 6 and ev.scope == "Lisboa T2"
    assert ev.discount > 0.2 and "ÓTIMO" in ev.verdict
    assert ev.fair_low <= ev.fair_price <= ev.fair_high
    assert "caro" in evaluate(db, {**spec, "price": 420_000.0}).verdict


def test_evaluate_without_comparables(tmp_path):
    from achados.scoring import evaluate
    ev = evaluate(Database(str(tmp_path / "t.db")),
                  {"municipality": "Faro", "area_m2": 50.0, "price": 100_000.0})
    assert ev.median_ppm2 is None and "sem comparáveis" in ev.verdict
