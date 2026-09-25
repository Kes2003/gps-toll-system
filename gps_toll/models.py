"""Core data types for the GPS toll simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import geopy.distance

# (latitude, longitude) in decimal degrees.
Coordinate = Tuple[float, float]


def calculate_distance(point1: Coordinate, point2: Coordinate) -> float:
    """Return the geodesic distance between two coordinates in kilometres."""
    return geopy.distance.distance(point1, point2).km


@dataclass(frozen=True)
class Highway:
    """A straight road between two named places."""

    start: Coordinate
    end: Coordinate
    start_name: str = "Start"
    end_name: str = "Destination"

    @property
    def length_km(self) -> float:
        return calculate_distance(self.start, self.end)

    def interpolate(self, fraction: float) -> Coordinate:
        """Return the point that lies ``fraction`` (0..1) of the way along the highway."""
        fraction = min(max(fraction, 0.0), 1.0)
        start_lat, start_lon = self.start
        end_lat, end_lon = self.end
        return (
            start_lat + fraction * (end_lat - start_lat),
            start_lon + fraction * (end_lon - start_lon),
        )


@dataclass(frozen=True)
class TollPoint:
    """A toll gantry. A vehicle is inside its zone when within ``radius_km`` of ``location``."""

    name: str
    location: Coordinate
    radius_km: float = 1.0

    def contains(self, position: Coordinate) -> bool:
        return calculate_distance(position, self.location) <= self.radius_km


@dataclass(frozen=True)
class Car:
    car_id: int
    speed_kmh: float
    vehicle_type: str = "Car"

    def __post_init__(self) -> None:
        if self.speed_kmh <= 0:
            raise ValueError(f"speed_kmh must be positive, got {self.speed_kmh}")


@dataclass(frozen=True)
class TollCrossing:
    """Recorded when the car's GPS position first falls inside a toll zone."""

    toll_point: TollPoint
    time_min: float
    position: Coordinate
    odometer_km: float
