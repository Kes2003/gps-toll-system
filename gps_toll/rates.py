"""Vehicle classes and their representative per-km toll rates on Indian national highways.

The simulation charges each toll plaza's own published fee (see
``gps_toll/data/toll_plazas.json``). The per-km rates here are the fallback for a
plaza whose fee for a class isn't known, and describe typical rates.

They are based on the National Highways Fee (Determination of Rates and Collection)
Rules, 2008. Rule 4 sets base rates for 2007-08 on highways of four or more lanes;
Rule 5 revises them every April (3% a year plus 40% of the rise in the wholesale
price index). After those revisions a car pays about 1.50 INR/km, roughly 2.3 times
its 2007-08 base rate, and the other classes below are scaled by the same factor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class VehicleClass:
    key: str
    name: str
    base_rate_2007_per_km: float  # INR, NH Fee Rules 2008, Rule 4
    rate_per_km: float  # INR, representative current rate


VEHICLE_CLASSES: Dict[str, VehicleClass] = {
    vc.key: vc
    for vc in (
        VehicleClass("car", "Car / Jeep / Van", 0.65, 1.50),
        VehicleClass("lcv", "LCV / LGV / Mini bus", 1.05, 2.42),
        VehicleClass("bus", "Bus / Truck (2 axles)", 2.20, 5.08),
        VehicleClass("3axle", "3-axle commercial vehicle", 2.40, 5.54),
        VehicleClass("mav", "Multi-axle vehicle (4-6 axles)", 3.45, 7.96),
        VehicleClass("oversized", "Oversized vehicle (7+ axles)", 4.20, 9.69),
    )
}

DEFAULT_VEHICLE_CLASS = VEHICLE_CLASSES["car"]
