# Oversaturation Incident -- 2026-05-23

## Summary

Two oversaturation events on the same day exposed layered failures in the decision engine's humidity control. Peak humidity reached 99.4% in the first event and effectively 100% in the second.

---

## Event 1: Afternoon (15:32 - 15:54)

### Timeline

| Time | Event | Humidity |
|------|-------|----------|
| 15:32 | Humidifier OFF, fan burst 360s fired (CO2 control) | 98.6% |
| 15:34 | Humidifier turned ON (recovery after fan-driven drop) | 80.1% |
| 15:38 | Follow-up check | 97.9% |
| ~15:54 | Operator notices visible saturation | ~100% |

### Root causes (layered)

**Layer 1: Dry-run cron.** The cron prompt had `--execute` missing from inception. Every prior run reported "Action Taken" with zero relay firings. This was discovered and fixed during this incident.

**Layer 2: Threshold math.** `phase_config.py` fruiting phase used `accept_max: 95` with a deadband of `+3`, meaning humidifier OFF only triggered at greater than 98%. This allowed unchecked rise from 95% to 98% over multiple cycles.

**Layer 3: Burst exhausted.** The fan burst (360s) ended. Humidifier remained ON. Humidity climbed from 97.9% to 99.4% in approximately 10 minutes with no fan running.

**Layer 4: Physics mismatch.** A 360-second fan burst cannot remove moisture as fast as the continuous humidifier adds it (approximately 1% RH per minute net gain). The architecture assumed periodic venting could offset continuous humidification.

---

## Event 2: Follow-up failure (17:15 - 17:25)

| Time | Event | Humidity |
|------|-------|----------|
| 17:15 | Decision engine fires `fan burst_360` + reports `humidifier ON` | 97.9% |
| 17:25 | Operator reports visible saturation | 99.4% |

The follow-up checker's 10-minute interval ran but registered "success" because it validated direction (humidity rising when humidifier ON), not magnitude. A runaway from 95% to 99% still passed as "humidity rising as expected."

---

## Fixes Applied

1. **Dry-run fix:** Added mode banner ("DRY RUN -- NOT EXECUTING RELAYS" vs "EXECUTION MODE -- relay commands fired") and appended `--execute` to cron prompt.

2. **Threshold reduction:** `accept_max` lowered from 95% to 93%. Removed `+3` deadband. Humidifier OFF now triggers above 93%.

3. **Oversaturation guard:** Lowered trigger from >= 98% to >= 95% with humidifier ON. Forces humidifier OFF plus fan burst.

4. **Co-fire mandate:** When humidifier turns ON (humidity below 85%), simultaneously fire `fan burst_120` if fan is not already running.

5. **Follow-up guard alignment:** Cross-run ceiling lowered from 95% to 93%.

---

## Critical Insight

The follow-up checker is NOT a ceiling -- it is a divergence detector. It catches "humidifier ON but humidity still dropping" (actuator failure), not "humidifier ON and humidity climbing too fast" (overshoot). The oversaturation guard in the decision engine is the ceiling.

---

## Emergency Response Protocol

If visible saturation is reported and autonomy has not corrected it within 2 minutes:

```bash
sensor-query.sh humidifier_off
sensor-query.sh fan_burst 360
```

Check `~/.mycodo-skill-override.json` -- if `autonomous_can_control` is false, the engine cannot have corrected it.

---

## Context: Second Flush Exposed Blocks

This guard exists because of the physics of second flush with exposed blocks:
- Exposed surface area generates high CO2 (800-1000+ ppm vs normal 600)
- Fan must run almost continuously to keep CO2 in range
- Humidifier must run to compensate for fan-driven drying
- This creates a fundamental conflict: CO2 control needs airflow, humidity control needs no airflow
- Result: the system can reach 100% humidity if humidifier runs without fan for even 15 minutes

During normal fruiting with fresh bags, the 30-minute interval is safe because metabolic output is moderate.
