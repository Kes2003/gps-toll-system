"""Download the Coimbatore -> Bangalore road route and save it as gps_toll/data/route.json.

The route comes from the public OSRM demo server (road data (c) OpenStreetMap
contributors, ODbL). Via points at three toll plazas keep it on the main NH544 /
NH44 corridor through Salem and Krishnagiri. The geometry is simplified with the
Douglas-Peucker algorithm to keep the file small.

    python scripts/fetch_route.py
"""

from __future__ import annotations

import json
import math
import urllib.request
from datetime import date
from pathlib import Path

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
OUTPUT = Path(__file__).resolve().parent.parent / "gps_toll" / "data" / "route.json"

# (lat, lon, bearing, bearing range). Bearings stop OSRM snapping a via point to
# the opposite carriageway, which would add a U-turn.
WAYPOINTS = [
    (11.0168, 76.9558, None, None),  # Coimbatore
    (11.51321, 77.92400, 60, 80),  # Vaiguntham toll plaza, NH544
    (11.71987, 78.07325, 330, 80),  # Omalur toll plaza, NH44
    (12.54450, 78.20107, 330, 90),  # Krishnagiri toll plaza, NH44
    (12.9716, 77.5946, None, None),  # Bangalore
]

# Towns along the corridor where vehicles can join or leave the highway.
PLACES = [
    ("Coimbatore", 11.0168, 76.9558),
    ("Avinashi", 11.1929, 77.2685),
    ("Perundurai", 11.2757, 77.5874),
    ("Kumarapalayam", 11.4402, 77.7154),
    ("Salem", 11.6643, 78.1460),
    ("Dharmapuri", 12.1277, 78.1579),
    ("Krishnagiri", 12.5186, 78.2137),
    ("Hosur", 12.7409, 77.8253),
    ("Bangalore", 12.9716, 77.5946),
]

SIMPLIFY_TOLERANCE_M = 15.0
EARTH_RADIUS_M = 6_371_008.8


def to_xy(lat: float, lon: float, lat0: float) -> tuple:
    return (
        math.radians(lon) * EARTH_RADIUS_M * math.cos(math.radians(lat0)),
        math.radians(lat) * EARTH_RADIUS_M,
    )


def point_segment_distance(p, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def simplify(points: list, tolerance_m: float) -> list:
    """Douglas-Peucker simplification of a list of (lat, lon) points."""
    lat0 = points[0][0]
    xy = [to_xy(lat, lon, lat0) for lat, lon in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        worst, worst_index = 0.0, None
        for i in range(first + 1, last):
            d = point_segment_distance(xy[i], xy[first], xy[last])
            if d > worst:
                worst, worst_index = d, i
        if worst_index is not None and worst > tolerance_m:
            keep[worst_index] = True
            stack += [(first, worst_index), (worst_index, last)]
    return [p for p, k in zip(points, keep) if k]


def nearest_on_route(points: list, lat: float, lon: float) -> tuple:
    """Return (distance in metres, snapped (lat, lon)) of the closest point on the route."""
    p = to_xy(lat, lon, lat)
    best = (math.inf, None)
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        a, b = to_xy(lat1, lon1, lat), to_xy(lat2, lon2, lat)
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
        d = math.dist(p, (a[0] + t * dx, a[1] + t * dy))
        if d < best[0]:
            best = (d, (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1)))
    return best


def format_route_json(data: dict) -> str:
    """JSON with one route point per line, so changes to the route diff cleanly."""
    lines = ["{"]
    for key, value in data.items():
        if key != "points":
            lines.append(f"  {json.dumps(key)}: {json.dumps(value)},")
    lines.append('  "points": [')
    lines.append(",\n".join(f"    [{lat}, {lon}]" for lat, lon in data["points"]))
    lines.append("  ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


def fetch_route() -> dict:
    coords = ";".join(f"{lon},{lat}" for lat, lon, _, _ in WAYPOINTS)
    bearings = ";".join("" if b is None else f"{b},{r}" for _, _, b, r in WAYPOINTS)
    radiuses = ";".join("" if b is None else "100" for _, _, b, _ in WAYPOINTS)
    url = (
        f"{OSRM_URL}{coords}?overview=full&geometries=geojson&continue_straight=true"
        f"&bearings={bearings}&radiuses={radiuses}"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "gps-toll-system route fetcher"})
    with urllib.request.urlopen(request, timeout=60) as response:
        data = json.load(response)
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data}")
    return data["routes"][0]


def main() -> None:
    route = fetch_route()
    points = [(round(lat, 6), round(lon, 6)) for lon, lat in route["geometry"]["coordinates"]]
    simplified = simplify(points, SIMPLIFY_TOLERANCE_M)

    places = []
    for name, lat, lon in PLACES:
        distance_m, (snap_lat, snap_lon) = nearest_on_route(simplified, lat, lon)
        places.append({"name": name, "lat": round(snap_lat, 6), "lon": round(snap_lon, 6)})
        print(f"{name:14s} {distance_m / 1000:5.2f} km from the town centre")

    output = {
        "name": "Coimbatore - Bangalore (NH544 / NH44)",
        "source": "OSRM (router.project-osrm.org), road data (c) OpenStreetMap contributors, ODbL",
        "retrieved": date.today().isoformat(),
        "osrm_distance_km": round(route["distance"] / 1000, 2),
        "places": places,
        "points": [[lat, lon] for lat, lon in simplified],
    }
    OUTPUT.write_text(format_route_json(output), encoding="utf-8")
    print(f"{len(points)} points simplified to {len(simplified)}; {route['distance'] / 1000:.1f} km")
    print(f"Saved {OUTPUT}")


if __name__ == "__main__":
    main()
