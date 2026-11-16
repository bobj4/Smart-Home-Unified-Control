"""Rheem: a water heater's MAC address (its EcoNet Wi-Fi module's name) and
its IP address, found from the MAC (neighbors.py), in the ⓘ window."""

import json

from pyeconet.equipment.water_heater import WaterHeater

from app import neighbors
from app.integrations import rheem
from tests import test_rheem
from tests.test_network_info import ARP_TEXT
from tests.test_rheem import heater, ready, rheem_devices, sync

econet, secrets_key = test_rheem.econet, test_rheem.secrets_key  # its fixtures


def test_the_module_name_is_its_mac():
    assert rheem.module_mac("80-91-33-8a-12-34") == "80:91:33:8A:12:34"
    assert rheem.module_mac("8091338A1234") == "80:91:33:8A:12:34"
    assert rheem.module_mac("econet_wh_1") is None
    assert rheem.module_mac("80-91-33-8A-12") is None
    assert rheem.module_mac(None) is None
    info = {
        "device_name": "34-13-43-92-94-8D",
        "serial_number": "S1",
        "device_type": "WH",
        "@NAME": {"value": "Garage"},
        "@SETPOINT": {
            "value": 120,
            "constraints": {"lowerLimit": 110, "upperLimit": 140},
        },
        "@CONNECTED": True,
    }
    read = rheem.heater_from_equipment(WaterHeater(info, None))
    assert read.mac == "34:13:43:92:94:8D"
    assert "mac" not in read.state()


def test_mac_and_ip_in_the_device_details(
    client,
    db,
    owner,
    login,
    csrf,
    econet,
    secrets_key,
    monkeypatch,
    tmp_path,  # noqa: F811
):
    arp = tmp_path / "arp"
    arp.write_text(ARP_TEXT)
    monkeypatch.setattr(neighbors, "ARP", arp)
    monkeypatch.setattr(neighbors, "_read_at", -1e9)  # read it afresh
    monkeypatch.setattr(neighbors, "_cache", {})
    econet.heaters = [heater(mac="34:13:43:92:94:8D")]
    ready(client, csrf, login, owner)
    assert sync(client, csrf, owner.home_id).status_code == 200
    (device,) = rheem_devices(db, owner.home_id)
    assert json.loads(device.capabilities) == {"mac": "34:13:43:92:94:8D"}
    shown = client.get(f"/api/v1/homes/{owner.home_id}/devices").json()
    assert shown[0]["network"] == {"ip": "192.168.1.57", "mac": "34:13:43:92:94:8D"}
    econet.heaters = [heater()]  # EcoNet left it out once: kept
    assert sync(client, csrf, owner.home_id).status_code == 200
    (device,) = rheem_devices(db, owner.home_id)
    assert json.loads(device.capabilities)["mac"] == "34:13:43:92:94:8D"
