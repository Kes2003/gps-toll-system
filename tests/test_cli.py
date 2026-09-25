import random

import pytest

import main
from gps_toll.simulation import load_default_route, load_default_zones, simulate
from gps_toll.visualization import save_figures, save_route_map


@pytest.fixture(scope="module")
def results():
    return simulate(traffic=4, rng=random.Random(9))


def test_figures_are_saved(tmp_path, results):
    paths = save_figures(load_default_route(), load_default_zones(), results, tmp_path / "plots")

    assert [p.name for p in paths] == ["route.png", "traffic.png", "tolls.png"]
    assert all(p.stat().st_size > 10_000 for p in paths)


def test_map_shows_zones_plazas_and_vehicles(tmp_path, results):
    path = save_route_map(load_default_route(), load_default_zones(), results, tmp_path / "map.html", highlight=2)
    html = path.read_text(encoding="utf-8")

    assert "Kaniyur toll zone" in html
    assert "Electronic City (elevated) toll plaza" in html
    for result in results:
        assert result.vehicle.registration in html


def test_cli_single_trip(tmp_path, capsys):
    db = tmp_path / "trips.db"
    main.main(["--cli", "--seed", "1", "--vehicle", "bus", "--from", "Salem", "--to", "Hosur",
               "--db", str(db), "--map-file", str(tmp_path / "map.html")])

    output = capsys.readouterr().out
    assert "Bus / Truck (2 axles)" in output
    assert "Trip: Salem -> Hosur" in output
    assert "GNSS toll (distance based)" in output
    assert "Saved 1 trip(s)" in output
    assert (tmp_path / "map.html").exists()


def test_cli_traffic_history_and_plots(tmp_path, capsys):
    db = tmp_path / "trips.db"
    main.main(["--cli", "--seed", "2", "--traffic", "5", "--db", str(db), "--map-file", str(tmp_path / "map.html"),
               "--plots-dir", str(tmp_path / "plots")])
    output = capsys.readouterr().out
    assert "All vehicles (6)" in output
    assert (tmp_path / "plots" / "traffic.png").exists()

    main.main(["--history", "3", "--db", str(db)])
    history = capsys.readouterr().out
    assert "6 trips in total" in history
    assert len([line for line in history.splitlines() if " -> " in line]) == 3


def test_cli_no_db(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    main.main(["--cli", "--seed", "3", "--no-db", "--map-file", "map.html"])

    assert "Saved" not in capsys.readouterr().out
    assert not (tmp_path / "trips.db").exists()


def test_national_permit_follows_vehicle_class_unless_set():
    assert main.parse_args(["--vehicle", "mav"]).national_permit is None
    assert main.parse_args(["--vehicle", "mav", "--no-national-permit"]).national_permit is False
    assert main.parse_args(["--national-permit"]).national_permit is True


@pytest.mark.parametrize("argv", [
    ["--from", "Hosur", "--to", "Salem"],
    ["--from", "Chennai"],
    ["--speed", "0"],
    ["--rate", "-1"],
    ["--traffic", "-2"],
    ["--gps-interval", "0"],
])
def test_cli_rejects_bad_arguments(argv):
    with pytest.raises(SystemExit):
        main.parse_args(argv)
