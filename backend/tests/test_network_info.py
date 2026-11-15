"""Settings > Devices' network details: the IP address of devices added by
it (TVs, ratgdo, Kasa), found from the MAC address for brands whose cloud
gives only that (Cync: neighbors.py), and types and brands as written."""

import json

from playwright.sync_api import expect

from app import neighbors
from app.models import Device
from tests import test_ui as _ui

ARP_TEXT = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.57     0x1         0x2         34:13:43:92:94:8d     *        eth0
192.168.1.60     0x1         0x0         00:00:00:00:00:00     *        eth0
192.168.1.61     0x1         0x0         34:13:43:00:00:01     *        eth0
"""


def test_the_neighbour_table_is_read():
    table = neighbors.read_table(ARP_TEXT)
    assert table == {"34:13:43:92:94:8D": "192.168.1.57"}  # incomplete ones skipped


def add(db, owner, make_device, integration, external_id, caps, kind="light"):
    device = db.get(
        Device, make_device(owner.home_id, device_type=kind, name=integration)
    )
    device.integration, device.external_id = integration, external_id
    device.capabilities = json.dumps(caps)
    db.commit()
    return device.id


def test_ip_addresses_by_brand(
    client, db, owner, login, make_device, monkeypatch, tmp_path
):
    arp = tmp_path / "arp"
    arp.write_text(ARP_TEXT)
    monkeypatch.setattr(neighbors, "ARP", arp)
    monkeypatch.setattr(neighbors, "_read_at", -1e9)  # read it afresh
    swept = []
    monkeypatch.setattr(neighbors, "_sweep_soon", lambda now: swept.append(now))
    ids = {
        "cync": add(
            db, owner, make_device, "cync", "77-1", {"mac": "34:13:43:92:94:8D"}
        ),
        "lost": add(
            db, owner, make_device, "cync", "77-2", {"mac": "34:13:43:00:00:09"}
        ),
        "kasa": add(
            db, owner, make_device, "kasa", "k1", {"host": "192.168.1.20"}, "plug"
        ),
        "lg_tv": add(
            db,
            owner,
            make_device,
            "lg_tv",
            "192.168.1.30",
            {"mac": "AA:BB:CC:00:00:01"},
            "tv",
        ),
        "roku_tv": add(db, owner, make_device, "roku_tv", "192.168.1.31", {}, "tv"),
        "ratgdo": add(
            db, owner, make_device, "ratgdo", "192.168.1.80", {}, "garage_door"
        ),
    }
    assert login(client, owner).status_code == 200
    out = {
        d["id"]: d["network"]
        for d in client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    }
    assert out[ids["cync"]] == {"ip": "192.168.1.57", "mac": "34:13:43:92:94:8D"}
    assert out[ids["lost"]] == {"ip": None, "mac": "34:13:43:00:00:09"}
    assert swept  # a miss asks the network (when the server's background work runs)
    assert out[ids["kasa"]]["ip"] == "192.168.1.20"
    assert out[ids["lg_tv"]]["ip"] == "192.168.1.30"
    assert out[ids["roku_tv"]]["ip"] == "192.168.1.31"
    assert out[ids["ratgdo"]]["ip"] == "192.168.1.80"


def test_no_sweep_in_tests_or_without_a_table(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(neighbors, "sweep", lambda network: sent.append(network))
    monkeypatch.setattr(neighbors, "_swept_at", -1e9)
    neighbors._sweep_soon(0.0)  # REFRESH_SECONDS is 0 in tests
    monkeypatch.setattr(neighbors, "ARP", tmp_path / "none")
    assert neighbors.ip_for("34:13:43:92:94:8D") is None
    assert sent == []


def test_ui_type_and_brand_as_written(open_page, db, owner, make_device):
    heater = add(db, owner, make_device, "rheem_econet", "h1", {}, "water_heater")
    page = open_page()
    _ui.ui_login(page, owner)
    panel = _ui.go_settings(page, "devices")
    row = panel.locator(f'[data-testid="device-row"][data-device-id="{heater}"]')
    expect(row.locator(".device-kind")).to_contain_text("Water Heater")
    expect(panel.get_by_test_id("device-filter")).to_contain_text("Water Heaters")
    row.get_by_test_id("device-info").click()
    info = page.get_by_test_id("device-info-panel")
    expect(info).to_contain_text("Water Heater")
    expect(info).to_contain_text("Rheem EcoNet")
    expect(info).to_contain_text("EcoNet cloud")
