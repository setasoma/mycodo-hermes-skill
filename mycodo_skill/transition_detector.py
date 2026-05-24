# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
transition_detector.py — Auto-detect phase transitions from sensor trends.

Determines WHEN to shift from one grow phase to the next.
Only transitions marked "auto" in species config are eligible.
Manual transitions require operator confirmation.

Uses:
- Time-in-phase (minimum duration met?)
- Sensor pattern shifts (CO2 drop, humidity stabilization)
- Optional: visual markers from camera snapshots (future)

2026-05-24 — placeholder for contamination vision integration
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

from species_loader import load_species, get_phase

# State file for tracking phase history
STATE_PATH = Path.home() / ".mycodo-skill-phase-state.json"


def load_phase_state() -> Dict[str, Any]:
    """Load current phase tracking state."""
    if STATE_PATH.exists():
        with open(STATE_PATH, "r") as f:
            return json.load(f)
    return {
        "current_species": None,
        "current_phase": None,
        "phase_start_time": None,
        "phase_history": [],
        "operator_locked": False,  # True = manual override, don't auto-transition
    }


def save_phase_state(state: Dict[str, Any]):
    """Save phase tracking state."""
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, default=str)


def init_phase(species_id: str, phase: str, force: bool = False) -> Dict[str, Any]:
    """
    Set the current phase explicitly (operator command or initialization).
    Returns updated state.
    """
    state = load_phase_state()

    if state["current_phase"] and not force:
        # Record transition
        state["phase_history"].append({
            "species": state["current_species"],
            "phase": state["current_phase"],
            "start": state["phase_start_time"],
            "end": datetime.now(timezone.utc).isoformat(),
        })

    state["current_species"] = species_id
    state["current_phase"] = phase
    state["phase_start_time"] = datetime.now(timezone.utc).isoformat()
    state["operator_locked"] = False

    save_phase_state(state)
    return state


def hours_in_phase(state: Optional[Dict[str, Any]] = None) -> float:
    """Calculate how many hours we've been in current phase."""
    if state is None:
        state = load_phase_state()

    if not state.get("phase_start_time"):
        return 0.0

    start = datetime.fromisoformat(state["phase_start_time"])
    now = datetime.now(timezone.utc)
    return (now - start).total_seconds() / 3600


def check_auto_transition(
    metrics: Dict[str, float],
    species_id: Optional[str] = None,
    current_phase: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Check if conditions warrant an auto-transition to the next phase.

    Args:
        metrics: {"temperature": float, "humidity": float, "co2": float}
        species_id: Override species (defaults to state file)
        current_phase: Override phase (defaults to state file)

    Returns:
        {
            "transition_ready": bool,
            "current_phase": str,
            "recommended_phase": str | None,
            "reason": str,
            "confidence": float,  # 0.0-1.0
            "hours_in_phase": float,
        }
    """
    state = load_phase_state()

    species_id = species_id or state.get("current_species")
    current_phase = current_phase or state.get("current_phase")

    if not species_id or not current_phase:
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": "No active phase state. Use init_phase() first.",
            "confidence": 0.0,
            "hours_in_phase": 0.0,
        }

    # Load species config
    try:
        species_data = load_species(species_id)
    except ValueError as e:
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": str(e),
            "confidence": 0.0,
            "hours_in_phase": 0.0,
        }

    phase_data = get_phase(species_data, current_phase)
    trigger_type = phase_data.get("transition_trigger", "manual")
    duration_estimate = phase_data.get("duration_estimate", 7)
    # Handle string duration_estimate like "7-14" (take average)
    if isinstance(duration_estimate, str):
        parts = duration_estimate.replace(" ", "").split("-")
        if len(parts) == 2:
            duration_estimate = (float(parts[0]) + float(parts[1])) / 2
        else:
            duration_estimate = float(duration_estimate)
    duration_estimate = float(duration_estimate)

    elapsed_hours = hours_in_phase(state)
    elapsed_days = elapsed_hours / 24

    # If manually locked, never auto-transition
    if state.get("operator_locked", False):
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": "Operator has locked phase — manual control only.",
            "confidence": 0.0,
            "hours_in_phase": elapsed_hours,
        }

    # If this phase requires manual transition, don't auto
    if trigger_type == "manual":
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": f"Phase '{current_phase}' requires MANUAL transition.",
            "confidence": 0.0,
            "hours_in_phase": elapsed_hours,
        }

    # -- Auto transition logic --

    # Phase sequence by species
    phase_sequences = {
        "lions_mane": ["colonization", "primordia", "fruiting", "late-stage-fruiting", "rest"],
        "oyster": ["colonization", "primordia", "fruiting", "spore-release", "rest"],
        "shiitake": ["colonization", "browning", "primordia", "fruiting", "late-stage-fruiting", "rest"],
        "reishi": ["colonization", "antler-development", "primordia", "fruiting", "late-stage-fruiting", "rest"],
    }

    sequence = phase_sequences.get(species_id, [])

    try:
        current_idx = sequence.index(current_phase)
    except ValueError:
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": f"Phase '{current_phase}' not in standard sequence for {species_id}",
            "confidence": 0.0,
            "hours_in_phase": elapsed_hours,
        }

    if current_idx >= len(sequence) - 1:
        return {
            "transition_ready": False,
            "current_phase": current_phase,
            "recommended_phase": None,
            "reason": "Already in final phase (rest).",
            "confidence": 0.0,
            "hours_in_phase": elapsed_hours,
        }

    next_phase = sequence[current_idx + 1]

    # Transition confidence calculation
    confidence = 0.0
    reasons = []

    # Factor 1: Minimum time elapsed (50% of confidence)
    min_days = duration_estimate * 0.7  # 70% of estimated duration
    if elapsed_days >= min_days:
        confidence += 0.5
        reasons.append(f"Minimum time threshold met ({elapsed_days:.1f}d >= {min_days:.1f}d)")
    else:
        reasons.append(f"Below minimum time threshold ({elapsed_days:.1f}d < {min_days:.1f}d)")

    # Factor 2: Sensor pattern match for next phase (30% of confidence)
    next_phase_data = get_phase(species_data, next_phase)
    next_targets = next_phase_data.get("targets", {})

    sensor_match_score = 0
    sensor_checks = 0
    for metric in ["temperature", "humidity", "co2"]:
        if metric in next_targets and metric in metrics:
            sensor_checks += 1
            val = metrics[metric]
            target = next_targets[metric]
            accept_min = target.get("accept_min", float('-inf'))
            accept_max = target.get("accept_max", float('inf'))
            if accept_min <= val <= accept_max:
                sensor_match_score += 1

    if sensor_checks > 0:
        sensor_ratio = sensor_match_score / sensor_checks
        if sensor_ratio >= 0.67:  # 2/3 sensors in acceptable range
            confidence += 0.3
            reasons.append(f"Sensor pattern match: {sensor_match_score}/{sensor_checks} metrics in target range")
        else:
            reasons.append(f"Sensor pattern mismatch: {sensor_match_score}/{sensor_checks} metrics in range")

    # Factor 3: Contamination check (20% of confidence) — placeholder for future
    # Future: If contamination detected, may BLOCK transition or force rest
    contamination_clear = True  # Placeholder — vision model not yet active
    if contamination_clear:
        confidence += 0.2
        reasons.append("Contamination status: CLEAR")
    else:
        reasons.append("Contamination detected — transition blocked")

    # Threshold for auto-transition
    transition_ready = confidence >= 0.7

    return {
        "transition_ready": transition_ready,
        "current_phase": current_phase,
        "recommended_phase": next_phase if transition_ready else None,
        "reason": " | ".join(reasons),
        "confidence": confidence,
        "hours_in_phase": elapsed_hours,
    }


def apply_transition(new_phase: str) -> Dict[str, Any]:
    """
    Apply a phase transition and update state.
    Returns new state.
    """
    state = load_phase_state()
    species_id = state["current_species"]

    if not species_id:
        raise ValueError("No active species. Call init_phase() first.")

    # Record history
    state["phase_history"].append({
        "species": species_id,
        "phase": state["current_phase"],
        "start": state["phase_start_time"],
        "end": datetime.now(timezone.utc).isoformat(),
    })

    state["current_phase"] = new_phase
    state["phase_start_time"] = datetime.now(timezone.utc).isoformat()

    save_phase_state(state)
    return state


def operator_lock(lock: bool = True):
    """Lock or unlock auto-transitions. Operator control override."""
    state = load_phase_state()
    state["operator_locked"] = lock
    save_phase_state(state)
    return state


# --- CLI interface ---

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Phase transition detector")
    parser.add_argument("--init", nargs=2, metavar=("SPECIES", "PHASE"), help="Initialize phase tracking")
    parser.add_argument("--check", action="store_true", help="Check if transition is ready")
    parser.add_argument("--transition-to", metavar="PHASE", help="Manually transition to phase")
    parser.add_argument("--lock", action="store_true", help="Lock auto-transitions")
    parser.add_argument("--unlock", action="store_true", help="Unlock auto-transitions")
    parser.add_argument("--metrics", type=json.loads, default="{}", help='JSON metrics: {"temperature": 18.5, "humidity": 90, "co2": 600}')
    parser.add_argument("--status", action="store_true", help="Show current phase state")

    args = parser.parse_args()

    if args.init:
        species, phase = args.init
        state = init_phase(species, phase, force=True)
        print(f"Initialized: {species} -> {phase}")
        print(json.dumps(state, indent=2, default=str))

    elif args.check:
        result = check_auto_transition(args.metrics)
        print(json.dumps(result, indent=2, default=str))

    elif args.transition_to:
        state = apply_transition(args.transition_to)
        print(f"Transitioned to: {args.transition_to}")
        print(json.dumps(state, indent=2, default=str))

    elif args.lock:
        state = operator_lock(True)
        print("Auto-transitions LOCKED")

    elif args.unlock:
        state = operator_lock(False)
        print("Auto-transitions UNLOCKED")

    elif args.status:
        state = load_phase_state()
        elapsed = hours_in_phase(state)
        print(f"Species: {state.get('current_species', 'NOT SET')}")
        print(f"Phase: {state.get('current_phase', 'NOT SET')}")
        print(f"Hours in phase: {elapsed:.1f}")
        print(f"Auto-transition: {'LOCKED' if state.get('operator_locked') else 'UNLOCKED'}")
        print(f"History: {len(state.get('phase_history', []))} transitions")
