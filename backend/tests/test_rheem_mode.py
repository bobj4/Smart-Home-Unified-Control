"""Water heater mode and status from what EcoNet reports. Nothing here
talks to Rheem."""

from pyeconet.equipment.water_heater import WaterHeater

from app.integrations import rheem


def test_mode_is_read_from_its_own_name():
    """pyeconet counts along the modes it knows, so a mode name it does not
    know earlier in the list shifted the mode (and the status) by one."""
    info = {
        "serialNumber": "W-1",
        "device_type": "WH",
        "@TYPE": "heatpumpWaterHeaterGen5",
        "@NAME": {"value": "Garage"},
        "@SETPOINT": {
            "value": 120,
            "constraints": {"lowerLimit": 110, "upperLimit": 140},
        },
        "@MODE": {
            "value": 2,
            "constraints": {
                "enumText": ["Off", "Smart Mode", "High Demand", "Electric"]
            },
        },
        "@ENABLED": {"value": 1},
        "@RUNNING": "",
    }
    assert WaterHeater(info, None).mode.name == "ELECTRIC_MODE"  # pyeconet: shifted
    assert rheem.heater_mode(WaterHeater(info, None)) == "high_demand"
    info["@MODE"]["value"] = 1
    assert rheem.heater_mode(WaterHeater(info, None)) == "smart_mode"
    info["@ENABLED"] = {"value": 0}  # switched off: @MODE keeps the last mode
    assert rheem.heater_mode(WaterHeater(info, None)) == "off"
    info.pop("@ENABLED")
    info["@MODE"] = {"value": 9, "constraints": {"enumText": ["Off"]}}
    read = rheem.heater_from_equipment(WaterHeater(info, None))  # does not fail
    assert read.status == "idle"
