# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
species_loader.py — Species-agnostic configuration loader for Mycodo decision engine.

Reads species YAML configs from species/ directory.
Provides unified interface: load_species() returns phase definitions compatible
with the existing decision engine.
"""

import yaml
from pathlib import Path
from typing import Dict, Any

SPECIES_DIR = Path(__file__).parent.parent / "species"


def load_species(species_id: str) -> Dict[str, Any]:
    """
    Load a species config and return structured phase definitions.

    Returns:
        {
            "species_id": str,
            "common_name": str,
            "scientific_name": str,
            "phases": {phase_name: phase_dict, ...},
            "sensor_authority": {"temperature": "sht45", ...},
            "safety": {"oversaturation_guard_rh": 98, ...},
        }
    """
    species_path = SPECIES_DIR / f"{species_id}.yaml"
    if not species_path.exists():
        raise ValueError(
            f"Species '{species_id}' not found. Available: {list_available_species()}"
        )

    with open(species_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Transform YAML nested structure to flat PHASES-compatible dict
    phases = {}
    for phase_name, phase_data in config.get("phases", {}).items():
        # Normalize: lowercase, replace hyphens with underscores for internal use
        phase_key = phase_name.lower().replace("-", "_").replace(" ", "_")
        # Build fan_rules with defaults for inactive phases
        raw_fan = phase_data.get("fan_rules", {})
        fan_rules = {
            "authority": raw_fan.get("authority", False),
            "mode": raw_fan.get("mode", "burst"),
            "reason": raw_fan.get("reason", ""),
            "co2_trigger": raw_fan.get("co2_trigger", 1200),
            "co2_critical": raw_fan.get("co2_critical", 2000),
            "humidity_floor": raw_fan.get("humidity_floor", 88),
            "burst_duration": raw_fan.get("burst_duration", 30),
        }

        # Build humidifier_rules with defaults
        raw_hum = phase_data.get("humidifier_rules", {})
        humidifier_rules = {
            "authority": raw_hum.get("authority", False),
            "active": raw_hum.get("active", True),
            "humidity_target": raw_hum.get("humidity_target", 92),
            "deadband_low": raw_hum.get("deadband_low", 85),
            "deadband_high": raw_hum.get("deadband_high", 98),
            "mode": raw_hum.get("mode", "pulse"),
            "reason": raw_hum.get("reason", ""),
        }

        # Build targets with null-safe defaults
        raw_targets = phase_data.get("targets", {})
        targets = {}
        for metric in ["temperature", "humidity", "co2"]:
            if metric in raw_targets:
                targets[metric] = raw_targets[metric]
            else:
                targets[metric] = {
                    "ideal_min": None, "ideal_max": None,
                    "accept_min": None, "accept_max": None,
                    "alert_min": None, "alert_max": None,
                }

        phases[phase_key] = {
            "label": phase_data["label"],
            "description": phase_data.get("description", ""),
            "duration_estimate": phase_data.get("duration_estimate", 7),
            "transition_trigger": phase_data.get("transition_trigger", "auto"),
            "targets": targets,
            "fan_rules": fan_rules,
            "humidifier_rules": humidifier_rules,
            "notes": phase_data.get("notes", ""),
        }

    return {
        "species_id": config["species_id"],
        "common_name": config["common_name"],
        "scientific_name": config["scientific_name"],
        "phases": phases,
        "sensor_authority": config.get("sensor_authority", {
            "temperature": "sht45",
            "humidity": "sht45",
            "co2": "scd41",
        }),
        "safety": config.get("safety", {
            "oversaturation_guard_rh": 98,
            "max_temp": 28,
            "min_temp": 10,
            "sensor_offline_minutes": 30,
        }),
    }


def list_available_species() -> list:
    """Return list of available species IDs."""
    return [p.stem for p in SPECIES_DIR.glob("*.yaml") if p.stem != "README"]


def get_phase(species_data: Dict[str, Any], phase_name: str) -> Dict[str, Any]:
    """Get a specific phase from a loaded species config."""
    phase_key = phase_name.strip().lower().replace("-", "_").replace(" ", "_")
    # Handle aliases
    aliases = {
        "colonisation": "colonization",
        "pinning": "primordia",
        "pins": "primordia",
        "second_flush": "fruiting",
        "second_flush_fruiting": "fruiting",
        "late_stage_fruiting": "late_stage_fruiting",
        "late-stage-fruiting": "late_stage_fruiting",
        "ants": "antler_development",
        "conk": "primordia",  # Reishi conk formation is triggered from primordia
    }

    phase_key = aliases.get(phase_key, phase_key)

    if phase_key not in species_data["phases"]:
        raise ValueError(
            f"Phase '{phase_name}' not found for species {species_data['species_id']}. "
            f"Valid: {list(species_data['phases'].keys())}"
        )

    return species_data["phases"][phase_key]


def assess(value: float, thresholds: Dict[str, float]) -> str:
    """Return status: ideal | acceptable | alert"""
    ideal_min = thresholds.get("ideal_min")
    ideal_max = thresholds.get("ideal_max")
    accept_min = thresholds.get("accept_min")
    accept_max = thresholds.get("accept_max")

    # If all thresholds are None/null, treat as unmonitored — return "ideal"
    if ideal_min is None and ideal_max is None and accept_min is None and accept_max is None:
        return "unmonitored"

    if (ideal_min is None or value >= ideal_min) and (ideal_max is None or value <= ideal_max):
        return "ideal"
    if (accept_min is None or value >= accept_min) and (accept_max is None or value <= accept_max):
        return "acceptable"
    return "alert"


def classify_all(metrics: Dict[str, float], phase_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    metrics: {"temperature": val, "humidity": val, "co2": val}
    phase_data: output from get_phase()
    Returns: dict with per-metric status, overall status, deviation summary.
    """
    targets = phase_data.get("targets", {})
    results = {}
    overall = "ideal"

    for metric, val in metrics.items():
        if metric not in targets:
            continue
        status = assess(val, targets[metric])
        results[metric] = {
            "value": val,
            "status": status,
            "ideal": (targets[metric].get("ideal_min"), targets[metric].get("ideal_max")),
            "acceptable": (targets[metric].get("accept_min"), targets[metric].get("accept_max")),
        }
        if status == "alert":
            overall = "alert"
        elif status == "acceptable" and overall != "alert":
            overall = "acceptable"

    return {
        "overall": overall,
        "metrics": results,
        "phase": phase_data["label"],
    }


# --- Legacy compatibility wrapper ---
# This allows gradual migration from phase_config.py to species-loader.yaml

def load_legacy_phases() -> Dict[str, Any]:
    """Load Lion's Mane config in the old flat PHASES format for backward compat."""
    return load_species("lions_mane")["phases"]


if __name__ == "__main__":
    print("Available species:", list_available_species())

    # Demo: load each species and show phases
    for species_id in list_available_species():
        data = load_species(species_id)
        print(f"\n{species_id}: {data['common_name']} ({data['scientific_name']})")
        print(f"  Phases: {list(data['phases'].keys())}")
        print(f"  Safety oversaturation guard: {data['safety']['oversaturation_guard_rh']}% RH")
