"""Toll zones and distance-based (GNSS) toll calculation.

Each toll plaza collects the fee for a stretch of highway (its tollable length).
Here that stretch is a *toll zone* on the route. When a vehicle's GPS track enters
a zone its entry point is registered, when it leaves the exit point is registered,
and it pays for the distance driven in between at that plaza's per-km rate
(fee / tollable length).

Under the National Highways Fee Amendment Rules, 2024, vehicles without a National
Permit pay nothing for the first 20 km a day in each direction under GNSS tolling.

For comparison, the FASTag total is what the vehicle would pay today: the full
single-journey fee at every plaza it drives through.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from gps_toll.models import Coordinate, Route, TollPlaza, Vehicle

GNSS_FREE_KM_PER_DAY = 20.0


@dataclass(frozen=True)
class TollZone:
    """The stretch of the route whose toll is collected by one plaza."""

    plaza: TollPlaza
    plaza_km: float
    start_km: float
    end_km: float

    @property
    def length_km(self) -> float:
        return self.end_km - self.start_km

    def contains(self, km: float) -> bool:
        return self.start_km <= km < self.end_km


def build_toll_zones(route: Route, plazas: Sequence[TollPlaza]) -> List[TollZone]:
    """Place each plaza's tollable stretch on the route, centred on the plaza.

    Where neighbouring stretches overlap, the overlap is split at its midpoint, and
    stretches are clipped to the ends of the route.
    """
    located = sorted(((route.locate(p.location), p) for p in plazas), key=lambda item: item[0])
    spans = [[km - p.tollable_km / 2, km + p.tollable_km / 2] for km, p in located]
    for (left_km, _), (right_km, _), left, right in zip(located, located[1:], spans, spans[1:]):
        if left[1] > right[0]:
            boundary = min(max((left[1] + right[0]) / 2, left_km), right_km)
            left[1] = right[0] = boundary

    zones = []
    for (km, plaza), (start, end) in zip(located, spans):
        start, end = max(start, 0.0), min(end, route.length_km)
        if end > start:
            zones.append(TollZone(plaza, km, start, end))
    return zones


def zone_at(zones: Sequence[TollZone], km: float) -> Optional[TollZone]:
    """Return the zone containing ``km``. ``zones`` must be sorted and not overlap."""
    i = bisect.bisect_right([z.start_km for z in zones], km) - 1
    if i >= 0 and zones[i].contains(km):
        return zones[i]
    return None


@dataclass(frozen=True)
class TollEvent:
    """An entry into or exit from a toll zone."""

    time_min: float
    position: Coordinate  # the GPS fix that registered the event
    km: float  # where on the route it happened


@dataclass(frozen=True)
class ZonePassage:
    zone: TollZone
    entry: TollEvent
    exit: TollEvent

    @property
    def distance_km(self) -> float:
        return self.exit.km - self.entry.km


@dataclass(frozen=True)
class ChargeLine:
    passage: ZonePassage
    rate_per_km: float
    free_km: float

    @property
    def chargeable_km(self) -> float:
        return max(0.0, self.passage.distance_km - self.free_km)

    @property
    def amount(self) -> float:
        return self.chargeable_km * self.rate_per_km


@dataclass(frozen=True)
class TollBill:
    lines: Tuple[ChargeLine, ...]
    fastag_fees: Tuple[Tuple[TollPlaza, float], ...]

    @property
    def tolled_km(self) -> float:
        return sum(line.passage.distance_km for line in self.lines)

    @property
    def free_km(self) -> float:
        return sum(line.free_km for line in self.lines)

    @property
    def gnss_total(self) -> float:
        return sum(line.amount for line in self.lines)

    @property
    def fastag_total(self) -> float:
        return sum(fee for _, fee in self.fastag_fees)

    @property
    def saving(self) -> float:
        return self.fastag_total - self.gnss_total


def calculate_bill(
    passages: Sequence[ZonePassage],
    plazas_passed: Sequence[TollPlaza],
    vehicle: Vehicle,
    rate_override: Optional[float] = None,
    free_km_per_day: float = GNSS_FREE_KM_PER_DAY,
) -> TollBill:
    """Charge each zone passage at its plaza's per-km rate (or ``rate_override``)."""
    if rate_override is not None and rate_override < 0:
        raise ValueError(f"rate_override must not be negative, got {rate_override}")

    allowance = 0.0 if vehicle.national_permit else free_km_per_day
    lines = []
    for passage in passages:
        if rate_override is None:
            rate = passage.zone.plaza.rate_per_km(vehicle.vehicle_class)
        else:
            rate = rate_override
        free = min(allowance, passage.distance_km)
        allowance -= free
        lines.append(ChargeLine(passage, rate, free))

    fastag = tuple((plaza, plaza.fee(vehicle.vehicle_class)) for plaza in plazas_passed)
    return TollBill(tuple(lines), fastag)
