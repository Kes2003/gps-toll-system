"""Core data types: the road route, toll plazas and vehicles."""

from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

import geopy.distance

from gps_toll.rates import DEFAULT_VEHICLE_CLASS, VehicleClass

# (latitude, longitude) in decimal degrees.
Coordinate = Tuple[float, float]

EARTH_RADIUS_KM = 6371.0088


def calculate_distance(point1: Coordinate, point2: Coordinate) -> float:
    """Return the geodesic distance between two coordinates in kilometres."""
    return geopy.distance.distance(point1, point2).km


def _to_xy(point: Coordinate, lat0: float) -> Tuple[float, float]:
    """Project a coordinate onto a local flat plane (km), accurate over a few km around ``lat0``."""
    lat, lon = point
    return (
        math.radians(lon) * EARTH_RADIUS_KM * math.cos(math.radians(lat0)),
        math.radians(lat) * EARTH_RADIUS_KM,
    )


@dataclass(frozen=True)
class Place:
    """A named point on a route, such as a town where vehicles join or leave the highway."""

    name: str
    km: float


class Route:
    """A road as a polyline of GPS points, measured in km from its start."""

    def __init__(
        self,
        points: Sequence[Coordinate],
        name: str = "Route",
        places: Sequence[Tuple[str, Coordinate]] = (),
    ) -> None:
        if len(points) < 2:
            raise ValueError("a route needs at least two points")
        self.name = name
        self.points: List[Coordinate] = [(float(lat), float(lon)) for lat, lon in points]
        self.cumulative_km = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cumulative_km.append(self.cumulative_km[-1] + calculate_distance(a, b))
        self.places = sorted((Place(n, self.locate(p)) for n, p in places), key=lambda p: p.km)

    @classmethod
    def straight(cls, start: Coordinate, end: Coordinate, start_name: str = "Start", end_name: str = "Destination") -> "Route":
        """A straight road between two points."""
        return cls([start, end], f"{start_name} - {end_name}", [(start_name, start), (end_name, end)])

    @classmethod
    def from_json(cls, path: Union[str, Path]) -> "Route":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        places = [(p["name"], (p["lat"], p["lon"])) for p in data.get("places", [])]
        return cls([tuple(p) for p in data["points"]], data.get("name", "Route"), places)

    @property
    def length_km(self) -> float:
        return self.cumulative_km[-1]

    @property
    def start(self) -> Coordinate:
        return self.points[0]

    @property
    def end(self) -> Coordinate:
        return self.points[-1]

    def place(self, name: str) -> Place:
        for place in self.places:
            if place.name.lower() == name.lower():
                return place
        raise KeyError(f"unknown place {name!r}; choose from {', '.join(p.name for p in self.places)}")

    def _segment_index(self, km: float) -> int:
        i = bisect.bisect_right(self.cumulative_km, km) - 1
        return min(max(i, 0), len(self.points) - 2)

    def point_at(self, km: float) -> Coordinate:
        """Return the point ``km`` along the route (clamped to the route's ends)."""
        km = min(max(km, 0.0), self.length_km)
        i = self._segment_index(km)
        segment_km = self.cumulative_km[i + 1] - self.cumulative_km[i]
        fraction = 0.0 if segment_km == 0 else (km - self.cumulative_km[i]) / segment_km
        (lat1, lon1), (lat2, lon2) = self.points[i], self.points[i + 1]
        return (lat1 + fraction * (lat2 - lat1), lon1 + fraction * (lon2 - lon1))

    def locate(self, position: Coordinate, near_km: Optional[float] = None, window_km: float = 2.0) -> float:
        """Map-match a GPS position: return the km along the route of the nearest point on it.

        With ``near_km`` only the part of the route within ``window_km`` of it is searched,
        which is faster and stops a fix jumping to a different part of a winding road.
        """
        if near_km is None:
            first, last = 0, len(self.points) - 2
        else:
            first = self._segment_index(near_km - window_km)
            last = self._segment_index(near_km + window_km)

        p = _to_xy(position, position[0])
        best_distance, best_km = math.inf, 0.0
        for i in range(first, last + 1):
            a = _to_xy(self.points[i], position[0])
            b = _to_xy(self.points[i + 1], position[0])
            dx, dy = b[0] - a[0], b[1] - a[1]
            length2 = dx * dx + dy * dy
            t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
            distance = math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))
            if distance < best_distance:
                best_distance = distance
                best_km = self.cumulative_km[i] + t * (self.cumulative_km[i + 1] - self.cumulative_km[i])
        return best_km


@dataclass(frozen=True, eq=False)
class TollPlaza:
    """A toll plaza and the fees it charges.

    ``fees`` holds the single-journey fee (INR) for each vehicle class key and covers
    ``tollable_km`` of highway, so a vehicle's per-km rate here is fee / tollable_km.
    """

    name: str
    location: Coordinate
    tollable_km: float
    fees: Dict[str, float] = field(default_factory=dict)
    nh: str = ""
    stretch: str = ""
    fee_effective: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        if self.tollable_km <= 0:
            raise ValueError(f"tollable_km must be positive, got {self.tollable_km}")

    def fee(self, vehicle_class: VehicleClass) -> float:
        """Single-journey fee. Falls back to the class's representative per-km rate if not published."""
        if vehicle_class.key in self.fees:
            return float(self.fees[vehicle_class.key])
        return round(vehicle_class.rate_per_km * self.tollable_km)

    def rate_per_km(self, vehicle_class: VehicleClass) -> float:
        return self.fee(vehicle_class) / self.tollable_km


def load_toll_plazas(path: Union[str, Path]) -> List[TollPlaza]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        TollPlaza(
            name=p["name"],
            location=tuple(p["location"]),
            tollable_km=p["tollable_km"],
            fees=dict(p.get("fees", {})),
            nh=p.get("nh", ""),
            stretch=p.get("stretch", ""),
            fee_effective=p.get("fee_effective", ""),
            source=p.get("source", ""),
        )
        for p in data["plazas"]
    ]


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: int
    registration: str
    vehicle_class: VehicleClass = DEFAULT_VEHICLE_CLASS
    cruise_speed_kmh: float = 80.0
    # National Permit goods vehicles don't get the free daily GNSS distance.
    national_permit: bool = False

    def __post_init__(self) -> None:
        if self.cruise_speed_kmh <= 0:
            raise ValueError(f"cruise_speed_kmh must be positive, got {self.cruise_speed_kmh}")
