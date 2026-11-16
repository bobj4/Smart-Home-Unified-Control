"""The demo garage door and door sensor: a demo door gets where it is sent
at once (a real one reports its way there)."""

import json

from app.demo import add_demo_devices
from app.models import Device


def test_demo_door_and_sensor(client, db, owner, login, csrf):
    add_demo_devices(db, owner.home_id)
    door = db.query(Device).filter_by(home_id=owner.home_id, name="Garage door").one()
    sensor = (
        db.query(Device)
        .filter_by(home_id=owner.home_id, name="Front door sensor")
        .one()
    )
    assert (door.type, json.loads(door.state)) == ("garage_door", {"door": "closed"})
    assert sensor.type == "sensor" and json.loads(sensor.state)["door"] == "closed"
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/devices/{door.id}/command"
    r = client.post(url, json={"command": "open", "payload": {}}, headers=csrf(client))
    assert r.status_code == 200, r.text
    assert r.json()["state"]["door"] == "open"
    r = client.post(url, json={"command": "close", "payload": {}}, headers=csrf(client))
    assert r.json()["state"]["door"] == "closed"
