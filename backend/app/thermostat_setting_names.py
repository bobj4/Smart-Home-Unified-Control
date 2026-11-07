"""The Cync thermostat's own settings: names, data points, kinds, choices
and ranges (used by app.thermostat_settings). Names and points are the Cync
app's (docs/CYNC-THERMOSTAT.md and the app's data point classes)."""

# key: (setting name, data point, kind)
SETTINGS: dict[str, tuple[str, int, str]] = {
    "early_on": ("EarlyON_Enable", 23, "bool"),
    "celsius": ("Temperature_Unit", 20, "bool"),  # its screen: true = Celsius
    "auto_dst": ("Auto_DST", 118, "bool"),
    "dehumidify": ("Dehumidification_Enable", 19, "bool"),
    "dehumidify_to": ("Dehumidification_Setpoint", 18, "int"),
    "min_fan_runtime": ("Min_Fan_Runtime", 26, "int"),
    "temperature_offset": ("Temperature_Offset", 21, "text"),
    "humidity_offset": ("Humidity_Offset", 22, "text"),
    "auto_deadband": ("Auto_Mode_Deadband", 15, "text"),
    "heat_pump_changeover": ("HeatPump_Changeover_Mode", 27, "bool"),
    "furnace_type": ("Furnace_Type_set", 14, "choice"),
    "power_wires": ("Power_Line", 97, "choice"),
}
# How far from the set point each heating or cooling stage starts (begin)
# and stops (end): the Cync app's Thresholds (HeatingCoolingStageTemperature-
# OffsetSetDataPoint: names and points as the app has them, the cooling
# stage 2 name with its lower-case "c"). Kept as text such as "1.0F".
STAGE_OFFSETS: dict[str, tuple[str, int]] = {
    "heat_stage1_begin": ("Heating_Stage_1_Begin_Offset", 28),
    "heat_stage2_begin": ("Heating_Stage_2_Begin_Offset", 29),
    "heat_stage2_end": ("Heating_Stage_2_End_Offset", 30),
    "heat_stage3_begin": ("Heating_Stage_3_Begin_Offset", 31),
    "heat_stage3_end": ("Heating_Stage_3_End_Offset", 32),
    "heat_stage4_begin": ("Heating_Stage_4_Begin_Offset", 33),
    "heat_stage4_end": ("Heating_Stage_4_End_Offset", 99),
    "emergency_stage3_begin": ("Heating_Emer_Stage3_Begin_Offset", 100),
    "emergency_stage4_begin": ("Heating_Emer_Stage4_Begin_Offset", 101),
    "emergency_stage4_end": ("Heating_Emer_Stage4_End_Offset", 102),
    "cool_stage1_begin": ("Cooling_Stage_1_Begin_Offset", 34),
    "cool_stage2_begin": ("cooling_Stage_2_Begin_Offset", 35),
    "cool_stage2_end": ("Cooling_Stage_2_End_Offset", 36),
}
SETTINGS.update(
    {key: (name, point, "text") for key, (name, point) in STAGE_OFFSETS.items()}
)
CHOICES: dict[str, dict[int, str]] = {
    "furnace_type": {0: "Gas", 1: "Electric", 2: "Boiler"},
    # ThermostatPowerLine: NONE 0, P1 1, P2 2 (the app's None, Rc, Rc and Rh).
    "power_wires": {0: "None", 1: "Rc", 2: "Rc and Rh"},
}
# The system types in the Cync app's words and order (HVAC_Type_Set codes).
SYSTEM_TYPES: dict[int, str] = {
    1: "1 Stage Cooling Conventional",
    7: "2 Stage Cooling Conventional",
    2: "1 Stage Heating Conventional",
    8: "2 Stage Heating Conventional",
    3: "1 Stage Heating/Cooling Conventional",
    9: "2 Stage Heating/Cooling Conventional",
    4: "1 Compressor Heat Pump (1-AUX)",
    5: "2 Compressors or 2 Speed Compressor Heat Pump (1-AUX)",
    6: "2 Compressors or 2 Speed Compressor Heat Pump (2-AUX)",
}
HVAC_SET = 13
EDITABLE = [k for k, (_, _, kind) in SETTINGS.items() if kind != "info"] + [
    "system_type"
]
# What only an admin may change: how the equipment is wired and set up.
INSTALLER = {
    "heat_pump_changeover",
    "furnace_type",
    "system_type",
    "auto_deadband",
    "dehumidify_to",
    "min_fan_runtime",
    "temperature_offset",
    "humidity_offset",
    "dehumidify",
    "power_wires",
    *STAGE_OFFSETS,
}
# Values kept to a range a thermostat is normally set to, so a typing slip
# cannot reach the thermostat.
LIMITS: dict[str, tuple[float, float]] = {
    "dehumidify_to": (25, 75),  # percent
    "min_fan_runtime": (0, 60),  # minutes an hour
    "temperature_offset": (-5, 5),  # degrees
    "humidity_offset": (-10, 10),  # percent
    "auto_deadband": (2, 9),  # degrees between heating and cooling
    **{key: (0, 10) for key in STAGE_OFFSETS},  # degrees from the set point
}
