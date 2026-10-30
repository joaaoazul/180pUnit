from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    price: float | None = None
    area_m2: float | None = None
    rooms: int | None = None  # tipologia: T2 -> 2
    property_type: str | None = None
    transaction: str = "sale"
    district: str | None = None
    municipality: str | None = None
    description: str = ""

    @property
    def price_per_m2(self) -> float | None:
        if self.price and self.area_m2 and self.area_m2 > 0:
            return self.price / self.area_m2
        return None
