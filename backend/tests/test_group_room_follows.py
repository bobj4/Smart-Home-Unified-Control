"""A group's room follows its devices: when the last of them moves to a new
room the group moves too, and a group with no room of its own shows the
room most of its devices are in."""


def test_group_moves_with_its_devices(client, owner, login, csrf, make_device):
    assert login(client, owner).status_code == 200
    base = f"/api/v1/homes/{owner.home_id}"

    def move(device_id, room):
        r = client.patch(
            f"{base}/devices/{device_id}", json={"room": room}, headers=csrf(client)
        )
        assert r.status_code == 200, r.text

    def group(group_id):
        return next(
            g for g in client.get(f"{base}/groups").json() if g["id"] == group_id
        )

    lamps = [make_device(owner.home_id, name=f"Lamp {i}") for i in range(3)]
    for lamp in lamps:
        move(lamp, "Kitchen")
    made = client.post(
        f"{base}/groups",
        json={"name": "Ceiling", "room": "Kitchen", "device_ids": lamps[:2]},
        headers=csrf(client),
    )
    assert made.status_code == 201, made.text
    ceiling = made.json()["id"]
    move(lamps[0], "Den")
    assert group(ceiling)["room"] == "Kitchen"  # one still in the kitchen
    move(lamps[2], "Den")  # not in the group: no effect
    assert group(ceiling)["room"] == "Kitchen"
    move(lamps[1], "Den")
    assert group(ceiling)["room"] == "Den"  # all of it moved

    # No room of its own: the room most of its devices are in.
    loose = client.post(
        f"{base}/groups",
        json={"name": "All", "device_ids": lamps},
        headers=csrf(client),
    ).json()["id"]
    move(lamps[0], "Hall")
    assert group(loose)["room"] == "Den"  # Hall, Den, Den
