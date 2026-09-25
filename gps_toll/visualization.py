"""Plots and maps of simulated trips."""

from __future__ import annotations

import html
import math
from pathlib import Path
from typing import List, Sequence, Union

import folium
from matplotlib.figure import Figure

from gps_toll.models import Route
from gps_toll.rates import VEHICLE_CLASSES
from gps_toll.simulation import TripResult, format_duration
from gps_toll.tolling import TollZone

DEFAULT_MAP_FILE = "car_path_map.html"

# Chart colours: blue marks your vehicle / the GNSS charge, orange the toll zones /
# FASTag fees, gray everything else.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
ROAD = "#c3c2b7"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

# Gap left between neighbouring toll zones so they read as separate stretches.
ZONE_GAP_KM = 0.6
# Only every n-th GPS fix is drawn on the map, to keep the HTML file small.
MAP_TRACK_STEP = 6


def _style_axes(ax) -> None:
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(colors=INK_SECONDARY, length=0)
    ax.xaxis.label.set_color(INK_SECONDARY)
    ax.yaxis.label.set_color(INK_SECONDARY)
    ax.title.set_color(INK)


def _new_figure(width: float, height: float) -> Figure:
    return Figure(figsize=(width, height), facecolor=SURFACE)


def _route_section(route: Route, start_km: float, end_km: float) -> List[tuple]:
    """Points along the route between two distances, following its bends."""
    inner = [p for p, km in zip(route.points, route.cumulative_km) if start_km < km < end_km]
    return [route.point_at(start_km)] + inner + [route.point_at(end_km)]


def _label_offset(route: Route, km: float, side: int, distance_pt: float = 10) -> dict:
    """Annotation settings that put a label beside the road, on its left (side=1) or right (side=-1)."""
    (lat1, lon1), (lat2, lon2) = route.point_at(km - 2), route.point_at(km + 2)
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    dy = lat2 - lat1
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length * side, dx / length * side
    return {
        "xytext": (nx * distance_pt, ny * distance_pt),
        "ha": "left" if nx > 0.3 else "right" if nx < -0.3 else "center",
        "va": "bottom" if ny > 0.3 else "top" if ny < -0.3 else "center",
    }


def create_route_figure(route: Route, zones: Sequence[TollZone], results: Sequence[TripResult], highlight: int = 0) -> Figure:
    """The road, its toll zones and plazas, and the highlighted vehicle's trip."""
    fig = _new_figure(9, 7.5)
    ax = fig.add_subplot()
    _style_axes(ax)

    lats, lons = zip(*route.points)
    ax.plot(lons, lats, color=ROAD, linewidth=6, solid_capstyle="round", label="Road", zorder=1)
    for i, zone in enumerate(zones):
        section = _route_section(route, zone.start_km + ZONE_GAP_KM / 2, zone.end_km - ZONE_GAP_KM / 2)
        z_lats, z_lons = zip(*section)
        ax.plot(z_lons, z_lats, color=ORANGE, linewidth=6, label="Toll zone" if i == 0 else None, zorder=2)

    if results:
        result = results[highlight]
        trip_lats, trip_lons = zip(*_route_section(route, result.trip.origin.km, result.trip.destination.km))
        ax.plot(trip_lons, trip_lats, color=BLUE, linewidth=2, label=f"Trip of {result.vehicle.registration}", zorder=3)

    for zone in zones:
        lat, lon = route.point_at(zone.plaza_km)
        ax.scatter(lon, lat, marker="s", s=36, color=INK, edgecolors=SURFACE, linewidths=2, zorder=4)
        ax.annotate(zone.plaza.name, (lon, lat), textcoords="offset points", fontsize=8, color=INK,
                    **_label_offset(route, zone.plaza_km, side=1))

    for place in route.places:
        lat, lon = route.point_at(place.km)
        ax.scatter(lon, lat, s=30, color=SURFACE, edgecolors=MUTED, linewidths=1.5, zorder=4)
        ax.annotate(place.name, (lon, lat), textcoords="offset points", fontsize=8, color=MUTED, style="italic",
                    **_label_offset(route, place.km, side=-1))

    ax.scatter([], [], marker="s", s=36, color=INK, label="Toll plaza")
    ax.scatter([], [], s=30, color=SURFACE, edgecolors=MUTED, linewidths=1.5, label="Town")

    mid_lat = (min(lats) + max(lats)) / 2
    ax.set_aspect(1 / math.cos(math.radians(mid_lat)))
    ax.set_title(f"{route.name}: toll zones", loc="left", fontsize=12)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.legend(loc="lower right", fontsize=8, frameon=False, labelcolor=INK_SECONDARY)
    fig.tight_layout()
    return fig


def create_traffic_figure(route: Route, zones: Sequence[TollZone], results: Sequence[TripResult], highlight: int = 0) -> Figure:
    """Time-distance diagram: every vehicle's position along the route over time."""
    fig = _new_figure(9, 6.5)
    ax = fig.add_subplot()
    _style_axes(ax)
    ax.grid(False, axis="x")

    for i, zone in enumerate(zones):
        ax.axhspan(zone.start_km + ZONE_GAP_KM, zone.end_km - ZONE_GAP_KM, color=ORANGE, alpha=0.1, linewidth=0,
                   label="Toll zone" if i == 0 else None, zorder=0)

    others = [r for i, r in enumerate(results) if i != highlight]
    for i, result in enumerate(others):
        hours = [p.time_min / 60 for p in result.track]
        ax.plot(hours, [p.km for p in result.track], color=ROAD, linewidth=1,
                label="Other traffic" if i == 0 else None, zorder=1)
    if results:
        result = results[highlight]
        ax.plot([p.time_min / 60 for p in result.track], [p.km for p in result.track], color=BLUE, linewidth=2,
                solid_capstyle="round", label=result.vehicle.registration, zorder=2)

    right = ax.get_xlim()[1]
    for zone in zones:
        ax.text(right, (zone.start_km + zone.end_km) / 2, f" {zone.plaza.name}", va="center", ha="left",
                fontsize=7, color=INK_SECONDARY, clip_on=False)

    ax.set_yticks([p.km for p in route.places])
    ax.set_yticklabels([p.name for p in route.places], fontsize=8)
    ax.set_ylim(0, route.length_km)
    ax.set_xlim(left=0)
    ax.set_xlabel("Hours since the first departure")
    ax.set_title("Vehicles on the highway (distance travelled over time)", loc="left", fontsize=12)
    ax.legend(loc="upper left", fontsize=8, frameon=False, labelcolor=INK_SECONDARY)
    fig.tight_layout()
    return fig


def create_toll_figure(result: TripResult) -> Figure:
    """Per plaza: the GNSS distance-based charge next to the full FASTag plaza fee."""
    gnss = {line.passage.zone.plaza.name: line.amount for line in result.bill.lines}
    fastag = {plaza.name: fee for plaza, fee in result.bill.fastag_fees}
    names = [line.passage.zone.plaza.name for line in result.bill.lines]
    names += [name for name in fastag if name not in gnss]

    fig = _new_figure(9, max(3.0, 0.5 * len(names) + 1.6))
    ax = fig.add_subplot()
    _style_axes(ax)
    ax.grid(False, axis="y")

    bar = 0.3
    positions = range(len(names))
    ax.barh([y - bar / 2 - 0.02 for y in positions], [gnss.get(n, 0) for n in names], height=bar,
            color=BLUE, label=f"GNSS, distance based ({result.bill.gnss_total:.2f} INR)")
    ax.barh([y + bar / 2 + 0.02 for y in positions], [fastag.get(n, 0) for n in names], height=bar,
            color=ORANGE, label=f"FASTag, full plaza fee ({result.bill.fastag_total:.2f} INR)")

    free = {line.passage.zone.plaza.name: line.free_km for line in result.bill.lines if line.free_km}
    for y, name in enumerate(names):
        if name in free:
            ax.annotate(f"{free[name]:.1f} km free", (gnss[name], y - bar / 2 - 0.02), textcoords="offset points",
                        xytext=(6, 0), va="center", fontsize=8, color=MUTED)

    ax.set_yticks(list(positions))
    ax.set_yticklabels(names, fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("Toll (INR)")
    ax.set_title(
        f"Toll by plaza for {result.vehicle.registration}, {result.trip.origin.name} -> {result.trip.destination.name}",
        loc="left", fontsize=12,
    )
    ax.legend(loc="lower right", fontsize=8, frameon=False, labelcolor=INK_SECONDARY)
    fig.tight_layout()
    return fig


def _plaza_popup(zone: TollZone) -> str:
    plaza = zone.plaza
    rows = "".join(
        f"<tr><td>{html.escape(vc.name)}</td><td style='text-align:right'>{plaza.fee(vc):.0f}</td>"
        f"<td style='text-align:right'>{plaza.rate_per_km(vc):.2f}</td></tr>"
        for vc in VEHICLE_CLASSES.values()
    )
    return (
        f"<b>{html.escape(plaza.name)} toll plaza</b> ({html.escape(plaza.nh)})<br>"
        f"{html.escape(plaza.stretch)}<br>"
        f"Tollable length {plaza.tollable_km:.1f} km, fees from {html.escape(plaza.fee_effective)}<br>"
        f"Zone on this route: km {zone.start_km:.1f} - {zone.end_km:.1f}"
        f"<table><tr><th>Vehicle</th><th>Fee (INR)</th><th>INR/km</th></tr>{rows}</table>"
    )


def create_route_map(route: Route, zones: Sequence[TollZone], results: Sequence[TripResult], highlight: int = 0) -> folium.Map:
    """Interactive Leaflet map: toll zones, plazas, towns and each vehicle's GPS track."""
    route_map = folium.Map(location=route.point_at(route.length_km / 2), zoom_start=8)

    folium.PolyLine(route.points, color=ROAD, weight=7, opacity=0.8, tooltip=route.name).add_to(route_map)
    for zone in zones:
        section = _route_section(route, zone.start_km + ZONE_GAP_KM / 2, zone.end_km - ZONE_GAP_KM / 2)
        folium.PolyLine(
            section, color=ORANGE, weight=7, opacity=0.9,
            tooltip=f"{zone.plaza.name} toll zone", popup=folium.Popup(_plaza_popup(zone), max_width=360),
        ).add_to(route_map)
        folium.Marker(
            zone.plaza.location, tooltip=f"{zone.plaza.name} toll plaza",
            popup=folium.Popup(_plaza_popup(zone), max_width=360), icon=folium.Icon(color="orange", icon="road"),
        ).add_to(route_map)

    for place in route.places:
        folium.CircleMarker(route.point_at(place.km), radius=5, color=MUTED, fill=True, fill_color="white",
                            fill_opacity=1, tooltip=place.name).add_to(route_map)

    order = [highlight] + [i for i in range(len(results)) if i != highlight]
    for i in order:
        result = results[i]
        mine = i == highlight
        vehicle = result.vehicle
        layer = folium.FeatureGroup(name=f"{vehicle.registration} ({vehicle.vehicle_class.name})", show=mine)
        track = [p.gps for p in result.track[::MAP_TRACK_STEP]] + [result.track[-1].gps]
        folium.PolyLine(
            track, color=BLUE if mine else INK_SECONDARY, weight=3 if mine else 2, opacity=1,
            tooltip=f"{vehicle.registration}: {result.trip.origin.name} -> {result.trip.destination.name}, "
                    f"GNSS toll {result.bill.gnss_total:.2f} INR",
        ).add_to(layer)
        for line in result.bill.lines:
            passage = line.passage
            for event, label, fill in ((passage.entry, "Entered", BLUE), (passage.exit, "Left", "white")):
                text = (f"{vehicle.registration}: {label} {passage.zone.plaza.name} zone at km {event.km:.1f}, "
                        f"t = {format_duration(event.time_min)}")
                folium.CircleMarker(event.position, radius=5, color=BLUE, weight=2, fill=True, fill_color=fill,
                                    fill_opacity=1, tooltip=text).add_to(layer)
        layer.add_to(route_map)

    folium.LayerControl(collapsed=True).add_to(route_map)
    lats, lons = zip(*route.points)
    route_map.fit_bounds([(min(lats), min(lons)), (max(lats), max(lons))])
    return route_map


def save_route_map(
    route: Route,
    zones: Sequence[TollZone],
    results: Sequence[TripResult],
    path: Union[str, Path] = DEFAULT_MAP_FILE,
    highlight: int = 0,
) -> Path:
    """Save the trip map as an HTML file and return its absolute path."""
    path = Path(path).resolve()
    create_route_map(route, zones, results, highlight).save(str(path))
    return path


def save_figures(
    route: Route,
    zones: Sequence[TollZone],
    results: Sequence[TripResult],
    directory: Union[str, Path],
    highlight: int = 0,
) -> List[Path]:
    """Save the route, traffic and toll figures as PNG files in ``directory``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    figures = {
        "route.png": create_route_figure(route, zones, results, highlight),
        "traffic.png": create_traffic_figure(route, zones, results, highlight),
        "tolls.png": create_toll_figure(results[highlight]),
    }
    paths = []
    for name, figure in figures.items():
        path = directory / name
        figure.savefig(path, dpi=150, facecolor=SURFACE)
        paths.append(path)
    return paths
