"""Plots and maps of a simulated trip."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple, Union

import folium
from matplotlib.figure import Figure

from gps_toll.models import Coordinate
from gps_toll.simulation import TripResult, format_duration

DEFAULT_MAP_FILE = "car_path_map.html"


def split_track(result: TripResult) -> Tuple[List[Coordinate], List[Coordinate], List[Coordinate]]:
    """Split the GPS track into the parts before, inside and after the tolled section.

    Neighbouring parts share their boundary point so they join up when drawn.
    """
    if result.entry is None or result.exit is None:
        return [p.position for p in result.track], [], []
    entry_km, exit_km = result.entry.odometer_km, result.exit.odometer_km
    before = [p.position for p in result.track if p.odometer_km <= entry_km]
    tolled = [p.position for p in result.track if entry_km <= p.odometer_km <= exit_km]
    after = [p.position for p in result.track if p.odometer_km >= exit_km]
    return before, tolled, after


def create_path_figure(result: TripResult) -> Figure:
    """Draw the car's path, toll points and the tolled section on a lat/lon plot."""
    highway = result.highway
    fig = Figure(figsize=(9, 7))
    ax = fig.add_subplot()

    ax.plot(
        [highway.start[1], highway.end[1]],
        [highway.start[0], highway.end[0]],
        color="lightgray", linewidth=8, label="Highway", zorder=1,
    )

    before, tolled, after = split_track(result)
    for segment, color, label in (
        (before, "tab:blue", "Car path"),
        (tolled, "tab:red", "Tolled section"),
        (after, "tab:blue", None),
    ):
        if len(segment) > 1:
            lats, lons = zip(*segment)
            ax.plot(lons, lats, color=color, linewidth=2.5, label=label, zorder=2)

    if result.toll_points:
        ax.scatter(
            [t.location[1] for t in result.toll_points],
            [t.location[0] for t in result.toll_points],
            marker="x", s=80, color="green", label="Toll points", zorder=3,
        )
        for toll in result.toll_points:
            ax.annotate(toll.name, (toll.location[1], toll.location[0]), textcoords="offset points", xytext=(8, -4))

    ax.scatter(highway.start[1], highway.start[0], s=60, color="orange", label=f"Start: {highway.start_name}", zorder=4)
    ax.scatter(highway.end[1], highway.end[0], s=60, color="purple", label=f"Destination: {highway.end_name}", zorder=4)

    for crossing, label, color in ((result.entry, "Toll entry", "black"), (result.exit, "Toll exit", "gold")):
        if crossing is not None:
            ax.scatter(
                crossing.position[1], crossing.position[0], s=50, color=color, edgecolors="black", zorder=5,
                label=f"{label}: {crossing.toll_point.name} ({format_duration(crossing.time_min)})",
            )

    ax.set_title("Car Path on the Highway with Toll Points")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(True)
    ax.legend(loc="upper left", fontsize="small")
    fig.tight_layout()
    return fig


def create_route_map(result: TripResult) -> folium.Map:
    """Build an interactive Leaflet map of the trip."""
    highway = result.highway
    route_map = folium.Map(location=highway.interpolate(0.5), zoom_start=8)

    folium.PolyLine([highway.start, highway.end], color="gray", weight=8, opacity=0.4, tooltip="Highway").add_to(route_map)

    before, tolled, after = split_track(result)
    for segment, color, tooltip in ((before, "blue", "Car path"), (tolled, "red", "Tolled section"), (after, "blue", "Car path")):
        if len(segment) > 1:
            folium.PolyLine(segment, color=color, weight=5, opacity=1, tooltip=tooltip).add_to(route_map)

    for toll in result.toll_points:
        folium.Circle(toll.location, radius=toll.radius_km * 1000, color="green", fill=True, fill_opacity=0.2).add_to(route_map)
        folium.Marker(toll.location, popup=toll.name, tooltip=toll.name, icon=folium.Icon(color="green")).add_to(route_map)

    folium.Marker(highway.start, popup=f"Start: {highway.start_name}", icon=folium.Icon(color="orange")).add_to(route_map)
    folium.Marker(highway.end, popup=f"Destination: {highway.end_name}", icon=folium.Icon(color="purple")).add_to(route_map)

    for crossing, label, color in ((result.entry, "Toll entry", "black"), (result.exit, "Toll exit", "darkred")):
        if crossing is not None:
            text = f"{label}: {crossing.toll_point.name} at {format_duration(crossing.time_min)}"
            folium.CircleMarker(
                crossing.position, radius=7, color=color, fill=True, fill_opacity=1, popup=text, tooltip=text,
            ).add_to(route_map)

    route_map.fit_bounds([highway.start, highway.end])
    return route_map


def save_route_map(result: TripResult, path: Union[str, Path] = DEFAULT_MAP_FILE) -> Path:
    """Save the trip map as an HTML file and return its absolute path."""
    path = Path(path).resolve()
    create_route_map(result).save(str(path))
    return path
