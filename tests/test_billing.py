import random

from gps_toll.billing import issue_receipt
from gps_toll.simulation import SimulationSettings, simulate


def test_receipt_matches_trip():
    (result,) = simulate(speed_kmh=60, settings=SimulationSettings(gps_noise_m=0), rng=random.Random(1))
    receipt = issue_receipt(result, random.Random(1))

    assert receipt.amount_inr == round(result.bill.gnss_total, 2)
    assert receipt.fastag_amount_inr == result.bill.fastag_total
    assert receipt.free_km == 20
    assert len(receipt.lines) == len(result.bill.lines)
    assert 1_000_000_000 <= receipt.transaction_id <= 9_999_999_999

    text = receipt.as_text()
    assert f"Amount Paid: {receipt.amount_inr:.2f} INR" in text
    assert "Kaniyur" in text
    assert result.vehicle.registration in text
