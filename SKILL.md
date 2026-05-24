---
name: mycodo-autonomous-control
description: Autonomous mushroom cultivation via Mycodo sensors and relays.
version: 0.1.0
author: Setasoma
license: MIT
---

# mycodo-autonomous-control

Autonomous environmental control for mushroom cultivation on a Raspberry Pi.
A phase-aware decision engine reads temperature, humidity, and CO2 sensors via
Mycodo and InfluxDB, evaluates readings against species-specific thresholds
defined in YAML configs, and fires fan and humidifier relays to maintain
optimal growing conditions. Safety guards prevent oversaturation, a follow-up
checker verifies actuator effects, and operator overrides allow manual
intervention at any time.

## When to Use

- Automate environmental control for a mushroom grow tent or fruiting chamber
- Run scheduled sensor checks with relay-based fan and humidifier actuation
- Troubleshoot decision engine behavior, relay firing, or dry-run issues
- Tune species-specific thresholds or add support for new species
- Transition between grow phases (colonization, primordia, fruiting, rest)
- Review HTML status reports with embedded camera snapshots

## Prerequisites

- **Raspberry Pi** running [Mycodo](https://github.com/kizniche/Mycodo) with InfluxDB 2.x
- **SHT45 sensor** for temperature and humidity (primary, +/-0.1C, +/-1% RH)
- **SCD41 sensor** for CO2 (primary, ppm)
- **Relay-controlled fan** (FAE exhaust) and **relay-controlled humidifier** (e.g., DLI IoT Power Relay on GPIO)
- **Python 3.9+** with PyYAML installed
- **Credential file** at `~/.mycodo/sensor-creds.env` containing Mycodo API key, InfluxDB token, and Pi host address. See `docs/templates/sensor-creds.env.example` for the required format.
- **Hermes agent framework** with cron scheduling capability (for automated 30-minute and 10-minute cycles)

## How to Run

Use the `terminal` tool to execute commands on the Raspberry Pi.

```bash
# Standard decision run with HTML report and camera snapshot
python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting --execute --camera --html

# Auto-detect phase from sensor trends and state file
python3 mycodo_skill/decision_engine.py --species lions_mane --auto-phase --execute --camera --html

# Dry-run (default) — evaluates conditions, prints report, fires NO relays
python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting
```

### Cron Setup

Two cron jobs provide the autonomous control loop:

| Job | Interval | Purpose | LLM Cost |
|-----|----------|---------|----------|
| Decision engine | Every 30 min | Sensor query, threshold evaluation, relay actuation, HTML report | Standard |
| Follow-up checker | Every 10 min | Verifies actuator effects (humidity rising/falling as expected) | Zero |

The follow-up checker (`mycodo_skill/followup_checker.py`) runs as a lightweight Python script with no LLM calls. It reads a flag file left by the decision engine and exits silently when no follow-up is needed.

## Quick Reference

| File | Purpose |
|------|---------|
| `mycodo_skill/decision_engine.py` | Core decision engine with phase-aware relay logic |
| `mycodo_skill/followup_checker.py` | 10-minute verification checker (zero LLM cost) |
| `mycodo_skill/species_loader.py` | Loads species YAML configs and classifies sensor readings |
| `mycodo_skill/phase_detector.py` | Classifies grow phase from live sensor data |
| `mycodo_skill/transition_detector.py` | Confidence-scored auto-transition between phases |
| `mycodo_skill/phase_config.py` | Legacy phase thresholds (fallback) |
| `mycodo_skill/verify_actuator.py` | Actuator state verification utility |
| `scripts/sensor-query.sh` | Sensor reads, fan/humidifier relay commands, camera |
| `scripts/mycodo-followup-wrapper.sh` | Cron wrapper for the follow-up checker |
| `scripts/archive-grow-cycle.sh` | Archive completed grow cycle data |
| `species/*.yaml` | Species-specific threshold configs |
| `~/.mycodo/sensor-creds.env` | Credentials (not in repo) |
| `~/.mycodo-skill-override.json` | Operator override state (not in repo) |

### Supported Species

Lion's Mane, Oyster, Shiitake, Reishi, Turkey Tail, Maitake. Each has a
YAML config under `species/` defining thresholds per phase. To add a new
species, copy an existing YAML and adjust values. See `species/README.md`.

### Grow Phases

| Phase | Fan | Humidifier | Use Case |
|-------|-----|------------|----------|
| `colonization` | Off | Off | Spawn run, no FAE needed |
| `primordia` | Off | Threshold-based | Pin formation, minimal airflow |
| `fruiting` | Burst on CO2 trigger | Threshold-based | Standard fruiting |
| `late-stage-fruiting` | Continuous | Pulse ON/OFF | Exposed blocks, high CO2 sensitivity |
| `rest` | As needed | Off | Between flushes |
| `inactive` | Off | Off | Empty tent, no grow in progress |

### Sensor Commands

```bash
bash scripts/sensor-query.sh quick          # Temp + humidity + CO2 as JSON
bash scripts/sensor-query.sh snapshot       # All sensor channels (CSV)
bash scripts/sensor-query.sh fan_on         # Fan relay ON
bash scripts/sensor-query.sh fan_off        # Fan relay OFF
bash scripts/sensor-query.sh fan_burst 360  # Timed fan burst (seconds)
bash scripts/sensor-query.sh humidifier_on  # Humidifier relay ON
bash scripts/sensor-query.sh humidifier_off # Humidifier relay OFF
bash scripts/sensor-query.sh humidifier_burst 60  # Timed humidifier burst
bash scripts/sensor-query.sh camera /tmp/latest.jpg  # Download camera snapshot
```

## Procedure

### 1. Query Sensors

Run `scripts/sensor-query.sh quick` to fetch current temperature, humidity,
and CO2 as JSON. The script sources credentials from `~/.mycodo/sensor-creds.env`
at runtime. Credentials are never exposed to the agent context.

### 2. Evaluate Conditions

The decision engine (`mycodo_skill/decision_engine.py`) loads the species YAML
config, classifies each metric as ideal/acceptable/alert against the
current phase thresholds, and determines relay actions.

### 3. Fire Relays (Execute Mode Only)

With `--execute`, the engine sends relay commands via `scripts/sensor-query.sh`.
Without `--execute`, the engine prints a report with a DRY RUN banner and
touches no relays.

### 4. Safety Guards

| Guard | Trigger | Action |
|-------|---------|--------|
| Oversaturation | Humidity >= 98% + humidifier ON | Force humidifier OFF + fan burst |
| Co-fire | Humidifier turns ON | Simultaneous fan burst (120s) to prevent moisture buildup |
| Operator override | `~/.mycodo-skill-override.json` present | Suppress fan/humidifier per override config |
| Follow-up verification | Any relay fired | Flag file triggers 10-min checker |

### 5. Generate Report

With `--html`, the engine produces a self-contained HTML report with inline
CSS. With `--camera`, it embeds a base64-encoded camera snapshot in the report
and saves a raw `.jpg` alongside for archival.

### 6. Follow-up Verification

After any relay action, the engine writes a flag file at
`$HOME/.mycodo-skill-followup`. The 10-minute cron job reads this flag and
verifies the expected environmental change occurred (e.g., humidity rising
after humidifier ON). If no improvement is detected, it exits with a non-zero
code to trigger an alert. If no flag exists, it exits silently.

### 7. Phase Auto-Transition (Optional)

Use `--auto-phase` to enable confidence-scored phase detection via
`mycodo_skill/transition_detector.py`. The detector scores transitions on
time-in-phase (50%), sensor pattern match (30%), and contamination clear
(20%), with a 70% confidence threshold. Physical steps (bag cutting, harvest)
require manual transition. Initialize before first use:

```bash
python3 mycodo_skill/transition_detector.py --init lions_mane colonization
```

### 8. Contamination Monitoring (Optional)

The `--contamination-check` flag is parsed but currently dormant (no model
configured). When a model is available, it will analyze camera snapshots
against a pattern database sourced from Reddit community reports. The HTML
report shows a STANDBY badge until activation.

## Pitfalls

1. **Dry-run ghost actions.** Without `--execute`, the engine prints reports
   but fires NO relays. The cron job MUST include `--execute`. Verify the
   report shows "EXECUTION MODE", not "DRY RUN". This failure mode ran
   undetected for multiple days in production.

2. **Follow-up flag path mismatch.** The decision engine and the follow-up
   checker MUST use the same flag path (`$HOME/.mycodo-skill-followup`).
   A mismatch (e.g., `/tmp/` vs `$HOME/`) causes the checker to silently
   no-op, leaving actuator effects unverified. In production, this led to
   humidity climbing from 68% to 99.91% unchecked.

3. **Oversaturation from burst fan + continuous humidifier.** The humidifier
   adds moisture faster than a fan burst can remove it. A co-fire pattern is
   required: whenever the humidifier turns ON, fire a simultaneous 120-second
   fan burst to prevent runaway humidity.

4. **Null threshold crashes in inactive phase.** Species YAML configs with
   `null` threshold values (used for the `inactive` phase) cause `TypeError`
   on comparisons like `value < None`. All threshold comparisons must use
   `is not None` guards. The `assess()` function returns "unmonitored" when
   all thresholds are null.

5. **Credential file exists but is empty.** After migrations or rotations,
   `sensor-creds.env` may be 0 bytes. The script checks `[ -f ]` (file
   exists) but not `[ -s ]` (file is non-empty). An empty file silently
   sources no variables, producing cryptic auth failures. Always verify
   with `ls -l`.

6. **`--camera` and `--execute` flags dropped when editing cron prompts.**
   Refactoring a cron prompt to add `--species` or `--auto-phase` can
   accidentally remove existing flags. This produces dry-run ghosts (no
   relay firing) and missing camera images simultaneously. Diff old vs new
   prompt before saving.

7. **Timestamp estimation from stale context.** After agent context
   compaction, session timestamps become stale. Never estimate the current
   time from cached references. Always query `date` before reporting when
   an action occurred.

## Verification

```bash
# Dry-run test (no relays fired, should show DRY RUN banner)
python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting
# Expected: report with sensor readings and "DRY RUN" banner

# Sensor connectivity test
bash scripts/sensor-query.sh quick
# Expected: JSON with temp, humidity, CO2 values

# Follow-up checker (should exit silently when no flag exists)
python3 mycodo_skill/followup_checker.py
# Expected: no output, exit code 0

# Credential file health check
ls -l ~/.mycodo/sensor-creds.env
# Expected: non-zero file size

# Species config validation
python3 -c "from mycodo_skill.species_loader import load_species; print(load_species('lions_mane')['common_name'])"
# Expected: "Lion's Mane"
```
