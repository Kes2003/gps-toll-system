"""Payment receipt for a completed trip."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Tuple

from gps_toll.simulation import TripResult


@dataclass(frozen=True)
class ReceiptLine:
    toll_zone: str
    distance_km: float
    free_km: float
    rate_per_km: float
    amount_inr: float


@dataclass(frozen=True)
class Receipt:
    transaction_id: int
    issued_at: datetime
    registration: str
    vehicle_type: str
    route: str
    distance_km: float
    speed_kmh: float
    lines: Tuple[ReceiptLine, ...]
    amount_inr: float
    fastag_amount_inr: float
    payment_mode: str = "Credit Card"

    @property
    def free_km(self) -> float:
        return sum(line.free_km for line in self.lines)

    def as_text(self) -> str:
        rows = [
            f"Transaction ID: {self.transaction_id}",
            f"Date and Time: {self.issued_at:%Y-%m-%d %H:%M:%S}",
            f"Vehicle: {self.registration}, {self.vehicle_type}",
            f"Route: {self.route} ({self.distance_km:.1f} km)",
            f"Average Speed: {self.speed_kmh:.1f} km/h",
            "",
            "Toll zone                      km    rate   amount",
        ]
        for line in self.lines:
            rows.append(
                f"{line.toll_zone:28s} {line.distance_km:5.1f}  {line.rate_per_km:5.2f}  {line.amount_inr:7.2f}"
            )
        if self.free_km:
            rows.append(f"GNSS free distance: {self.free_km:.1f} km")
        rows += [
            "",
            f"Amount Paid: {self.amount_inr:.2f} INR",
            f"(FASTag plaza fees would have been {self.fastag_amount_inr:.2f} INR)",
            f"Payment Mode: {self.payment_mode}",
        ]
        return "\n".join(rows)


def issue_receipt(result: TripResult, rng: Optional[random.Random] = None) -> Receipt:
    lines = tuple(
        ReceiptLine(
            toll_zone=line.passage.zone.plaza.name,
            distance_km=line.passage.distance_km,
            free_km=line.free_km,
            rate_per_km=line.rate_per_km,
            amount_inr=round(line.amount, 2),
        )
        for line in result.bill.lines
    )
    return Receipt(
        transaction_id=(rng or random).randint(1_000_000_000, 9_999_999_999),
        issued_at=datetime.now(),
        registration=result.vehicle.registration,
        vehicle_type=result.vehicle.vehicle_class.name,
        route=f"{result.trip.origin.name} -> {result.trip.destination.name}",
        distance_km=result.distance_km,
        speed_kmh=result.average_speed_kmh,
        lines=lines,
        amount_inr=round(result.bill.gnss_total, 2),
        fastag_amount_inr=round(result.bill.fastag_total, 2),
    )
