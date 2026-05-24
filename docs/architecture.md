# Mycodo Hermes Skill Architecture

This document describes the decision pipeline, control layers, reporting system, and integration points that make up the Mycodo Hermes Skill autonomous mushroom grow environment controller.

---

## Decision Pipeline (10-Stage Cycle)

Every 30 minutes, the decision engine (`mycodo-decision.py`) executes a 10-stage cycle:

1. **Fetch sensor snapshot** -- live readings from SHT45 (temperature, humidity) and SCD41 (CO2) via `sensor-query.sh snapshot`
2. **Detect or accept phase** -- auto-detect from sensor signatures or accept explicit `--phase` argument
3. **Load species config** -- YAML-based thresholds for the active species (default: Lion's Mane)
4. **Classify metrics vs thresholds** -- each metric assessed as `ideal`, `acceptable`, `alert`, or `unmonitored`
5. **Query actuator state** -- read current fan and humidifier relay positions via `sensor-query.sh fan_status` / `humidifier_status`
6. **Read operator override** -- check `~/.mycodo-skill-override.json` for active protocols or suppressed actuators
7. **Evaluate decision rules** -- phase rules, safety gates, oversaturation guard, co-fire logic
8. **Generate and execute actions** -- relay commands fired when `--execute` is passed
9. **Write follow-up flag** -- if actions were fired, create `~/.mycodo-skill-followup` for verification
10. **Generate report** -- text summary, optional HTML with embedded camera, optional JSON output

---

## Adaptive Follow-Up System (2-Tier Architecture)

The system uses two tiers to balance decision quality against token cost:

| Tier | Script | Interval | Cost | Purpose |
|------|--------|----------|------|---------|
| **Decision engine** | `mycodo-decision.py` | 30 min | LLM tokens | Reasoned environmental assessment, generates actions |
| **Follow-up checker** | `mycodo-followup-check.py` | 10 min | Zero tokens | Verifies the last action produced expected change |

### How follow-up works

1. Decision engine fires an action and writes `~/.mycodo-skill-followup` (JSON with action type, start time, expected outcome)
2. Every 10 minutes, `mycodo-followup-wrapper.sh` runs as a no-agent cron job
3. If the flag exists and 10+ minutes have passed, the wrapper re-reads sensors
4. It compares current readings against pre-action baseline stored in `~/.mycodo-skill-prev-readings.json`
5. Expected outcomes are verified:
   - `humidifier:on` -- humidity should have **risen**
   - `humidifier:off` -- humidity should have **dropped**
   - `fan:burst` -- CO2 should have **dropped**
6. On match: flag cleared, silent success
7. On mismatch: non-zero exit triggers operator alert

### Token economics

The follow-up checker saves approximately 144 LLM calls per day by handling verification in pure Python. Total daily budget is roughly 53 LLM calls (48 decision engine + 5 scheduled checks) plus 144 zero-cost follow-up runs.

### Edge cases

- **Flag but no baseline file:** Checker notes "no baseline" and exits gracefully
- **Pi offline during follow-up:** `sensor-query.sh` fails, non-zero exit triggers alert
- **Operator takes manual control:** `override.json` set to `autonomous_can_control: false` suppresses future actions; existing follow-up still runs independently
- **Multiple simultaneous actions:** Only the last action gets follow-up (simplifies logic)

---

## Operator Override Model (3-Layer)

Every decision requires three inputs:

| Layer | Source | Question Answered | Query Method |
|-------|--------|-------------------|--------------|
| **1. Sensor state** | InfluxDB (SHT45, SCD41) | What is the environment doing? | `sensor-query.sh snapshot` |
| **2. Operator intent** | `~/.mycodo-skill-override.json` | What protocol did the operator establish? | File read on every run |
| **3. Actuator state** | Mycodo GPIO API | Is the fan actually on or off right now? | `sensor-query.sh fan_status` |

### Decision hierarchy (evaluated in order, stops at first match)

```
1. EXPLICIT OPERATOR DIRECTIVE
   -- Real-time spoken/written instruction (highest authority)
   -- Immediately persisted to override file

2. ACTIVE OPERATING PROTOCOL
   -- From ~/.mycodo-skill-override.json
   -- Overrules generic phase rules but NOT direct operator commands

3. PHASE RULES
   -- Species-specific YAML thresholds for the current grow phase
   -- Default when no override is active

4. GENERIC SAFETY RULES
   -- Always-active thresholds (e.g., CO2 > 2000 ppm)
   -- Never disabled, even during override
```

### Override JSON schema (v1.0)

```json
{
  "schema_version": "1.0",
  "updated_at": "ISO-8601-timestamp",
  "established_by": "the operator or agent name",
  "active_protocol": {
    "name": "kebab-case-identifier",
    "label": "Human-readable label",
    "description": "Full sentence describing what the operator does",
    "status": "active | suspended | deprecated",
    "phase_context": "colonization | primordia | fruiting | late-stage-fruiting | rest"
  },
  "overrides": {
    "fan": {
      "mode": "off | burst | continuous",
      "should_be_on": true,
      "reason": "Why the operator established this",
      "authority": "operator | agent",
      "autonomous_can_override": true
    },
    "humidifier": {
      "mode": "off | on | manual-level-N | auto",
      "reason": "Why manual vs auto",
      "operator_control": true,
      "autonomous_can_control": true
    }
  },
  "safety_gates": {
    "always_vent_if_co2_ppm_above": 2000,
    "always_alert_if_temp_c_above": 28,
    "always_alert_if_temp_c_below": 10
  }
}
```

Key fields:
- `autonomous_can_override: false` -- engine NEVER turns fan OFF; safety alerts still fire but warn rather than act
- `autonomous_can_control: false` -- engine NEVER emits humidifier commands
- Missing override file -- falls back to standard phase rules (graceful degradation)

### Graceful degradation

If any layer is missing, the engine falls back:
- Missing override file -- assumes no operator protocol, uses phase rules
- Fan status query fails -- logs `fan_state: unknown`, proceeds with caution
- Missing sensors -- errors out (sensors are required)

---

## HTML Reporting and Telegram Delivery

### Report generation

When `--html --html-dir <dir>` is passed, the decision engine produces a self-contained HTML report with:

- **Sensor grid:** Temperature, humidity, CO2 cards with colored status pills (optimal/warning/alert)
- **Camera snapshot:** Base64-embedded JPEG (requires `--camera` flag)
- **Operator override banner:** Shown when an active protocol exists
- **Actions taken:** With rationale for each relay command
- **Contamination detection:** STANDBY badge (stub for future vision model)
- **Alerts and notes**

Dark theme (`#0f1115` background, `#22c55e` accent), max-width 800px, mobile-friendly.

### Files produced per run

| File | Size | Purpose |
|------|------|---------|
| `mycodo_report_YYYYMMDD_HHMMSS.html` | ~1.1 MB | Self-contained report with embedded image |
| `mycodo_report_YYYYMMDD_HHMMSS.jpg` | ~845 KB | Raw JPEG for contamination model training |

### Telegram delivery pipeline

1. Generate HTML report
2. Screenshot via Firefox headless: `firefox --headless --screenshot /tmp/mycodo_screenshot.png file:///path/to/report.html`
3. Deliver screenshot image + optional HTML attachment to Telegram

The screenshot is a delivery convenience (Telegram renders it inline). It does NOT need archival -- the HTML and JPG are the archival artifacts.

### Timezone discipline

All user-facing timestamps MUST use local time (configurable via `MYCODO_SKILL_TZ`). Internal timestamps (InfluxDB, epoch, file modification times) remain UTC.

```python
import zoneinfo
local_tz = zoneinfo.ZoneInfo("your configured timezone")
now_local = datetime.now(local_tz)
ts = now_local.strftime("%Y%m%d_%H%M%S")
```

---

## Phase Auto-Transition System

The `transition_detector.py` module provides confidence-scored auto-transition between grow phases. It only **recommends** transitions -- it does not execute them unilaterally.

### State file

`~/.mycodo-skill-phase-state.json` is the single source of truth for current grow state:

```json
{
  "current_species": "lions_mane",
  "current_phase": "fruiting",
  "phase_start_time": "2026-05-24T18:28:10.909180+00:00",
  "phase_history": [],
  "operator_locked": false
}
```

### Confidence scoring

Auto-transition requires 70% or higher confidence:

| Component | Weight | Calculation |
|-----------|--------|-------------|
| Time threshold | 50% | 70% of estimated phase duration elapsed |
| Sensor match | 30% | At least 2/3 metrics in acceptable range for next phase |
| Contamination | 20% | Always clear until model is trained |

### Manual vs auto transitions

**Always manual** (physical action required):
- Colonization to primordia (bag-cutting)
- Late-stage to rest (harvest)
- Rest to colonization (new blocks/inoculation)

**Auto when species config allows:**
- Primordia to fruiting (time + sensor-based)
- Fruiting to late-stage (primarily time-based)

Each species YAML includes `transition_trigger: "auto" | "manual"` per phase.

---

## Actuator Interaction Effects

### Fan + humidifier co-fire problem

When the exhaust fan runs while the humidifier is OFF, humidity drops extremely fast. Measured data shows a drop of 18.5% RH in approximately 2 minutes during a fan burst.

Key implications:
- **`fan_burst` (timed) is strongly preferred** over `fan_on` (sustained) when humidity retention matters
- Recovery time after a fan burst must be measured empirically before tightening thresholds
- Prefer staggered commands: fan burst, then wait for follow-up, then humidifier only if needed
- Avoid `fan_on` + `humidifier_off` simultaneously -- this is the fastest deflation path

### Co-fire mandate

When the humidifier turns ON (humidity below `accept_min`), simultaneously fire `fan burst_120` if the fan is not already running. This prevents the unmonitored humidity climb that caused the oversaturation incidents.

### Recovery rate

The ultrasonic humidifier can recover approximately 4.5% RH per minute, which outpaces continuous fan exhaust. However, simultaneous ON state of both actuators is energy-wasteful. Staggered duty cycles are preferred.

---

## Sensor Phase Signatures

CO2 is the most diagnostic metabolic signal for cultivation phase detection:

| Phase | Temperature | Humidity | CO2 Pattern |
|-------|-------------|----------|-------------|
| Setup | ~24C ambient | 28-50% ambient | 668-974 ppm (ambient) |
| Colonization | 18-23C | 85-95% | **RISING** 1000 to 2934 ppm |
| Primordia | 18-21C | 90-95% | **VOLATILE** 800-1500, wide spread |
| Fruiting | 17-19C | 85-100% | **LOW and STABLE** 450-900 ppm |
| Post-harvest | Ambient | **CRASH** below 60% | Ambient / low |

### Automated phase classification (v2)

Implemented as `scripts/phase_detector.py`:

```
Primary classifier (CO2):
  CO2 > 1500 ppm              -> colonization   (confidence: 0.70+)
  800 <= CO2 <= 1500 ppm      -> primordia       (confidence: 0.60)
  CO2 < 800 ppm               -> fruiting        (confidence: 0.75)
  CO2 < 500 ppm + temp > 20C  -> post-harvest    (confidence: 0.55)

Confidence modifiers:
  Fruiting:  +0.15 if humidity is 85-100%
  Primordia: +0.15 if humidity > 90% and temp is 15-20C
  Fruiting:  -0.15 if humidity < 70% (triggers alert)
```

### Phase-aware alert thresholds

Environmental thresholds are phase-dependent. A humidity of 82% triggers an alert during fruiting (below 85% floor) but NOT during colonization.

| Phase | Humidity Alert | CO2 Alert | Temp Alert |
|-------|---------------|-----------|------------|
| Colonization | None (80% floor) | Only if > 8000 ppm (anaerobic) | None |
| Primordia | < 85% | > 1200 ppm AND humidity < 85% | < 13C or > 20C |
| Fruiting | < 85% flag; < 70% urgent | > 800 ppm | < 15C or > 21C |
| Post-harvest | None | None | None |

---

## Contamination Detection (Future Integration Point)

**Status:** STUB -- fully dormant, zero noise. All plumbing is in place for future activation.

When `--camera` is passed to `mycodo-decision.py`:
1. Camera image is fetched and base64-embedded in HTML
2. Decision output includes a `contamination` dict
3. HTML shows: "Contamination detection: STANDBY (model not configured)"
4. No alerts fire, no false positives

### Activation path

1. Write model config at `~/.mycodo-skill-contamination-model.json` with `"active": true`, model path, confidence threshold, and signature map
2. Add `--contamination-check` to the cron command
3. Replace the stub `pass` block in the decision engine with actual model inference

The stub produces three states: `stub` (no config), `inactive` (config exists but disabled), `active` (model detected something).

Training data accumulates automatically: every HTML report saves a raw `.jpg` with a matching timestamp. Reddit scraping from the contamination monitoring pipeline adds reference examples.

---

## Oversaturation Guard

A safety mechanism that runs BEFORE standard humidity logic in the decision engine:

```
if humidity >= 95% AND humidifier_state == "on":
    -> force humidifier OFF
    -> fire fan burst
    -> emit OVERSATURATION ALERT
    -> skip standard humidifier logic this cycle
```

This guard exists because exposed blocks in second flush can climb 20-30% humidity in 10-15 minutes. The 30-minute decision cycle is too slow for these events -- the follow-up checker (10-minute) is the fast safety net.

### Two-layer safety architecture

| Layer | Trigger | Frequency |
|-------|---------|-----------|
| Decision engine guard | humidity >= 95% AND humidifier ON | Every 30 min |
| Follow-up velocity warning | Humidity rose >25-30% since last action | Every 10 min |

---

## Grow Cycle Archival

After blocks are harvested and the tent is reset:

```bash
bash scripts/archive-grow-cycle.sh <cycle-name>
```

This packages all HTML reports and raw JPGs from the cycle into an archive directory. At approximately 1.8 GB per 45-day cycle, storage is not a pressure point on typical setups.

---

## Design Principles

1. **Actuator awareness is a prerequisite for autonomy.** You cannot automate what you cannot observe.
2. **Operator intent is a first-class input, not an afterthought.** The engine must know WHY the fan is running.
3. **Safety gates are always active.** Overrides control normal operation; safety gates control edge cases.
4. **Machine + human readable.** JSON for the engine, markdown for the human. Both must exist and be accurate.
5. **Graceful degradation.** If the override file is missing or corrupt, the system falls back to phase rules. It never crashes.
6. **Follow-up is free.** The adaptive follow-up system validates actuator actions at zero token cost.
