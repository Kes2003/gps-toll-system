"""Payment receipt for a completed trip."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from gps_toll.simulation import TripResult


@dataclass(frozen=True)
class Receipt:
    transaction_id: int
    issued_at: datetime
    amount_inr: float
    vehicle_type: str
    speed_kmh: float
    route: str
    distance_charged_km: float
    rate_per_km: float
    payment_mode: str = "Credit Card"

    def as_text(self) -> str:
        return "\n".join(
            [
                f"Amount Paid: {self.amount_inr:.2f} INR",
                f"Date and Time: {self.issued_at:%Y-%m-%d %H:%M:%S}",
                f"Route: {self.route}",
                f"Distance Charged: {self.distance_charged_km:.2f} km",
                f"Rate: {self.rate_per_km:.2f} INR/km",
                f"Vehicle Type: {self.vehicle_type}",
                f"Speed: {self.speed_kmh:.2f} km/h",
                f"Transaction ID: {self.transaction_id}",
                f"Payment Mode: {self.payment_mode}",
            ]
        )


def issue_receipt(result: TripResult, rng: Optional[random.Random] = None) -> Receipt:
    return Receipt(
        transaction_id=(rng or random).randint(1_000_000_000, 9_999_999_999),
        issued_at=datetime.now(),
        amount_inr=round(result.toll_amount, 2),
        vehicle_type=result.car.vehicle_class.name,
        speed_kmh=result.car.speed_kmh,
        route=f"{result.highway.start_name} -> {result.highway.end_name}",
        distance_charged_km=result.tolled_distance_km,
        rate_per_km=result.toll_rate_per_km,
    )
