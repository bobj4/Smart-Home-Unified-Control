# ruff: noqa: F811 (fixtures shared with test_package1)
"""Alerts: the server watches for a garage left open (and can close it),
something in a garage door's way, devices offline, water heater problems,
thermostats too hot or too cold and camera detections (each device's own
settings: its bell in Settings > Devices), and tells the people who asked, by email and by
notifications (Web Push: RFC 8291 encryption, RFC 8292 signing)."""

import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

from app import alerts, frigate_home, webpush
from app.integrations import ratgdo
from app.models import Device, PushSubscription
from tests.test_package1 import SERVER, outbox, secrets_key  # noqa: F401

FCM = "https://fcm.googleapis.com/fcm/send/abc123"
BROWSER = ec.generate_private_key(ec.SECP256R1())
BROWSER_KEY = webpush.b64url(
    BROWSER.public_key().public_bytes(
        __import__(
            "cryptography.hazmat.primitives.serialization", fromlist=["x"]
        ).Encoding.X962,
        __import__(
            "cryptography.hazmat.primitives.serialization", fromlist=["x"]
        ).PublicFormat.UncompressedPoint,
    )
)
AUTH = webpush.b64url(b"0123456789abcdef")


def test_encryption_matches_rfc_8291():
    priv = int.from_bytes(
        webpush.unb64url("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"), "big"
    )
    body = webpush.encrypt(
        b"When I grow up, I want to be a watermelon",
        "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
        "BTBZMqHH6r4Tts7J_aSIgg",
        salt=webpush.unb64url("DGv6ra1nlYgDCS1FRnbzlw"),
        ours=ec.derive_private_key(priv, ec.SECP256R1()),
    )
    assert webpush.b64url(body) == (
        "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCY"
        "LocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWy"
        "ouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
    )


def test_vapid_signature_verifies():
    pem = webpush.new_key()
    header = webpush.vapid_header(pem, FCM, now=1_800_000_000)
    token = header.split("t=", 1)[1].split(",", 1)[0]
    head, body, sig = token.split(".")
    claims = json.loads(webpush.unb64url(body))
    assert claims["aud"] == "https://fcm.googleapis.com"
    raw = webpush.unb64url(sig)
    der = encode_dss_signature(
        int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")
    )
    public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), webpush.unb64url(webpush.public_key(pem))
    )
    public.verify(
        der, f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())
    )  # raises if wrong


@pytest.fixture
def pushed(monkeypatch):
    sent = []
    status = {"code": 201}

    def post(url, data, headers):
        sent.append({"url": url, "data": data, "headers": headers})
        return status["code"]

    monkeypatch.setattr(webpush, "post", post)
    return {"sent": sent, "status": status}


def subscribe(client, csrf, endpoint=FCM):
    return client.post(
        "/api/v1/account/push",
        json={
            "endpoint": endpoint,
            "keys": {"p256dh": BROWSER_KEY, "auth": AUTH},
            "label": "Phone",
        },
        headers=csrf(client),
    )


def test_only_browser_push_services_are_sent_to(
    client, owner, login, csrf, secrets_key
):
    assert login(client, owner).status_code == 200
    assert client.get("/api/v1/account/push/key").json()["key"]
    for bad in (
        "https://192.168.1.5/push",
        "http://fcm.googleapis.com/x",
        "https://evil.example/fcm.googleapis.com",
    ):
        assert subscribe(client, csrf, bad).status_code == 422
    assert subscribe(client, csrf).status_code == 201
    r = client.post(
        "/api/v1/account/push",
        json={"endpoint": FCM, "keys": {"p256dh": BROWSER_KEY, "auth": "x" * 30}},
        headers=csrf(client),
    )
    assert r.status_code == 422  # not a 16-byte auth secret
    client.post(
        "/api/v1/account/push/remove", json={"endpoint": FCM}, headers=csrf(client)
    )


def ready(client, db, owner, login, csrf, kinds, email=True, push=True):
    assert login(client, owner).status_code == 200
    client.put("/api/v1/admin/email", json=SERVER, headers=csrf(client))
    assert client.get("/api/v1/account/push/key").json()["key"]  # as the page does
    assert subscribe(client, csrf).status_code == 201
    r = client.put(
        f"/api/v1/homes/{owner.home_id}/alerts/mine",
        json={"email": email, "push": push, "kinds": kinds},
        headers=csrf(client),
    )
    assert r.status_code == 200, r.text


def bell(client, csrf, owner, device, enabled=None, settings=None):
    """The device's bell in Settings > Devices."""
    body = {"enabled": enabled, "settings": settings or {}}
    return client.put(
        f"/api/v1/homes/{owner.home_id}/alerts/devices/{device.id}",
        json=body,
        headers=csrf(client),
    )


def garage(db, owner, make_device, door="closed", **more):
    device = db.get(
        Device, make_device(owner.home_id, device_type="garage_door", name="Garage")
    )
    device.state = json.dumps({"door": door, **more})
    db.commit()
    return device


def decrypt(body):
    """What the browser reads (RFC 8291), to check the message."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt, keylen = body[:16], body[20]
    as_public = body[21 : 21 + keylen]
    sealed = body[21 + keylen :]
    shared = BROWSER.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public),
    )
    ua_public = webpush.unb64url(BROWSER_KEY)
    ikm = webpush._hkdf(
        webpush.unb64url(AUTH), shared, b"WebPush: info\x00" + ua_public + as_public, 32
    )
    cek = webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    return json.loads(AESGCM(cek).decrypt(nonce, sealed, None)[:-1])


def test_garage_left_open_alerts_once_and_can_close_it(
    client, db, owner, login, csrf, make_device, secrets_key, outbox, pushed
):
    door = garage(db, owner, make_device, "open")
    ready(client, db, owner, login, csrf, ["garage_open", "auto_close"])
    r = bell(
        client,
        csrf,
        owner,
        door,
        settings={"open_minutes": 10, "auto_close_minutes": 30},
    )
    assert r.status_code == 200 and r.json()["settings"]["auto_close_minutes"] == 30
    watch = alerts.Watch()
    assert alerts.check_home(db, owner.home_id, now=0, watch=watch) == 0
    assert alerts.check_home(db, owner.home_id, now=9 * 60, watch=watch) == 0
    assert alerts.check_home(db, owner.home_id, now=10 * 60, watch=watch) == 1
    assert alerts.check_home(db, owner.home_id, now=11 * 60, watch=watch) == 0  # once
    to, subject, text = outbox[-1]
    assert to == owner.email and "Garage is open" in subject and "10 minutes" in text
    message = decrypt(pushed["sent"][-1]["data"])
    assert message["title"] == "Garage is open" and pushed["sent"][-1]["url"] == FCM
    assert pushed["sent"][-1]["headers"]["Authorization"].startswith("vapid t=")
    # After 30 minutes it closes, and says so.
    assert alerts.check_home(db, owner.home_id, now=30 * 60, watch=watch) == 1
    db.expire_all()
    assert json.loads(db.get(Device, door.id).state)["door"] == "closed"
    assert "closing" in outbox[-1][2]
    # Closed: the next time it is left open alerts again.
    alerts.check_home(db, owner.home_id, now=31 * 60, watch=watch)
    door = db.get(Device, door.id)
    door.state = json.dumps({"door": "open"})
    db.commit()
    alerts.check_home(db, owner.home_id, now=40 * 60, watch=watch)
    assert alerts.check_home(db, owner.home_id, now=50 * 60, watch=watch) == 1


def test_nothing_is_sent_until_someone_picks(
    client, db, owner, login, csrf, make_device, secrets_key, outbox, pushed
):
    garage(db, owner, make_device, "open")
    assert login(client, owner).status_code == 200
    watch = alerts.Watch()
    alerts.check_home(db, owner.home_id, now=0, watch=watch)
    assert alerts.check_home(db, owner.home_id, now=3600, watch=watch) == 0
    assert outbox == [] and pushed["sent"] == []


def test_obstruction_offline_and_water_heater(
    client, db, owner, login, csrf, make_device, secrets_key, outbox, pushed
):
    door = garage(db, owner, make_device, "closed", obstruction=False)
    hall = db.get(
        Device, make_device(owner.home_id, device_type="thermostat", name="Hall")
    )
    tank = db.get(
        Device, make_device(owner.home_id, device_type="water_heater", name="Tank")
    )
    tank.state = json.dumps({"alerts": 0})
    db.commit()
    ready(
        client,
        db,
        owner,
        login,
        csrf,
        ["obstruction", "offline", "water_heater"],
        push=False,
    )
    watch = alerts.Watch()
    assert alerts.check_home(db, owner.home_id, now=0, watch=watch) == 0
    door.state = json.dumps({"door": "closing", "obstruction": True})
    hall.online = False
    tank.state = json.dumps({"alerts": 2})
    db.commit()
    assert (
        alerts.check_home(db, owner.home_id, now=60, watch=watch) == 2
    )  # blocked, heater
    assert (
        alerts.check_home(db, owner.home_id, now=16 * 60, watch=watch) == 1
    )  # offline
    subjects = [s for _, s, _ in outbox]
    assert any("Garage is blocked" in s for s in subjects)
    assert any("Tank reports a problem" in s for s in subjects)
    assert any("Hall is offline" in s for s in subjects)
    assert pushed["sent"] == []  # email only, as chosen


def test_camera_detections(
    client, db, owner, login, csrf, secrets_key, outbox, pushed, monkeypatch
):
    from app import features

    features.set_integration(db, owner.home_id, "frigate", True, None, None)
    ready(client, db, owner, login, csrf, ["camera"])
    events = [{"id": "a", "camera": "driveway", "label": "car", "start_time": 100.0}]

    class Client:
        def events(self, limit, camera=None):
            return list(events)

    monkeypatch.setattr(frigate_home, "client_for_home", lambda db, home_id: Client())
    watch = alerts.Watch()
    assert alerts.check_home(db, owner.home_id, now=0, watch=watch) == 0  # first look
    events.insert(
        0, {"id": "b", "camera": "front_door", "label": "person", "start_time": 200.0}
    )
    events.insert(
        0, {"id": "c", "camera": "driveway", "label": "car", "start_time": 210.0}
    )
    assert alerts.check_home(db, owner.home_id, now=30, watch=watch) == 1
    assert "Person at front door" in outbox[-1][1]
    assert alerts.check_home(db, owner.home_id, now=60, watch=watch) == 0  # nothing new


def test_a_gone_browser_is_forgotten_and_test_alerts(
    client, db, owner, login, csrf, make_device, secrets_key, outbox, pushed
):
    ready(client, db, owner, login, csrf, ["garage_open"], email=False)
    pushed["status"]["code"] = 410
    r = client.post(f"/api/v1/homes/{owner.home_id}/alerts/test", headers=csrf(client))
    assert r.status_code == 200 and r.json() == {"email": False, "push": 0}
    assert db.query(PushSubscription).count() == 0


def test_settings_are_for_admins(
    client, new_client, db, owner, make_user, login, csrf, make_device
):
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/alerts"
    assert other.get(url).json()["can_admin"] is False
    r = other.put(f"{url}/settings", json={"frigate_labels": []}, headers=csrf(other))
    assert r.status_code == 403
    door = garage(db, owner, make_device)
    assert other.get(f"{url}/devices").json()[door.id]["enabled"] is True
    r = bell(other, csrf, owner, door, enabled=False)
    assert r.status_code == 403  # operators and admins
    r = other.put(
        f"{url}/mine", json={"kinds": ["camera", "nonsense"]}, headers=csrf(other)
    )
    assert r.status_code == 422
    r = other.put(f"{url}/mine", json={"kinds": ["camera"]}, headers=csrf(other))
    assert r.json()["kinds"] == ["camera"]


def test_each_device_sets_its_own_alerts(
    client, db, owner, login, csrf, make_device, secrets_key, outbox, pushed
):
    door = garage(db, owner, make_device, "open", obstruction=True)
    lamp = db.get(Device, make_device(owner.home_id, device_type="light", name="Lamp"))
    hall = db.get(
        Device, make_device(owner.home_id, device_type="thermostat", name="Hall")
    )
    hall.state = json.dumps({"current_temperature": 70, "unit": "F"})
    lamp.online = False
    db.commit()
    ready(
        client,
        db,
        owner,
        login,
        csrf,
        ["garage_open", "obstruction", "offline", "temperature"],
        push=False,
    )
    url = f"/api/v1/homes/{owner.home_id}/alerts/devices"
    shown = client.get(url).json()
    assert shown[door.id]["popup"] and shown[door.id]["enabled"]
    assert shown[lamp.id] == {"enabled": False, "popup": False, "settings": {}}
    assert shown[hall.id]["settings"]["too_cold"] is None
    # Off: the open, blocked door says nothing; the light (bell only) is on.
    assert bell(client, csrf, owner, door, enabled=False).status_code == 200
    assert bell(client, csrf, owner, lamp, enabled=True).json()["enabled"] is True
    r = bell(client, csrf, owner, lamp, settings={"open_minutes": 5})
    assert r.status_code == 422  # a light has no settings
    r = bell(client, csrf, owner, hall, settings={"too_cold": 80, "too_hot": 75})
    assert r.status_code == 422 and "below" in r.json()["detail"]
    r = bell(client, csrf, owner, hall, settings={"too_cold": 65, "too_hot": 68})
    assert r.status_code == 200
    watch = alerts.Watch()
    assert alerts.check_home(db, owner.home_id, now=0, watch=watch) == 1  # too hot
    assert "Hall is too hot" in outbox[-1][1] and "70 °F" in outbox[-1][2]
    assert alerts.check_home(db, owner.home_id, now=15 * 60, watch=watch) == 1
    assert "Lamp is offline" in outbox[-1][1]
    assert not any("Garage" in s for _, s, _ in outbox)
    # Back on, with the door's alerts at their settings.
    bell(client, csrf, owner, door, enabled=True, settings={"obstruction": False})
    assert alerts.check_home(db, owner.home_id, now=16 * 60, watch=watch) == 1
    assert "Garage is open" in outbox[-1][1]  # blocked, but that alert is off


def test_smartthings_token_ending_and_ended(
    client, db, owner, login, csrf, secrets_key, outbox, pushed
):
    import time

    from app import credentials, features, smartthings_oauth

    features.set_integration(db, owner.home_id, "samsung_tv", True, None, None)
    ready(client, db, owner, login, csrf, ["smartthings"], push=False)

    def token_age(hours, **more):
        credentials.save(
            db,
            owner.home_id,
            smartthings_oauth.CREDENTIAL,
            "SmartThings",
            {"token": "t" * 20, "saved_at": time.time() - hours * 3600, **more},
        )

    watch = alerts.Watch()
    token_age(2)
    assert alerts.check_home(db, owner.home_id, now=0, watch=watch) == 0
    token_age(23.5)
    assert alerts.check_home(db, owner.home_id, now=30, watch=watch) == 1
    assert "SmartThings token ends soon" in outbox[-1][1]
    assert alerts.check_home(db, owner.home_id, now=60, watch=watch) == 0  # once
    token_age(25)
    assert alerts.check_home(db, owner.home_id, now=90, watch=watch) == 1
    assert "SmartThings needs connecting again" in outbox[-1][1]
    assert "24 hours" in outbox[-1][2]
    token_age(0)  # a new token: quiet, and the next lapse alerts again
    assert alerts.check_home(db, owner.home_id, now=120, watch=watch) == 0
    token_age(1, problem=smartthings_oauth.RECONNECT)  # a sign-in to redo
    assert alerts.check_home(db, owner.home_id, now=150, watch=watch) == 1
    # A sign-in that renews itself never warns.
    credentials.save(
        db,
        owner.home_id,
        smartthings_oauth.CREDENTIAL,
        "SmartThings",
        {"oauth": True, "access_token": "a", "problem": None},
    )
    assert alerts.check_home(db, owner.home_id, now=180, watch=watch) == 0


# ------------------------------------------------------------ ratgdo extras


def test_ratgdo_extras(monkeypatch):
    answers = {
        "/binary_sensor/Obstruction": {"state": "ON", "value": True},
        "/light/Light": {"state": "OFF"},
    }
    calls = []

    class Answer:
        def __init__(self, status, data=None):
            self.status_code, self._data = status, data

        def json(self):
            return self._data

    def request(method, url, timeout):
        path = url.split("192.168.1.80", 1)[1]
        calls.append((method, path))
        base = path.rsplit("/", 1)[0] if method == "POST" else path
        return Answer(200, answers[base]) if base in answers else Answer(404)

    ratgdo._extra_path.clear()
    monkeypatch.setattr(ratgdo.requests, "request", request)
    assert ratgdo.extras("192.168.1.80") == {
        "obstruction": True,
        "light": False,
        "locked": None,
        "laser": None,  # not a ratgdo32 disco
        "vehicle": None,
    }
    ratgdo.act("192.168.1.80", "light_on")
    assert calls[-1] == ("POST", "/light/Light/turn_on")
    with pytest.raises(ratgdo.RatgdoError, match="no such part"):
        ratgdo.act("192.168.1.80", "lock")


def test_garage_light_and_lockout_commands(client, db, owner, login, csrf, make_device):
    door = garage(db, owner, make_device, "closed", light=False, locked=None)
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/devices/{door.id}/command"
    r = client.post(
        url, json={"command": "light_on", "payload": {}}, headers=csrf(client)
    )
    assert r.status_code == 200 and r.json()["state"]["light"] is True
    r = client.post(url, json={"command": "lock", "payload": {}}, headers=csrf(client))
    assert r.status_code == 422 and "remote lockout" in r.json()["detail"]


def test_the_bell_counts_new_alerts(
    client, new_client, db, owner, make_user, login, csrf, make_device, secrets_key
):
    garage(db, owner, make_device, "open")
    assert login(client, owner).status_code == 200
    url = f"/api/v1/homes/{owner.home_id}/alerts/feed"
    assert client.get(url).json() == {"unseen": 0, "items": []}
    watch = alerts.Watch()
    alerts.check_home(db, owner.home_id, now=0, watch=watch)
    alerts.check_home(
        db, owner.home_id, now=16 * 60, watch=watch
    )  # nobody asked: still kept
    feed = client.get(url).json()
    assert feed["unseen"] == 1 and feed["items"][0]["title"] == "Garage is open"
    assert feed["items"][0]["new"] is True
    assert client.post(f"{url}/seen", headers=csrf(client)).json() == {"unseen": 0}
    feed = client.get(url).json()
    assert feed["unseen"] == 0 and feed["items"][0]["new"] is False
    # Each person has their own count; guests have no bell.
    member = make_user(owner.home_id, role="member")
    other = new_client()
    assert login(other, member).status_code == 200
    assert other.get(url).json()["unseen"] == 1
    guest = make_user(owner.home_id, role="guest")
    them = new_client()
    assert login(them, guest).status_code == 200
    assert them.get(url).status_code in (403, 404)


def test_the_bell_keeps_the_newest(db, owner):
    for n in range(alerts.KEEP_ALERTS + 5):
        alerts.remember(db, owner.home_id, "offline", f"Alert {n}", "body")
    from app.models import AlertItem

    assert (
        db.query(AlertItem).filter_by(home_id=owner.home_id).count()
        == alerts.KEEP_ALERTS
    )
