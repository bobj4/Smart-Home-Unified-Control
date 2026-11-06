"""Find TVs on the home network: only small private networks, and each kind
of TV is told apart. The network is never really searched here."""

import ipaddress

import pytest
from playwright.sync_api import expect

from app import tv_scan
from app.routes import tv_scan as scan_route
from tests import test_ui as _ui


def test_network_rules():
    assert str(tv_scan.network_for("192.168.1.0/24", None)) == "192.168.1.0/24"
    assert str(tv_scan.network_for(None, "10.0.5.23")) == "10.0.5.0/24"
    for bad in ("8.8.8.0/24", "10.0.0.0/8", "nonsense", "127.0.0.0/24"):
        with pytest.raises(tv_scan.ScanError):
            tv_scan.network_for(bad, None)
    with pytest.raises(tv_scan.ScanError):
        tv_scan.network_for(None, None)


def test_identify(monkeypatch):
    ports = {
        "192.168.1.10": [8001],
        "192.168.1.11": [8060],
        "192.168.1.12": [3001, 3000],
        "192.168.1.13": [],
    }
    monkeypatch.setattr(tv_scan, "_open_ports", lambda host: ports.get(host, []))
    monkeypatch.setattr(
        tv_scan,
        "_samsung",
        lambda host: {
            "brand": "samsung",
            "name": "Living room",
            "model": "QN65",
            "mac": None,
        },
    )
    monkeypatch.setattr(
        tv_scan,
        "_roku",
        lambda host: {"brand": "roku", "name": "Den", "model": "TCL", "mac": None},
    )
    found = tv_scan.scan(ipaddress.ip_network("192.168.1.8/29"))
    assert [(t["host"], t["brand"]) for t in found] == [
        ("192.168.1.10", "samsung"),
        ("192.168.1.11", "roku"),
        ("192.168.1.12", "lg"),
    ]


FOUND = [
    {
        "host": "192.168.1.11",
        "brand": "roku",
        "name": "Den Roku",
        "model": "TCL",
        "mac": None,
    },
]


def test_api(client, owner, make_user, new_client, login, csrf, monkeypatch):
    monkeypatch.setattr(scan_route, "scan", lambda net: [dict(t) for t in FOUND])
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/tv-scan"
    r = client.post(url, json={"network": "192.168.1.0/24"}, headers=csrf(client))
    assert r.status_code == 200, r.text
    tv = r.json()["tvs"][0]
    assert (
        tv["integration"] == "roku_tv"
        and tv["enabled"] is False
        and tv["added"] is False
    )
    assert (
        client.post(
            url, json={"network": "8.8.8.0/24"}, headers=csrf(client)
        ).status_code
        == 422
    )
    member = make_user(owner.home_id, role="member")
    m = new_client()
    assert login(m, member).status_code == 200
    assert (
        m.post(url, json={"network": "192.168.1.0/24"}, headers=csrf(m)).status_code
        == 403
    )


def test_ui_find_and_add(open_page, owner, monkeypatch):
    from app.integrations import roku

    monkeypatch.setattr(scan_route, "scan", lambda net: [dict(t) for t in FOUND])
    monkeypatch.setattr(
        roku,
        "info",
        lambda host: {"name": "Den Roku", "model": "TCL", "is_tv": True, "on": True},
    )
    page = open_page()
    _ui.ui_login(page, owner)
    _ui.go_settings(page, "integrations")
    panel = page.get_by_test_id("tv-scan-panel")
    panel.get_by_test_id("tv-scan-network").fill("192.168.1.0/24")
    panel.get_by_test_id("tv-scan").click()
    row = page.get_by_test_id("tv-scan-row")
    expect(row).to_contain_text("Den Roku")
    row.get_by_test_id("tv-scan-add").click()  # turns Roku on, then adds
    expect(page.get_by_test_id("status")).to_contain_text("Den Roku added")
    expect(page.get_by_test_id("roku-row")).to_contain_text("Den Roku")
    expect(page.get_by_test_id("tv-scan-row")).to_contain_text("Added")
