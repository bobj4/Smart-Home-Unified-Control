"""Read-only probe of the Cync thermostat (step 2 of the thermostat notes).

    python scripts/cync_thermostat_probe.py [--seconds 30]

Uses the Cync login saved in Settings > Integrations (SECRETS_KEY must be
set). Lists every device on the account, then connects to Cync's server,
asks each one that is not a light or plug to report ("probe") and prints
every reply, decoding the data points from the protocol notes. It sends no
settings: nothing on the thermostat changes.

Cync allows one connection per account, so the server's live connection
drops while this runs and reconnects within about 30 seconds afterwards.
Save the output (it holds no passwords or tokens) and send it to the reviewer.
"""

import argparse
import asyncio
import json
import ssl
import struct
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402
from pycync import Auth, User  # noqa: E402
from pycync.const import REST_API_BASE_URL  # noqa: E402
from pycync.tcp.packet_builder import build_login_request_packet  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app import credentials, init_db  # noqa: E402
from app.db_config import SessionLocal  # noqa: E402
from app.models import Home  # noqa: E402

HOST, PORT = "cm-sec.gelighting.com", 23779
TYPES = {
    1: "LOGIN",
    3: "SET",
    4: "SYNC",
    7: "PIPE",
    8: "PIPE_SYNC",
    9: "SUBSCRIPTION",
    10: "PROBE",
    12: "EVENT",
    13: "PING",
    14: "DISCONNECT",
}
POINTS = {
    0: "FirmwareVersion",
    1: "Stm32Version",
    2: "WifiRssi",
    3: "ErrorCode",
    4: "RealtimeTemperature",
    5: "RealtimeHumidity",
    6: "ModeStatus",
    7: "Mode_set",
    8: "FanModeStatus",
    9: "Fan_Mode_Set",
    10: "HeatSetpointStatus",
    11: "Setpoint_heat_set",
    12: "HvacTypeStatus",
    13: "HVAC_Type_Set",
    14: "Furnace_Type_set",
    15: "Auto_Mode_Deadband",
    16: "RunModeStatus",
    17: "Run_Mode_Set",
    18: "Dehumidification_Setpoint",
    19: "Dehumidification_Enable",
    20: "Temperature_Unit",
    21: "Temperature_Offset",
    22: "Humidity_Offset",
    23: "EarlyON_Enable",
    24: "Eco_Mode_Min_Setpoint",
    25: "Eco_Mode_Max_Setpoint",
    26: "Min_Fan_Runtime",
    27: "HeatPump_Changeover_Mode",
    56: "Event_Notification_En",
    57: "Minimum_Temperature",
    58: "Maximum_Temperature",
    59: "Minimum_Humidity",
    60: "Maximum_Humidity",
    61: "Filter_Replacement_Method",
    62: "Auto_OTA_En",
    84: "ReadSetting",
    86: "EnergyReportStatus",
    87: "SensorRawDataReport",
    88: "Filter_Replacement_Reset",
    89: "OtaUpdateControl",
    90: "OtaUpdateStatus",
    91: "CoolSetpointStatus",
    92: "Setpoint_cool_set",
    96: "WorkStatus",
    97: "Power_Line",
    98: "Aux_Furnace_Type_set",
    104: "FanRunModeStatus",
    105: "RelayStatus",
    106: "FilterInfoStatus",
    107: "Date_Time_Set",
    108: "CountdownStatus",
    115: "Zipcode",
    118: "Auto_DST",
}


def packet(kind: int, body: bytes) -> bytes:
    return bytes([(kind << 4) | 3]) + struct.pack(">I", len(body)) + body


def decode_value(nibble: int, raw: bytes) -> Any:
    if nibble == 0:
        return raw[0] if len(raw) == 1 else raw.hex()
    if nibble in (1, 2) and len(raw) == 2:
        return struct.unpack(">h", raw)[0]
    if 3 <= nibble <= 6 and len(raw) == 4:
        return struct.unpack(">i", raw)[0]
    if nibble in (7, 8) and len(raw) == 4:
        return round(struct.unpack(">f", raw)[0], 3)
    if nibble == 9:
        return raw.decode("utf-8", "replace")
    return raw.hex()


def decode_entries(data: bytes) -> list[str]:
    """index(1) header(2) value; header = type nibble << 12 | length."""
    out, i = [], 0
    while i + 3 <= len(data):
        index = data[i]
        header = struct.unpack(">H", data[i + 1 : i + 3])[0]
        nibble, length = header >> 12, header & 0x0FFF
        raw = data[i + 3 : i + 3 + length]
        if len(raw) != length:
            out.append(f"    (could not decode the rest: {data[i:].hex()})")
            break
        out.append(
            f"    [{index:3}] {POINTS.get(index, '?'):28} = {decode_value(nibble, raw)!r}"
        )
        i += 3 + length
    return out


def describe(kind: int, response: bool, body: bytes) -> list[str]:
    lines = [
        f"<- {TYPES.get(kind, kind)}{' (response)' if response else ''}  {len(body)} bytes: {body.hex()}"
    ]
    if kind in (10, 4) and len(body) >= 7:
        device_id, msg_id = struct.unpack(">IH", body[:6])
        rest = body[6:]
        if kind == 10 and response:
            code, rest = rest[0], rest[1:]
            lines.append(f"   probe reply: device {device_id} msg {msg_id} code {code}")
            if code != 0 or not rest:
                return lines
        flags, rest = rest[0], rest[1:]
        lines.append(f"   device {device_id} flags {flags:08b}")
        if flags & 1 and len(rest) >= 2:  # name present: 2-byte length, then name
            name_len = int.from_bytes(rest[:2], "big")
            if name_len <= len(rest) - 2:
                lines.append(
                    f"   name: {rest[2 : 2 + name_len].decode('utf-8', 'replace')!r}"
                )
                rest = rest[2 + name_len :]
        lines += decode_entries(rest)
    return lines


async def run(seconds: int) -> None:
    init_db()
    with SessionLocal() as db:
        saved = None
        for home_id in db.scalars(select(Home.id)).all():
            saved = credentials.load(db, home_id, "cync")
            if saved:
                break
    if not saved or not saved.get("tokens"):
        print("No Cync login is saved (Settings > Integrations > GE Cync).")
        return
    t = saved["tokens"]
    user = User(
        t["access_token"],
        t["refresh_token"],
        t["authorize"],
        t["user_id"],
        expires_at=t["expires_at"],
    )
    async with aiohttp.ClientSession() as web:
        auth = Auth(web, user=user)
        devices = await auth._send_user_request(
            f"{REST_API_BASE_URL}/v2/user/{user.user_id}/subscribe/devices"
        )
    print(f"== {len(devices)} entries on the Cync account")
    probe_ids = []
    for d in devices:
        fields = {
            k: d.get(k)
            for k in (
                "id",
                "name",
                "product_id",
                "source",
                "is_online",
                "mac",
                "device_type",
                "deviceType",
            )
        }
        print("   " + json.dumps(fields))
        if d.get("source") != 5:  # 5 = a home, not a device
            probe_ids.append(int(d["id"]))

    context = ssl.create_default_context()
    try:
        reader, writer = await asyncio.open_connection(HOST, PORT, ssl=context)
    except ssl.SSLError:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE  # same fallback as pycync and the Cync app
        reader, writer = await asyncio.open_connection(HOST, PORT, ssl=context)
    writer.write(build_login_request_packet(user.authorize, user.user_id))
    await writer.drain()
    print(
        f"== connected to {HOST}:{PORT}, logging in; probing {len(probe_ids)} device(s)"
    )

    async def probes() -> None:
        await asyncio.sleep(2)
        for n, device_id in enumerate(probe_ids, start=1):
            body = struct.pack(">IH", device_id, n) + b"\x00"
            print(f"-> PROBE device {device_id}: {packet(10, body).hex()}")
            writer.write(packet(10, body))
            await writer.drain()
            await asyncio.sleep(1)

    sender = asyncio.create_task(probes())
    deadline = time.monotonic() + seconds
    try:
        while time.monotonic() < deadline:
            try:
                head = await asyncio.wait_for(
                    reader.readexactly(5), deadline - time.monotonic()
                )
            except (TimeoutError, asyncio.IncompleteReadError):
                break
            kind, response = head[0] >> 4, bool(head[0] & 8)
            body = await reader.readexactly(struct.unpack(">I", head[1:])[0])
            for line in describe(kind, response, body):
                print(line)
            if kind == 14:
                print("   (the server closed the session)")
                break
    finally:
        sender.cancel()
        writer.close()
    print("== done; nothing was changed. Send this output to the reviewer.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Cync thermostat probe.")
    parser.add_argument("--seconds", type=int, default=30, help="how long to listen")
    asyncio.run(run(parser.parse_args().seconds))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
