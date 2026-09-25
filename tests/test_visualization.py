from gps_toll.simulation import simulate_default_trip
from gps_toll.visualization import create_path_figure, save_route_map, split_track

import main


def test_split_track_joins_at_toll_entry_and_exit():
    result = simulate_default_trip(speed_kmh=70)
    before, tolled, after = split_track(result)

    assert before[-1] == tolled[0] == result.entry.position
    assert tolled[-1] == after[0] == result.exit.position
    assert len(before) + len(tolled) + len(after) == len(result.track) + 2


def test_path_figure_and_map(tmp_path):
    result = simulate_default_trip(speed_kmh=70)

    figure = create_path_figure(result)
    figure.savefig(tmp_path / "plot.png")
    assert (tmp_path / "plot.png").stat().st_size > 0

    map_path = save_route_map(result, tmp_path / "map.html")
    html = map_path.read_text(encoding="utf-8")
    assert "Toll Point 1" in html
    assert "Tolled section" in html


def test_cli_run(tmp_path, capsys):
    main.main(["--cli", "--seed", "1", "--map-file", str(tmp_path / "map.html")])

    output = capsys.readouterr().out
    assert "Total toll amount" in output
    assert "Transaction ID" in output
    assert (tmp_path / "map.html").exists()


def test_cli_vehicle_option(tmp_path, capsys):
    main.main(["--cli", "--speed", "80", "--vehicle", "bus", "--map-file", str(tmp_path / "map.html")])

    output = capsys.readouterr().out
    assert "Vehicle: Bus / Truck (2 axles)" in output
    assert "@ 5.08 INR/km" in output
