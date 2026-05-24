# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
phase_config.py — Lion's Mane phase definitions for Mycodo decision engine.

This module is the machine-readable source consumed by decision_engine.py.
"""

PHASES = {
    "colonization": {
        "label": "Colonization",
        "description": "Mycelium growing through substrate. High CO2 is normal.",
        "targets": {
            "temperature": {"ideal_min": 21, "ideal_max": 24, "accept_min": 18, "accept_max": 26, "alert_min": 16, "alert_max": 28},
            "humidity": {"ideal_min": 85, "ideal_max": 95, "accept_min": 80, "accept_max": 95, "alert_min": 75, "alert_max": 98},
            "co2": {"ideal_min": 2000, "ideal_max": 5000, "accept_min": 0, "accept_max": 8000, "alert_min": 0, "alert_max": 10000},
        },
        "fan_rules": {
            "authority": False,
            "burst_duration": 360,
            "humidity_floor": 80,
            "co2_trigger": 10000,
            "co2_critical": 15000,
        },
        "notes": "Fan OFF by default. Only fire for anaerobic risk (>10k ppm) or condensation (>98%).",
    },
    "primordia": {
        "label": "Primordia / Pinning Initiation",
        "description": "Transition phase. Temp drop + fresh air trigger pin formation.",
        "targets": {
            "temperature": {"ideal_min": 15, "ideal_max": 18, "accept_min": 13, "accept_max": 20, "alert_min": 10, "alert_max": 22},
            "humidity": {"ideal_min": 90, "ideal_max": 95, "accept_min": 85, "accept_max": 97, "alert_min": 85, "alert_max": 98},
            "co2": {"ideal_min": 500, "ideal_max": 800, "accept_min": 0, "accept_max": 1000, "alert_min": 0, "alert_max": 1200},
        },
        "fan_rules": {
            "authority": True,
            "burst_duration": 360,
            "humidity_floor": 85,
            "co2_trigger": 800,
            "co2_critical": 1000,
        },
        "notes": "Fan authority ACTIVE. Fresh air is critical. Do NOT fire fan if humidity <85%.",
    },
    "fruiting": {
        "label": "Fruiting (Exposed Blocks — Lower Ceiling)",
        "description": "Active mushroom growth with exposed mycelium blocks. Humidifier and fan must co-fire.",
        "targets": {
            "temperature": {"ideal_min": 16, "ideal_max": 18, "accept_min": 15, "accept_max": 21, "alert_min": 12, "alert_max": 24},
            "humidity": {"ideal_min": 90, "ideal_max": 93, "accept_min": 85, "accept_max": 93, "alert_min": 80, "alert_max": 98},
            "co2": {"ideal_min": 400, "ideal_max": 600, "accept_min": 0, "accept_max": 800, "alert_min": 0, "alert_max": 1000},
        },
        "fan_rules": {
            "authority": True,
            "burst_duration": 360,
            "humidity_floor": 88,
            "co2_trigger": 800,
            "co2_critical": 1000,
        },
        "notes": "Exposed blocks: accept_max lowered to 93% to prevent saturation. Humidifier OFF at 93% (deadband: 85-93). Fan must co-fire when humidifier turns on.",
    },
    "late-stage-fruiting": {
        "label": "Late-Stage Fruiting",
        "description": "Days to 1 week remaining. Large fruiting bodies. CO2 is THE priority.",
        "targets": {
            "temperature": {"ideal_min": 16, "ideal_max": 18, "accept_min": 15, "accept_max": 21, "alert_min": 12, "alert_max": 24},
            "humidity": {"ideal_min": 90, "ideal_max": 95, "accept_min": 85, "accept_max": 98, "alert_min": 80, "alert_max": 100},
            "co2": {"ideal_min": 400, "ideal_max": 600, "accept_min": 0, "accept_max": 800, "alert_min": 0, "alert_max": 1000},
        },
        "fan_rules": {
            "authority": True,
            "burst_duration": 0,
            "humidity_floor": 0,
            "co2_trigger": 0,
            "co2_critical": 0,
            "mode": "continuous",
        },
        "notes": "Fan stays ON continuously unless operator explicitly directs OFF. Humidity floor rules SUSPENDED.",
    },
    "rest": {
        "label": "Rest / Drying",
        "description": "Post-harvest drying or idle state. No active growth.",
        "targets": {
            "temperature": {"ideal_min": 16, "ideal_max": 21, "accept_min": 14, "accept_max": 24, "alert_min": 10, "alert_max": 28},
            "humidity": {"ideal_min": 65, "ideal_max": 75, "accept_min": 50, "accept_max": 85, "alert_min": 30, "alert_max": 95},
            "co2": {"ideal_min": 400, "ideal_max": 800, "accept_min": 0, "accept_max": 1500, "alert_min": 0, "alert_max": 2000},
        },
        "fan_rules": {
            "authority": False,
            "burst_duration": 0,
            "humidity_floor": 50,
            "co2_trigger": 2000,
            "co2_critical": 3000,
        },
        "notes": "Monitor only. Fan for excess CO2 or humidity. Drying target: low humidity.",
    },
}


def get_phase(name: str) -> dict:
    name = name.strip().lower().replace("-", "_")
    # Aliases
    aliases = {
        "colonisation": "colonization",
        "pinning": "primordia",
        "pins": "primordia",
        "second_flush": "fruiting",
        "second_flush_fruiting": "fruiting",
        "late_stage_fruiting": "late-stage-fruiting",
    }
    phase_key = aliases.get(name, name)
    if phase_key not in PHASES:
        raise ValueError(f"Unknown phase '{name}'. Valid: {list(PHASES.keys())}")
    return PHASES[phase_key]


def assess(value: float, thresholds: dict) -> str:
    """Return status: ideal | acceptable | alert"""
    if thresholds["ideal_min"] <= value <= thresholds["ideal_max"]:
        return "ideal"
    if thresholds["accept_min"] <= value <= thresholds["accept_max"]:
        return "acceptable"
    return "alert"


def classify_all(metrics: dict, phase_name: str) -> dict:
    """
    metrics: {"temperature": val, "humidity": val, "co2": val}
    Returns: dict with per-metric status, overall status, deviation summary.
    """
    phase = get_phase(phase_name)
    results = {}
    overall = "ideal"
    for metric, val in metrics.items():
        if metric not in phase["targets"]:
            continue
        status = assess(val, phase["targets"][metric])
        results[metric] = {
            "value": val,
            "status": status,
            "ideal": (phase["targets"][metric]["ideal_min"], phase["targets"][metric]["ideal_max"]),
            "acceptable": (phase["targets"][metric]["accept_min"], phase["targets"][metric]["accept_max"]),
        }
        if status == "alert":
            overall = "alert"
        elif status == "acceptable" and overall != "alert":
            overall = "acceptable"
    return {"overall": overall, "metrics": results, "phase": phase_name}
