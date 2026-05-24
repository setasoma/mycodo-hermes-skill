# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
followup_checker.py — Lightweight sensor verifier for adaptive environmental loop.
Runs after an actuator action to confirm environment improved. No LLM required.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

FLAG_FILE = Path.home() / ".mycodo-skill-followup"
LOG_FILE = Path.home() / ".mycodo-skill-followup-log.jsonl"
SCRIPT_DIR = Path(os.environ.get("MYCODO_SKILL_BASE", str(Path(__file__).parent)))


def fetch_quick() -> dict:
    """Run sensor-query.sh quick and parse the three JSON lines."""
    result = subprocess.run(
        ["bash", str(SCRIPT_DIR / "sensor-query.sh"), "quick"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode != 0:
        raise RuntimeError(f"sensor-query failed: {result.stderr.strip()}")

    data = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("==="):
            continue
        try:
            obj = json.loads(line)
            # Infer which metric from the response shape
            if "value" in obj and "time" in obj:
                # Heuristic: CO2 usually >500, humidity 30-99, temp 10-40
                # Check HIGHEST thresholds first to avoid misclassification
                val = obj["value"]
                if val > 200:
                    data["co2"] = val
                elif val > 50:
                    data["humidity"] = val
                else:
                    data["temperature"] = val
        except json.JSONDecodeError:
            continue
    return data


def load_flag() -> dict | None:
    if not FLAG_FILE.exists():
        return None
    try:
        with open(FLAG_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def load_prev(flag: dict) -> dict | None:
    prev_file = Path(flag.get("prev_file", "/dev/null"))
    if not prev_file.exists():
        return None
    try:
        with open(prev_file, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def run_cross_run_guards(current: dict) -> list[str]:
    """Return list of cross-run guard alerts. Run every invocation, flag or no flag."""
    alerts = []
    hum = current.get("humidity")
    co2 = current.get("co2")

    # Guard: upper humidity ceiling — approaching oversaturation
    if hum is not None and hum >= 93:
        alerts.append(f"GUARD: humidity {hum:.1f}% >=93% — near oversaturation zone (ceiling lowered for exposed blocks)")

    # Guard: CO2 stagnation — dangerous build-up
    if co2 is not None and co2 > 1000:
        alerts.append(f"GUARD: CO2 {co2:.0f} ppm >1000 — ventilation check needed")

    return alerts


def check_action(prev: dict, current: dict, action: dict) -> dict:
    """Return assessment of whether the action had expected effect."""
    actuator = action.get("actuator")
    command = action.get("command", "")
    guards = []
    good = True
    msg = ""

    if actuator == "humidifier":
        prev_hum = prev.get("humidity")
        curr_hum = current.get("humidity")
        if prev_hum is None or curr_hum is None:
            return {"ok": False, "msg": "Missing humidity readings for follow-up", "guards": guards}
        if "off" in command:
            # Expect humidity to decrease
            if curr_hum >= prev_hum:
                good = False
                msg = f"HUMIDIFIER OFF: humidity NOT dropping ({prev_hum:.1f}% -> {curr_hum:.1f}%)"
            else:
                msg = f"HUMIDIFIER OK: humidity dropping ({prev_hum:.1f}% -> {curr_hum:.1f}%)"
        elif "on" in command:
            rise = curr_hum - prev_hum
            if curr_hum <= prev_hum:
                good = False
                msg = f"HUMIDIFIER ON: humidity NOT rising ({prev_hum:.1f}% -> {curr_hum:.1f}%)"
            else:
                msg = f"HUMIDIFIER OK: humidity rising ({prev_hum:.1f}% -> {curr_hum:.1f}%)"
            # Guard: runaway rise (>8% in 10 min means out-of-control)
            if rise > 8:
                guards.append(f"GUARD: humidity jumped +{rise:.1f}% in follow-up window — possible overshoot")
            # Oversaturation warning
            if curr_hum >= 98:
                guards.append(f"GUARD: humidity {curr_hum:.1f}% >=98% — humidifier needs OFF + fan burst")

    elif actuator == "fan":
        prev_hum = prev.get("humidity")
        curr_hum = current.get("humidity")
        prev_co2 = prev.get("co2")
        curr_co2 = current.get("co2")
        if prev_co2 is None or curr_co2 is None:
            return {"ok": False, "msg": "Missing CO2 readings for follow-up", "guards": guards}
        if curr_co2 >= prev_co2:
            good = False
            msg = f"FAN VENT: CO2 NOT dropping ({prev_co2:.0f} -> {curr_co2:.0f} ppm)"
        else:
            msg = f"FAN OK: CO2 dropping ({prev_co2:.0f} -> {curr_co2:.0f} ppm)"
            # Also check humidity didn't crater
            if prev_hum and curr_hum and curr_hum < prev_hum - 5:
                guards.append(f"WARNING: humidity dropped hard ({prev_hum:.1f}% -> {curr_hum:.1f}%)")
    else:
        return {"ok": True, "msg": f"Unknown actuator {actuator}, skipping follow-up", "guards": guards}

    return {"ok": good, "msg": msg, "guards": guards}


def main():
    parser = argparse.ArgumentParser(description="Mycodo adaptive follow-up checker")
    parser.add_argument("--clear", action="store_true", help="Clear flag after checking")
    args = parser.parse_args()

    # =========================================================================
    # PHASE 1: Always-on cross-run guards (run every invocation, flag or no flag)
    # =========================================================================
    try:
        current = fetch_quick()
    except RuntimeError as e:
        print(f"Follow-up FAILED to fetch sensors: {e}")
        sys.exit(1)

    cross_alerts = run_cross_run_guards(current)

    # =========================================================================
    # PHASE 2: Per-action follow-up (requires flag file)
    # =========================================================================
    flag = load_flag()
    if not flag:
        # No flag — still report any cross-run guards
        if cross_alerts:
            for alert in cross_alerts:
                print(alert)
            sys.exit(2)
        sys.exit(0)

    # Check if minimum wait has passed (default 10 minutes)
    fired_at = flag.get("fired_at", 0)
    wait_seconds = flag.get("wait_seconds", 600)
    if (time.time() - fired_at) < wait_seconds:
        if cross_alerts:
            for alert in cross_alerts:
                print(alert)
            sys.exit(2)
        sys.exit(0)

    prev = load_prev(flag)
    if not prev:
        print("Follow-up: no previous readings to compare")
        if args.clear:
            FLAG_FILE.unlink(missing_ok=True)
        if cross_alerts:
            for alert in cross_alerts:
                print(alert)
            sys.exit(2)
        sys.exit(0)

    action = flag.get("action", {})
    result = check_action(prev, current, action)

    log_entry = {
        "timestamp": time.time(),
        "action": action,
        "previous": prev,
        "current": current,
        "result": result,
        "cross_alerts": cross_alerts,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry) + "\n")

    # Report cross-run guards first, then action result
    exit_code = 0 if result["ok"] else 1
    if result.get("guards"):
        for g in result["guards"]:
            print(g)
            # Any guard forces non-zero exit so cron alerts
            if exit_code == 0:
                exit_code = 2  # guard alert (distinct from action fail)

    if cross_alerts:
        for alert in cross_alerts:
            print(alert)
            if exit_code == 0:
                exit_code = 2

    prefix = "OK:" if result["ok"] else "WARNING:"
    print(f"{prefix} {result['msg']}")

    if args.clear:
        FLAG_FILE.unlink(missing_ok=True)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
