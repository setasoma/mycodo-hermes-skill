# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
decision_engine.py — Phase-aware environmental decision engine for Mycodo grow automation.

CHANGELOG 2026-05-20:
- Auto-queries live fan state before every decision (no more actuator-blind firing)
- Reads ~/.mycodo-skill-override.json for operator protocols (respects manual overrides)
- If fan already ON per operator directive, skips redundant commands
- Safety gates still apply even during operator override
- Logs operator override context in every decision output

CHANGELOG 2026-05-24:
- Camera snapshot integration: optionally fetches latest jpg and embeds path in report
  so the agent can relay the image. Strictly WMI (write-mechanical-instruction) —
  no vision claim, no contamination analysis promise. The image is for the operator.
"""

import argparse
import base64
import csv
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

scripts_dir = Path(__file__).parent
sys.path.insert(0, str(scripts_dir))

# Try to import species_loader; fall back to legacy phase_config
try:
    from species_loader import load_species, get_phase as get_phase_species, classify_all as classify_all_species, list_available_species
    from phase_config import classify_all, get_phase
    SPECIES_MODE = True
except ImportError:
    SPECIES_MODE = False
    print("# [WARN] species_loader not available — falling back to legacy phase_config.py", file=sys.stderr)
    from phase_config import classify_all, get_phase

SHT45_ID_FRAG = "8523956e"
SCD41_ID_FRAG = "cb36c5c3"
OVERRIDE_PATH = Path.home() / ".mycodo-skill-override.json"



def _device_type(device_id: str) -> str:
    if SHT45_ID_FRAG in device_id:
        return "sht45"
    if SCD41_ID_FRAG in device_id:
        return "scd41"
    return "unknown"


def parse_influx_csv(csv_text: str) -> dict:
    reader = csv.DictReader(io.StringIO(csv_text))
    results = {}
    for row in reader:
        if row.get("_field") != "value":
            continue
        metric = row.get("measure", "")
        device = row.get("device_id", "")
        value = float(row["_value"])
        dev_type = _device_type(device)
        if dev_type == "unknown":
            continue
        key = f"{metric}_{dev_type}"
        results[key] = value
    return results


def fetch_snapshot() -> str:
    script = scripts_dir / "sensor-query.sh"
    result = subprocess.run(
        ["bash", str(script), "snapshot"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"sensor-query snapshot failed: {result.stderr.strip()}")
    return result.stdout


def fetch_fan_status() -> dict:
    """Query live fan state from Mycodo. Returns {"state": "on"/"off", "source": "live"} or error dict."""
    script = scripts_dir / "sensor-query.sh"
    result = subprocess.run(
        ["bash", str(script), "fan_status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return {"state": "unknown", "error": result.stderr.strip(), "source": "failed"}
    try:
        data = json.loads(result.stdout)
        channel_states = data.get("output device channel states", {})
        state = channel_states.get("0", "unknown")
        return {"state": state, "source": "live", "raw": data}
    except json.JSONDecodeError:
        # Fallback: grep for "on" or "off" in raw output
        raw = result.stdout.lower()
        if '"0": "on"' in raw or '"on"' in raw:
            return {"state": "on", "source": "live", "raw_fallback": True}
        if '"0": "off"' in raw or '"off"' in raw:
            return {"state": "off", "source": "live", "raw_fallback": True}
        return {"state": "unknown", "source": "parse-failed", "raw": result.stdout}



def fetch_humidifier_status() -> dict:
    """Query live humidifier state from Mycodo. Returns {"state": "on"/"off", "source": "live"} or error dict."""
    script = scripts_dir / "sensor-query.sh"
    result = subprocess.run(
        ["bash", str(script), "humidifier_status"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode != 0:
        return {"state": "unknown", "error": result.stderr.strip(), "source": "failed"}
    try:
        data = json.loads(result.stdout)
        channel_states = data.get("output device channel states", {})
        state = channel_states.get("0", "unknown")
        return {"state": state, "source": "live", "raw": data}
    except json.JSONDecodeError:
        raw = result.stdout.lower()
        if '"0": "on"' in raw or '"on"' in raw:
            return {"state": "on", "source": "live", "raw_fallback": True}
        if '"0": "off"' in raw or '"off"' in raw:
            return {"state": "off", "source": "live", "raw_fallback": True}
        return {"state": "unknown", "source": "parse-failed", "raw": result.stdout}


def fetch_camera(snapshot_dir: Path | None = None) -> dict:
    """Pull latest.jpg via sensor-query.sh camera. Returns path dict or error dict."""
    dest = snapshot_dir / "latest.jpg" if snapshot_dir else Path("/tmp/mycodo_latest.jpg")
    script = scripts_dir / "sensor-query.sh"
    result = subprocess.run(
        ["bash", str(script), "camera", str(dest)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    # Parse stdout line like "Saved to /path (817723 bytes)"
    m = re.search(r"Saved to (.+?) \((\d+) bytes\)", result.stdout)
    if m:
        path_str = m.group(1)
    elif dest.exists():
        path_str = str(dest)
    else:
        return {"ok": False, "error": "camera download succeeded but file not found", "stdout": result.stdout}
    # Embed as base64 for inline HTML
    try:
        with open(path_str, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except Exception as e:
        return {"ok": True, "path": path_str, "size": Path(path_str).stat().st_size, "error": f"base64 encode failed: {e}"}
    return {"ok": True, "path": path_str, "size": Path(path_str).stat().st_size, "base64": b64}


def load_override() -> dict | None:
    """Load operator override state from ~/.mycodo-skill-override.json. Returns None if missing or invalid."""
    if not OVERRIDE_PATH.exists():
        return None
    try:
        with open(OVERRIDE_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def build_decision(parsed: dict, phase_name: str, fan_status: dict | None = None, humidifier_status: dict | None = None, override: dict | None = None, mode: str = "dry-run", camera: dict | None = None, species_id: str | None = None) -> dict:
    # --- Species-aware phase loading ---
    if SPECIES_MODE and species_id:
        try:
            species_data = load_species(species_id)
            phase = get_phase_species(species_data, phase_name)
            species_name = species_data["common_name"]
            is_species_mode = True
        except Exception as e:
            # Fall back to legacy
            phase = get_phase(phase_name)
            species_name = "Lion's Mane (legacy)"
            is_species_mode = False
    else:
        phase = get_phase(phase_name)
        species_name = "Lion's Mane (legacy)"
        is_species_mode = False

    fan_rules = phase["fan_rules"]

    metrics = {
        "temperature": parsed.get("temperature_sht45", parsed.get("temperature_scd41")),
        "humidity": parsed.get("humidity_sht45", parsed.get("humidity_scd41")),
        "co2": parsed.get("co2_scd41"),
    }

    missing = [k for k, v in metrics.items() if v is None]
    if missing:
        return {"status": "error", "error": f"Missing sensors: {missing}", "raw_parsed": parsed}

    # Use species-aware classify_all if available
    classification = classify_all_species(metrics, phase) if is_species_mode else classify_all(metrics, phase_name)
    actions = []
    alerts = []
    notes = []

    # Operator override awareness
    fan_override = None
    if override and override.get("active_protocol", {}).get("status") == "active":
        fan_override = override.get("overrides", {}).get("fan")

    fan_state_str = fan_status.get("state", "unknown") if fan_status else "unknown"
    humidifier_state = humidifier_status.get("state", "unknown") if humidifier_status else "unknown"

    # --- FAN DECISIONS ---
    # Priority 1: Late-stage fruiting continuous mode (from phase_config)
    if fan_rules.get("mode") == "continuous":
        if fan_state_str == "on":
            notes.append("Fan already ON (late-stage-fruiting continuous mode). No redundant command.")
        else:
            actions.append({"actuator": "fan", "command": "on", "reason": "late-stage-fruiting: CO2 priority, continuous vent"})
        notes.append("LATE-STAGE: Humidity floor rules are SUSPENDED.")

    # Priority 2: Operator override continuous fan
    elif fan_override and fan_override.get("mode") == "continuous" and fan_override.get("should_be_on"):
        if fan_state_str == "on":
            notes.append(f"Fan already ON per operator override ({fan_override.get('reason', 'manual protocol')}). Skipping redundant command.")
        else:
            actions.append({"actuator": "fan", "command": "on", "reason": f"Operator override: {fan_override.get('reason', 'continuous fan protocol')}"})
        # Safety gate: even during override, alert on critical CO2
        if metrics["co2"] > 2000:
            alerts.append(f"CRITICAL SAFETY: CO2 {metrics['co2']} ppm exceeded 2000 ppm safety gate — despite operator override, ventilation critical")

    # Priority 3: Phase rules with fan authority OFF (non-autonomous phases)
    elif not fan_rules["authority"]:
        if metrics["co2"] > fan_rules["co2_trigger"]:
            if metrics["humidity"] >= fan_rules["humidity_floor"]:
                actions.append({"actuator": "fan", "command": f"burst_{fan_rules['burst_duration']}", "reason": f"CO2 {metrics['co2']} > trigger {fan_rules['co2_trigger']}"})
            else:
                notes.append(f"CO2 high ({metrics['co2']}) but fan blocked: humidity {metrics['humidity']} < floor {fan_rules['humidity_floor']}")
        else:
            notes.append("Fan authority OFF. No fan action needed.")

    # Priority 4: Standard phase rules with fan authority ON
    else:
        if metrics["co2"] > fan_rules["co2_critical"]:
            actions.append({"actuator": "fan", "command": f"burst_{fan_rules['burst_duration']}", "reason": f"CRITICAL: CO2 {metrics['co2']} > {fan_rules['co2_critical']}"})
            alerts.append(f"CRITICAL: CO2 {metrics['co2']} ppm exceeded {fan_rules['co2_critical']} threshold")
        elif metrics["co2"] > fan_rules["co2_trigger"]:
            if metrics["humidity"] >= fan_rules["humidity_floor"]:
                actions.append({"actuator": "fan", "command": f"burst_{fan_rules['burst_duration']}", "reason": f"CO2 {metrics['co2']} exceeds trigger {fan_rules['co2_trigger']}"})
            else:
                notes.append(f"CO2 elevated ({metrics['co2']}) but blocked: humidity {metrics['humidity']} < {fan_rules['humidity_floor']}%")
        if phase["targets"]["humidity"]["alert_max"] is not None and metrics["humidity"] > phase["targets"]["humidity"]["alert_max"]:
            actions.append({"actuator": "fan", "command": f"burst_{fan_rules['burst_duration']}", "reason": f"Humidity {metrics['humidity']}% > ceiling {phase['targets']['humidity']['alert_max']}%"})

    # ===========================================
    # HUMIDITY OVERSATURATION GUARD (May 2026 — second flush exposed blocks)
    # Critical safety: when humidity >=95% with humidifier ON, we are in
    # saturation territory. Turn humidifier OFF and ventilate immediately.
    # Guard fires at 95% (not 98%) because exposed blocks saturate faster.
    # ===========================================
    if metrics["humidity"] >= 95 and humidifier_state == "on":
        actions.append({"actuator": "humidifier", "command": "off", "reason": f"OVERSATURATION GUARD: Humidity {metrics['humidity']}% >= 95% with humidifier ON. Condensation risk."})
        actions.append({"actuator": "fan", "command": f"burst_{fan_rules['burst_duration']}", "reason": "OVERSATURATION GUARD: Ventilating saturated air."})
        alerts.append(f"OVERSATURATION ALERT: Humidity {metrics['humidity']}% — humidifier OFF, fan burst fired")
        notes.append("Oversaturation guard triggered. Standard phase rules suppressed for this cycle.")
        # Skip standard humidifier logic — guard has priority
    else:
        # Humidifier (IoT Power Relay v2 on GPIO5)
        hum_rules = phase["targets"]["humidity"]
        if hum_rules["accept_min"] is not None and metrics["humidity"] < hum_rules["accept_min"]:
            # Co-fire fan burst when humidifier turns on — prevents unchecked rise
            actions.append({"actuator": "humidifier", "command": "on", "reason": f"Humidity {metrics['humidity']}% below acceptable {hum_rules['accept_min']}%"})
            if fan_state_str != "on":
                actions.append({"actuator": "fan", "command": f"burst_120", "reason": "CO-FIRE: Ventilating while humidifier runs to prevent saturation"})
        elif hum_rules["accept_max"] is not None and metrics["humidity"] > hum_rules["accept_max"]:
            # Lower OFF threshold: accept_max (93%) instead of accept_max + 3 (96%)
            actions.append({"actuator": "humidifier", "command": "off", "reason": f"Humidity {metrics['humidity']}% above ceiling {hum_rules['accept_max']}%"})

        # Check if humidifier is under operator control
        if override:
            hum_override = override.get("overrides", {}).get("humidifier")
            if hum_override and not hum_override.get("autonomous_can_control", True):
                had_hum_actions = any(a.get("actuator") == "humidifier" for a in actions)
                actions = [a for a in actions if a.get("actuator") != "humidifier"]
                if had_hum_actions:
                    notes.append("Humidifier is under manual operator control (autonomous control disabled). Humidifier actions suppressed.")

    # Temperature alerts
    temp = metrics["temperature"]
    t_rules = phase["targets"]["temperature"]
    if t_rules["alert_min"] is not None and temp < t_rules["alert_min"]:
        alerts.append(f"CRITICAL: Temperature {temp}°C below alert threshold {t_rules['alert_min']}°C")
    elif t_rules["alert_max"] is not None and temp > t_rules["alert_max"]:
        alerts.append(f"CRITICAL: Temperature {temp}°C above alert threshold {t_rules['alert_max']}°C")

    result = {
        "status": "ok",
        "mode": mode,
        "phase": phase_name,
        "phase_label": phase["label"],
        "timestamp": None,
        "metrics": metrics,
        "classification": classification,
        "actions": actions,
        "alerts": alerts,
        "notes": notes,
        "fan_state": fan_state_str,
        "humidifier_state": humidifier_state,
        "operator_override": fan_override,
    }
    if camera:
        result["camera"] = camera

    # --- Contamination detection placeholder ---
    # When a model is trained, load from ~/.mycodo-skill-contamination-model.json
    # and replace this stub with actual inference
    contamination_config = Path.home() / ".mycodo-skill-contamination-model.json"
    if contamination_config.exists():
        try:
            with open(contamination_config) as f:
                ccfg = json.load(f)
            if ccfg.get("active") and camera and camera.get("ok"):
                # Future: run model inference here
                result["contamination"] = {
                    "status": "stub",
                    "message": "Model config found but inference not yet implemented",
                    "model_path": ccfg.get("model_path"),
                }
            else:
                result["contamination"] = {"status": "inactive", "message": "Model inactive or no camera"}
        except Exception:
            result["contamination"] = {"status": "error", "message": "Failed to load contamination config"}
    else:
        result["contamination"] = {"status": "stub", "message": "No model configured"}

    return result


def format_report(decision: dict) -> str:
    execute_mode = decision.get("mode", "dry-run")
    mode_banner = ""
    if execute_mode == "dry-run":
        mode_banner = "**DRY RUN — NOT EXECUTING RELAYS**\nTo fire actuators, add `--execute` to the command.\n"
    else:
        mode_banner = "**EXECUTION MODE** — relay commands fired.\n"
    if decision["status"] == "error":
        return f"Decision Engine Error: {decision['error']}\nParsed: {json.dumps(decision.get('raw_parsed', {}), indent=2)}"
    lines = []
    lines.append(f"**Mycodo Decision Report** — *{decision['phase_label']}*\n")
    lines.append(mode_banner)
    m = decision["metrics"]
    c = decision["classification"]
    lines.append(f"**SHT45 Primary:** {m['temperature']:.1f}°C | **Humidity:** {m['humidity']:.1f}% | **CO2:** {m['co2']:.0f} ppm")
    lines.append(f"**Overall:** {c['overall'].upper()}\n")

    # Camera attachment
    cam = decision.get("camera")
    if cam and cam.get("ok"):
        lines.append(f"**Camera snapshot:** `{cam['path']}` ({cam['size']:,} bytes)\n")
    elif cam:
        lines.append(f"**Camera unavailable:** {cam.get('error', 'unknown error')}\n")

    # Operator override notice
    override = decision.get("operator_override")
    if override:
        lines.append(f"**Operator Override Active:** {override.get('reason', 'Manual protocol')}")
        lines.append(f"   Fan mode: `{override.get('mode', 'unknown')}` | Autonomous can override: `{override.get('autonomous_can_override', True)}`\n")

    if decision["actions"]:
        lines.append("**Actions:**")
        for a in decision["actions"]:
            stub_mark = " [STUB—requires hardware]" if a.get("stub") else ""
            lines.append(f"  * `{a['actuator']}` -> `{a['command']}`{stub_mark}\n    *{a['reason']}*")
        lines.append("")
    if decision["alerts"]:
        lines.append("**Alerts:**")
        for alert in decision["alerts"]:
            lines.append(f"  * {alert}")
        lines.append("")
    if decision["notes"]:
        lines.append("**Notes:**")
        for note in decision["notes"]:
            lines.append(f"  * {note}")
        lines.append("")
    lines.append(f"_Live fan state: {decision.get('fan_state', 'unknown')} | Live humidifier state: {decision.get('humidifier_state', 'unknown')}_")
    return "\n".join(lines)


# -- HTML report generation (2026-05-24) --
def format_html(decision: dict) -> str:
    """Generate self-contained HTML report from decision dict."""
    if decision["status"] == "error":
        error_html = f"""
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
body {{ background:#0f1115; color:#e2e8f0; font-family:system-ui,-apple-system,sans-serif; padding:40px; max-width:700px; margin:0 auto; }}
h1 {{ color:#ef4444; }}
pre {{ background:#1a1d23; padding:16px; border-radius:8px; overflow-x:auto; }}
</style></head><body>
<h1>Decision Engine Error</h1>
<p>{decision['error']}</p>
<pre>{json.dumps(decision.get('raw_parsed', {}), indent=2, default=str)}</pre>
</body></html>"""
        return error_html

    m = decision["metrics"]
    c = decision["classification"]
    phase = decision["phase_label"]
    execute_mode = decision.get("mode", "dry-run")
    timestamp = decision.get("timestamp") or "--"

    # Status pills
    def pill(label: str, style: str) -> str:
        styles = {
            "optimal": "background:rgba(34,197,94,0.15);color:#22c55e;",
            "warning": "background:rgba(234,179,8,0.15);color:#eab308;",
            "alert": "background:rgba(239,68,68,0.15);color:#ef4444;",
            "info": "background:rgba(100,116,139,0.15);color:#94a3b8;",
        }
        return f'<span style="{styles.get(style, styles["info"])}padding:4px 10px;border-radius:20px;font-size:12px;font-weight:600;display:inline-block;">{label}</span>'

    overall = c["overall"].upper()
    overall_style = "optimal" if overall in ["OPTIMAL", "ON TARGET"] else "warning" if overall in ["ACCEPTABLE", "ELEVATED"] else "alert"

    # Mode banner
    if execute_mode == "dry-run":
        mode_html = '<div style="background:rgba(234,179,8,0.1);border-left:3px solid #eab308;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:20px;"><strong style="color:#eab308;">DRY RUN</strong> — Relay commands are simulated, not fired.</div>'
    else:
        mode_html = '<div style="background:rgba(34,197,94,0.1);border-left:3px solid #22c55e;padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:20px;"><strong style="color:#22c55e;">EXECUTION MODE</strong> — Relay commands fired.</div>'

    # Metric cards
    temp = m["temperature"]
    hum = m["humidity"]
    co2 = m["co2"]

    temp_style = "optimal" if 16 <= temp <= 22 else "warning" if 14 <= temp <= 24 else "alert"
    hum_style = "optimal" if 75 <= hum <= 90 else "warning" if 70 <= hum <= 95 else "alert"
    co2_style = "optimal" if co2 <= 1000 else "warning" if co2 <= 2000 else "alert"

    def card(label: str, value: str, unit: str, status: str) -> str:
        return f'''
        <div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:20px;transition:border-color 0.2s;" onmouseover="this.style.borderColor=\'#22c55e\'" onmouseout="this.style.borderColor=\'#2d3748\'">
          <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;margin-bottom:8px;">{label}</div>
          <div style="font-size:32px;font-weight:700;color:#f1f5f9;">{value}<span style="font-size:14px;color:#94a3b8;margin-left:4px;">{unit}</span></div>
          {pill(status, status.replace(" ", "").lower())}
        </div>'''

    # Camera section
    cam = decision.get("camera")
    cam_html = ""
    if cam and cam.get("ok"):
        if cam.get("base64"):
            cam_html = f'''<div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:24px;margin-bottom:20px;">
              <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;margin-bottom:12px;">Camera Snapshot</div>
              <img src="data:image/jpeg;base64,{cam["base64"]}" alt="Mycodo Tent" style="width:100%;max-width:600px;border-radius:8px;display:block;">
              <div style="margin-top:8px;color:#94a3b8;font-size:12px;">{cam["path"]} ({cam["size"]:,} bytes)</div>
            </div>'''
        else:
            cam_html = f'<p><strong>Camera snapshot:</strong> <code>{cam["path"]}</code> ({cam["size"]:,} bytes)</p>'
    elif cam:
        cam_html = f'<p style="color:#eab308;"><strong>Camera unavailable:</strong> {cam.get("error", "unknown")}</p>'

    # Contamination detection stub
    contamination = decision.get("contamination")
    contamination_html = ""
    if contamination:
        if contamination.get("status") == "active":
            sev_color = {"critical": "#ef4444", "warning": "#eab308", "info": "#3b82f6"}.get(contamination.get("severity"), "#3b82f6")
            contamination_html = f'''
            <div style="background:rgba(239,68,68,0.1);border:1px solid {sev_color};border-radius:12px;padding:24px;margin-bottom:20px;">
              <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#ef4444;margin-bottom:8px;">Contamination Alert</div>
              <div style="font-size:16px;font-weight:600;color:#e2e8f0;margin-bottom:4px;">{contamination.get("type", "Unknown")}</div>
              <div style="color:#94a3b8;font-size:13px;">Confidence: {contamination.get("confidence", 0):.0%} | Signature: {contamination.get("signature_id", "N/A")}</div>
            </div>'''
        else:
            contamination_html = '''
            <div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:16px 24px;margin-bottom:20px;">
              <span style="color:#64748b;font-size:13px;">Contamination detection: STANDBY (model not configured)</span>
            </div>'''

    # Override section
    override = decision.get("operator_override")
    override_html = ""
    if override:
        override_html = f'''
        <div style="background:rgba(59,130,246,0.1);border-left:3px solid #3b82f6;padding:12px 16px;border-radius:0 8px 8px 0;margin:16px 0;">
          <strong>Operator Override Active:</strong> {override.get("reason", "Manual protocol")}<br>
          <span style="color:#94a3b8;">Fan mode: <code>{override.get("mode", "unknown")}</code> | Autonomous can override: <code>{override.get("autonomous_can_override", True)}</code></span>
        </div>'''

    # Actions
    actions_html = ""
    if decision["actions"]:
        rows = ""
        for a in decision["actions"]:
            stub = " <span style='color:#eab308;'>[STUB]</span>" if a.get("stub") else ""
            rows += f'''
            <div style="display:flex;justify-content:space-between;align-items:center;padding:12px 0;border-bottom:1px solid #2d3748;">
              <span style="font-weight:600;color:#e2e8f0;">{a["actuator"]} -> <code>{a["command"]}</code>{stub}</span>
              <span style="font-size:12px;color:#94a3b8;max-width:60%;text-align:right;">{a["reason"]}</span>
            </div>'''
        actions_html = f'''
        <div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:24px;margin-bottom:20px;">
          <h2 style="font-size:16px;color:#22c55e;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px;">Actions</h2>
          {rows}
        </div>'''

    # Alerts
    alerts_html = ""
    if decision["alerts"]:
        items = ""
        for alert in decision["alerts"]:
            items += f'<li style="margin-bottom:8px;color:#f87171;font-weight:500;">{alert}</li>'
        alerts_html = f'''
        <div style="background:rgba(239,68,68,0.05);border:1px solid rgba(239,68,68,0.2);border-radius:12px;padding:24px;margin-bottom:20px;">
          <h2 style="font-size:16px;color:#ef4444;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px;">Alerts</h2>
          <ul style="padding-left:20px;">{items}</ul>
        </div>'''

    # Notes
    notes_html = ""
    if decision["notes"]:
        items = ""
        for note in decision["notes"]:
            items += f'<li style="margin-bottom:8px;color:#94a3b8;">{note}</li>'
        notes_html = f'''
        <div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:24px;margin-bottom:20px;">
          <h2 style="font-size:16px;color:#22c55e;margin-bottom:16px;text-transform:uppercase;letter-spacing:0.5px;">Notes</h2>
          <ul style="padding-left:20px;">{items}</ul>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mycodo Decision Report</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: #0f1115; color: #e2e8f0; padding: 40px 20px; max-width: 800px; margin: 0 auto; }}
  .header {{ border-bottom: 2px solid #22c55e; padding-bottom: 20px; margin-bottom: 30px; }}
  .header h1 {{ font-size: 28px; color: #22c55e; letter-spacing: -0.5px; }}
  .header .meta {{ color: #64748b; font-size: 14px; margin-top: 6px; }}
  .status-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 30px; }}
  .footer {{ margin-top: 30px; padding-top: 20px; border-top: 1px solid #2d3748; font-size: 12px; color: #475569; text-align: center; }}
</style>
</head>
<body>

<div class="header">
  <h1>Mycodo Decision Report</h1>
  <div class="meta">{phase} &middot; {timestamp}</div>
</div>

{mode_html}

<div class="status-grid">
  {card("Temperature", f"{temp:.1f}", "°C", temp_style)}
  {card("Humidity", f"{hum:.0f}", "%", hum_style)}
  {card("CO2", f"{co2:,.0f}", "ppm", co2_style)}
  <div style="background:#1a1d23;border:1px solid #2d3748;border-radius:12px;padding:20px;">
    <div style="font-size:12px;text-transform:uppercase;letter-spacing:0.5px;color:#64748b;margin-bottom:8px;">Overall</div>
    <div style="font-size:32px;font-weight:700;color:#f1f5f9;">{overall}</div>
    {pill(overall, overall_style)}
  </div>
</div>

{override_html}
{cam_html}
{contamination_html}

{actions_html}

{alerts_html}

{notes_html}

<div class="footer">
  Live fan: <code>{decision.get("fan_state", "unknown")}</code> |
  Live humidifier: <code>{decision.get("humidifier_state", "unknown")}</code> |
  Mycodo Autonomous Control
</div>

</body>
</html>'''
    return html


def main():
    parser = argparse.ArgumentParser(description="Mycodo environmental decision engine")
    parser.add_argument("--phase", default="fruiting", help="Grow phase")
    parser.add_argument("--species", default="lions_mane", help="Mushroom species (default: lions_mane). Available: see species/ directory")
    parser.add_argument("--auto-phase", action="store_true", help="Auto-detect phase transition (requires prior phase state)")
    parser.add_argument("--snapshot", default=None, help="Raw Influx CSV text")
    parser.add_argument("--fan-state", default=None, help="Known fan state (on/off/burst)")
    parser.add_argument("--humidifier-state", default=None, help="Known humidifier state (on/off)")
    parser.add_argument("--camera", action="store_true", help="Fetch camera snapshot and include in report")
    parser.add_argument("--camera-dir", default=None, help="Directory to save camera snapshot (default /tmp)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    parser.add_argument("--execute", action="store_true", help="Fire relay commands")
    parser.add_argument("--html", action="store_true", help="Generate self-contained HTML report")
    parser.add_argument("--html-dir", default="/tmp", help="Directory to save HTML report (default /tmp)")
    parser.add_argument("--contamination-check", action="store_true", help="[STUB] Enable contamination detection when model is trained")
    args = parser.parse_args()

    # --- Species & Auto-Phase System ---
    species_id = args.species.lower().replace("-", "_")
    phase_name = args.phase.lower().replace("-", "_")

    # Try species_loader first, fall back to legacy
    species_mode_active = SPECIES_MODE
    if species_mode_active:
        try:
            species_data = load_species(species_id)
            available = list_available_species()
            if species_id not in available:
                print(f"# [WARN] Species '{species_id}' not found. Available: {available}. Falling back to legacy phase_config.", file=sys.stderr)
                species_mode_active = False
        except Exception as e:
            print(f"# [WARN] species_loader error: {e}. Falling back to legacy phase_config.", file=sys.stderr)
            species_mode_active = False

    # Auto-phase detection
    if args.auto_phase and species_mode_active:
        try:
            from transition_detector import check_auto_transition, load_phase_state
            metrics = {}  # Will be populated after sensor fetch
            state = load_phase_state()
            if state.get("current_species") == species_id:
                transition_result = check_auto_transition(metrics, species_id, phase_name)
                if transition_result["transition_ready"]:
                    phase_name = transition_result["recommended_phase"]
                    print(f"# [AUTO-PHASE] Transitioning to {phase_name} (confidence: {transition_result['confidence']:.0%})", file=sys.stderr)
                else:
                    print(f"# [AUTO-PHASE] Staying in {phase_name} — {transition_result['reason']}", file=sys.stderr)
            else:
                print(f"# [AUTO-PHASE] Initiating tracking for {species_id} -> {phase_name}", file=sys.stderr)
                from transition_detector import init_phase
                init_phase(species_id, phase_name)
        except Exception as e:
            print(f"# [WARN] Auto-phase failed: {e}. Using explicit --phase.", file=sys.stderr)

    # Canonical aliases (legacy compatibility)
    CANONICAL_ALIASES = {
        "second_flush": "fruiting",
        "second_flush_fruiting": "fruiting",
        "pinning": "primordia",
        "pins": "primordia",
        "late_stage_fruiting": "late-stage-fruiting",
        "colonisation": "colonization",
    }
    if phase_name in CANONICAL_ALIASES:
        phase_name = CANONICAL_ALIASES[phase_name]

    # --- Auto-query fan status and operator override ---
    fan_status = None
    override = None
    try:
        if args.fan_state:
            fan_status = {"state": args.fan_state, "source": "cli-arg"}
        else:
            fan_status = fetch_fan_status()
    except Exception as e:
        fan_status = {"state": "unknown", "error": str(e), "source": "exception"}

    humidifier_status = None
    try:
        if args.humidifier_state:
            humidifier_status = {"state": args.humidifier_state, "source": "cli-arg"}
        else:
            humidifier_status = fetch_humidifier_status()
    except Exception as e:
        humidifier_status = {"state": "unknown", "error": str(e), "source": "exception"}

    try:
        override = load_override()
    except Exception:
        override = None

    # --- Optional camera fetch ---
    camera_info = None
    if args.camera:
        cam_dir = Path(args.camera_dir) if args.camera_dir else None
        camera_info = fetch_camera(cam_dir)

    try:
        csv_text = args.snapshot if args.snapshot else fetch_snapshot()
        parsed = parse_influx_csv(csv_text)
        decision = build_decision(parsed, phase_name, fan_status=fan_status, humidifier_status=humidifier_status, override=override, mode="execute" if args.execute else "dry-run", camera=camera_info, species_id=species_id)
    except RuntimeError as e:
        decision = {"status": "error", "error": str(e), "raw_parsed": {}, "fan_state": fan_status.get("state", "unknown") if fan_status else "unknown"}
    except Exception as e:
        decision = {"status": "error", "error": f"mycodo-decision internal error: {e}", "raw_parsed": {}, "fan_state": fan_status.get("state", "unknown") if fan_status else "unknown"}

    if args.execute:
        import time
        followup_file = Path.home() / ".mycodo-skill-followup"
        prev_file = Path.home() / ".mycodo-skill-prev-readings.json"
        followup_needed = False
        action_for_followup = {}

        for a in decision.get("actions", []):
            if a.get("stub"):
                print(f"# [STUB] Would execute: {a['actuator']} {a['command']}")
                continue
            script = scripts_dir / "sensor-query.sh"
            cmd = ["bash", str(script)]
            if a["actuator"] == "fan" and a["command"].startswith("burst_"):
                subprocess.run(cmd + ["fan_burst", a["command"].split("_")[1]])
                action_for_followup = a
                followup_needed = True
            elif a["actuator"] == "fan" and a["command"] == "on":
                subprocess.run(cmd + ["fan_on"])
                action_for_followup = a
                followup_needed = True
            elif a["actuator"] == "humidifier" and a["command"] == "on":
                subprocess.run(cmd + ["humidifier_on"])
                action_for_followup = a
                followup_needed = True
            elif a["actuator"] == "humidifier" and a["command"] == "off":
                subprocess.run(cmd + ["humidifier_off"])
                action_for_followup = a
                followup_needed = True
            elif a["actuator"] == "humidifier" and a["command"].startswith("burst_"):
                subprocess.run(cmd + ["humidifier_burst", a["command"].split("_")[1]])
                action_for_followup = a
                followup_needed = True

        if followup_needed:
            with open(prev_file, "w") as f:
                json.dump(decision["metrics"], f)
            with open(followup_file, "w") as f:
                json.dump({
                    "fired_at": time.time(),
                    "wait_seconds": 600,
                    "action": action_for_followup,
                    "prev_file": str(prev_file),
                }, f, indent=2)
            print(f"\n[followup] Flag set — next check in {10}m, action={action_for_followup['actuator']}:{action_for_followup['command']}")

    if args.json:
        print(json.dumps(decision, indent=2, default=str))
    else:
        print(format_report(decision))

    # --- HTML output ---
    if args.html:
        from datetime import datetime, timezone
        import zoneinfo
        _tz_name = os.environ.get("MYCODO_SKILL_TZ", "America/New_York")
        local_tz = zoneinfo.ZoneInfo(_tz_name)
        now_local = datetime.now(local_tz)
        ts = now_local.strftime("%Y%m%d_%H%M%S")
        decision["timestamp"] = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        html_path = Path(args.html_dir) / f"mycodo_report_{ts}.html"
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_content = format_html(decision)
        html_path.write_text(html_content, encoding="utf-8")
        print(f"\n[html] Report saved to: {html_path}")

        # Save raw camera JPG alongside HTML (for training / archival)
        cam = decision.get("camera")
        if cam and cam.get("ok") and cam.get("path"):
            jpg_src = Path(cam["path"])
            if jpg_src.exists():
                import shutil
                jpg_path = Path(args.html_dir) / f"mycodo_report_{ts}.jpg"
                shutil.copy(str(jpg_src), str(jpg_path))
                print(f"[img] Raw image saved to: {jpg_path}")


if __name__ == "__main__":
    main()
