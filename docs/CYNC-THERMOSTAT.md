> **Status (2026-10-23): reading confirmed** by the owner's probe of their thermostat (firmware V1.2.136): the probe reply, its 2-byte name length and every data point below decoded as described. **Writing is still unconfirmed**: the app checks each write by probing afterwards and reports a failure if the thermostat did not take it.

# Cync (C by GE) thermostat: cloud protocol notes

Source: Cync app 6.17.0 dex bytecode (`com.gelighting.cbygekit`) and the Xlink SDK sources (`io.xlink.wifi.sdk`).
Cross-checked against one real captured packet in pycync's tests. **Nothing here has been run against a live thermostat yet.**

## Transport
- Cloud TCP connection manager. pycync uses `cm-sec.gelighting.com:23779` (TLS). The SDK defaults are port 23778 (TLS) and an HTTP-port fallback; the SDK's TLS context trusts any certificate.
- One session per Cync account: a second login kicks the first (disconnect code 3).
- Login: pycync already implements it (type 1; body `03, userId(4), authLen(2), authorize, 02, keepalive(2)=180, resLen(1), resource`).
- Keepalive: type 13 ping, empty body, about every 87 s (180/2-3). More than 3 unanswered pings = the SDK drops the session. Cloud request timeout 7 s.

## Packet framing
`b0 = (type<<4) | (response<<3) | 3`, then 4-byte big-endian body length, then body.

Types: 1 LOGIN, 3 SET, 4 SYNC, 5 SETPWD, 7 PIPE, 8 PIPE_SYNC, 9 SUBSCRIPTION, 10 PROBE, 12 EVENT, 13 PING, 14 DISCONNECT.

| Message | Body |
|---|---|
| Probe request (type 10) | `deviceId(4) msgId(2) 00` |
| Probe response (type 10, response bit) | `deviceId(4) msgId(2) code(1)`, if code 0: `flags(1)` (bit0 = name present, bits 1-2 = data points follow), optional name, entries |
| Set request (type 3) | `deviceId(4) msgId(2) 06 entries...` |
| Set ack (type 3, response bit) | `deviceId(4) msgId(2) code(1)`, 0 = success |
| Device push (type 4, no response bit) | `deviceId(4) msgId(2) flags(1)` then optional name, then entries (bit2 = data points) |

Server codes: 0 ok, 1 invalid param, 2 invalid key, 3 unavailable id, 4 server error, 5 unauthorized, 10 device offline.

## Data-point entry
`index(1) | header(2) | value`, header = `(typeNibble<<12) | length` (length is 12 bits).
Write headers: bool/byte `0x0001`, short `0x2002`, int `0x4004`, float `0x7004`, string `0x9000|len`, bytes `0xA000|len`.
Read nibble: 0 byte/bool, 1-2 short, 3-6 int, 7-8 float, 9 string, 10 bytes.

Example (UNVERIFIED): set heat setpoint to 72.0F
`33 0000000f <deviceId(4)> <msgId(2)> 06 0b 9005 37 32 2e 30 46`

## Thermostat data points
Device types: 122 (Gen 2), 224 (Gen 1), both data-point protocol. W = written by the app, R = reported by the device.

| Idx | Name | Type | Notes |
|---|---|---|---|
| 0 | FirmwareVersion | string | R |
| 1 | Stm32Version | string | R |
| 2 | WifiRssi | string | R |
| 3 | ErrorCode | int | R, code meanings not decoded |
| 4 | RealtimeTemperature | string | R, e.g. `75.9F` |
| 5 | RealtimeHumidity | int | R, percent |
| 6 | ModeStatus | int | R, same codes as 7 |
| 7 | Mode_set | int | W: 0 OFF, 1 COOL, 2 HEAT, 3 AUTO, 4 ECO, 5 EMERGENCY |
| 8 | FanModeStatus | int | R |
| 9 | Fan_Mode_Set | int | W: 0 AUTO, 1 ON |
| 10 | HeatSetpointStatus | string | R, `72.0F` |
| 11 | Setpoint_heat_set | string | W, `72.0F`, 0.1 degree, `F` or `C` suffix |
| 12 | HvacTypeStatus | int | R: 1 CO1, 2 HE1, 3 HC1, 4 HP1, 5 HP2, 6 HPA, 7 CO2, 8 HE2, 9 HC2, 10 NONE |
| 13 | HVAC_Type_Set | int | W, same codes |
| 14 | Furnace_Type_set | int | W: 0 gas, 1 electric, 2 boiler/radiant |
| 15 | Auto_Mode_Deadband | string | |
| 16 | RunModeStatus | int | R, same codes as 17 |
| 17 | Run_Mode_Set | int | W: 0 SCHEDULE, 1 PERMANENT, 2 TEMPORARY (app never sets 2) |
| 18 | Dehumidification_Setpoint | int | |
| 19 | Dehumidification_Enable | bool | |
| 20 | Temperature_Unit | bool | false = Fahrenheit, true = Celsius |
| 21 | Temperature_Offset | string | |
| 22 | Humidity_Offset | string | |
| 23 | EarlyON_Enable | bool | |
| 24 / 25 | Eco_Mode_Min / Max_Setpoint | string | |
| 26 | Min_Fan_Runtime | int | |
| 27 | HeatPump_Changeover_Mode | bool | |
| 56 | Event_Notification_En | bool | |
| 57 / 58 | Minimum / Maximum_Temperature | string | notification thresholds |
| 59 / 60 | Minimum / Maximum_Humidity | int | notification thresholds |
| 61 | Filter_Replacement_Method | bytes | |
| 62 | Auto_OTA_En | bool | |
| 84 | ReadSetting | string | write a setting name to request it; reply is JSON `{name: value}` |
| 86 | EnergyReportStatus | bytes | not decoded |
| 87 | SensorRawDataReport | string | JSON `sensorsData:[...]` |
| 88 | Filter_Replacement_Reset | bool | |
| 89 / 90 | OtaUpdateControl / Status | string | do not touch |
| 91 | CoolSetpointStatus | string | R |
| 92 | Setpoint_cool_set | string | W |
| 96 | WorkStatus | int | R: 0 NONE, 1 COOLING, 2 HEATING |
| 97 | Power_Line | int | |
| 98 | Aux_Furnace_Type_set | int | |
| 104 | FanRunModeStatus | int | R |
| 105 | RelayStatus | bytes | R, exactly 6 bytes, each 0 OFF, 1 ON, 2 NOT_USED (terminal order not decoded) |
| 106 | FilterInfoStatus | string | R, JSON `{resetDate, runtimeHours}` |
| 107 | Date_Time_Set | string | |
| 108 | CountdownStatus | bytes | R: b0 work mode (cool/heat), b1 type (min runtime / min timeout), b2-7 year, month, day, hour, minute, second, b8-9 duration (big-endian) |
| 115 | Zipcode | string | |
| 118 | Auto_DST | bool | |

## App behaviour worth copying
- Changing setpoints writes only the heat and/or cool setpoint entries, in one set packet.
- The app blocks setpoint changes while the mode is ECO ("leave Eco mode first").
- The Savant layer in the app uses different enum numbering (mode HEAT=1/COOL=2, fan ON=0/AUTO=1). Those are not wire values; the wire values are the ones above.

## Unknowns
- Whether the device pushes state after login or needs a probe first (probe is the documented path).
- Exact precision/range limits and the Eco-mode rule enforced by firmware vs only by the app.
- Names/order of the six relay terminals, error code meanings, energy report layout.
- Whether a second (home-shared) account avoids the one-session limit.
## Schedules (from the Cync app 6.24; reading confirmed on the owner's thermostat 2026-10-24, writing not yet tried)
Source: `com.gelighting.cbygekit.services.devices.datapoint` (ThermostatScheduleSetDataPoint,
ThermostatScheduleDataPointsKt, TemperatureReadMethodScheduleDataPoint). Code: `app/integrations/cync_schedule.py`.

| Idx | Name | Value |
|---|---|---|
| 37-43 | Temp_Read_Schd_Mon ... Sun | which sensors are read, by time of day |
| 63-69 | Sched_Heat_Mon ... Sun | heating set point schedule |
| 70-76 | Sched_Cool_Mon ... Sun | cooling set point schedule |
| 77-83 | Sched_Auto_Mon ... Sun | auto (heat and cool) schedule |

Days run Monday (+0) to Sunday (+6). Every value is bytes: a list of periods, or the single byte
`FF` for a day with none.
- Heat/Cool period (5 bytes): hour, minute, unit (0 F, 1 C), temperature x100 (2 bytes, big-endian).
- Auto period (7 bytes): hour, minute, unit, heat x100 (2), cool x100 (2).
- Sensor period (10 bytes): hour, minute, method (0 thermostat, 1 one remote sensor, 2 all
  sensors, FF none), then 7 bytes naming the remote sensor for method 1 (zeros otherwise; the
  7-byte sensor format is in ExternalSensorDataPoints, not yet decoded).

These points have the "setting" role: a probe does not return them. Asking for one is a set
packet writing its name (for example `Sched_Heat_Mon`) to ReadSetting (point 84). The set is
acknowledged (code 0; a second ack with code 10 follows some seconds later), and the answer
arrives as a SYNC push of point 84 holding JSON `{"Sched_Heat_Mon": null}` (nothing stored) or
`{"Temp_Read_Schd_Mon": [7,0,2,0,...]}`: the bytes as numbers, padded with 255 (sensor schedules
to 100 bytes). pycync cannot parse these pushes and drops them, so `cync_thermostat` reads raw
packets before pycync does. A remote sensor in a sensor period is its type byte `01` followed by
its 6-digit PIN code as text (`01 "024944"` for PinCode 24944 in SensorRawDataReport).
