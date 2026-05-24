# Mycodo Hermes Skill Pitfall Guide

Hard-won lessons from building and operating the Mycodo Hermes Skill autonomous grow environment controller. Every entry here represents a real failure that cost time, caused oversaturation events, or produced misleading data. Organized by category for quick reference.

---

## Cron Pitfalls

### P-01: Dry-Run Mode Running for Days Unnoticed

**What happened:** The decision engine cron job ran for approximately 7 days without the `--execute` flag. Reports showed "Action Taken: fan burst_360" and "humidifier off" but no relays ever fired. The operator discovered this during an active oversaturation event when the fan failed to respond.

**Root cause:** `mycodo-decision.py` defaults to dry-run mode unless `--execute` is explicitly passed. The reports gave no visual indication that actions were not being executed.

**Fix:**
- Added `--execute` to the cron prompt
- Added a mode banner to every report: "DRY RUN -- NOT EXECUTING RELAYS" or "EXECUTION MODE -- relay commands fired"
- Added a `mode` field to decision JSON for programmatic verification

**Prevention:** Any cron or automation invoking `mycodo-decision.py` MUST include `--execute`. Any report saying "Action Taken" without an execution-mode banner is suspect. Verify with `sensor-query.sh <actuator>_status` after every claimed action.

---

### P-02: Cron Environment Path Resolution

**What happened:** A cron job output said a file "does not exist" but the same command worked perfectly when run interactively.

**Root cause:** Hermes cron jobs run in isolated sessions with a modified `$HOME`. The path `~` expands to a different directory than the operator's home. Files at `$HOME/workspace/` may not be visible at the cron session's effective path.

**Fix:** Use absolute paths or `~/.mycodo-skill-override.json` for files the automation needs. Never use relative paths like `workspace/knowledge/...` in cron prompts. Keep the machine-readable data source (`~/.mycodo-skill-override.json`) as the primary input.

**Detection:**
```bash
hermes cron log <example-cron-id> | grep -i "not exist\|no such file\|path\|does not"
```

---

### P-03: Cron Flag Regression When Editing Prompts

**What happened:** When adding `--species lions_mane --auto-phase` to the cron prompt, the existing `--camera` and `--execute` flags were accidentally dropped. The next run produced a text-only HTML report in dry-run mode -- no image, no relay commands.

**Root cause:** The entire command block was replaced instead of appending new flags.

**Prevention checklist after any cron prompt edit:**
1. Old flags still present? (`--camera`, `--execute`, `--html`, `--html-dir`)
2. New flags correctly placed? (`--species`, `--auto-phase`)
3. Missing flag impact assessed? (Dropping `--camera` = no image; dropping `--execute` = dry-run)

Always diff the old and new command strings side-by-side before deploying.

---

### P-04: Cron Audit Before Answering Configuration Questions

**What happened:** The operator asked about HTML integration for tent reports. The agent responded by asking "which cron job should get this treatment" -- despite having pulled a test report from the decision engine earlier in the same session.

**Root cause:** Agent relied on memory recall instead of auditing the live cron list.

**Prevention:** Before answering ANY tent-configuration question:
1. Run `cronjob action=list`
2. Filter for tent-related jobs
3. Read the specific job prompt if needed
4. Answer from live data, never from memory alone

---

## Safety Pitfalls

### P-05: Follow-Up Flag Path Mismatch

**What happened:** The tent hit 99.91% humidity because the follow-up wrapper script and the decision engine used different file paths for the follow-up flag.

| Component | Flag Path |
|-----------|-----------|
| `mycodo-decision.py` | `~/.mycodo-skill-followup` |
| `mycodo-followup-wrapper.sh` | `/tmp/mycodo-skill-followup` (WRONG) |

The wrapper checked `/tmp/...` but the engine wrote `~/.mycodo-skill-followup`. The wrapper always found no flag, exited silently, and the follow-up checker was never invoked.

**Root cause:** The two components were developed at different times and nobody verified that the paths matched. The wrapper's silent no-op behavior on "no flag found" masked the failure completely.

**Fix:** Patch wrapper to use `FLAG="$HOME/.mycodo-skill-followup"`. `/tmp` is unreliable (cleared on reboot, session-isolated on some systems). `$HOME` is persistent and tied to the operator's profile.

**Prevention:** When a safety mechanism has two components communicating via a flag file:
1. Find the write line in the engine (grep `followup-needed`)
2. Find the read line in the wrapper (grep `followup-needed`)
3. Compare the paths character-for-character
4. Verify with a manual run after any change

---

### P-06: Oversaturation Guard Timing Gap

**What happened:** Humidity climbed from 68.66% to 99.91% in 13 minutes. The decision engine correctly turned the humidifier ON at 68.66%, but the next scheduled decision run was 23 minutes away. The follow-up checker could not fire because of the path mismatch (P-05). Both safety layers failed simultaneously.

**Root cause:** The 30-minute decision cycle is too slow for humidity oversaturation events on exposed blocks in second flush, where humidity can climb 20-30% in 10-15 minutes.

**Fix:**
- Fixed follow-up flag path (P-05)
- Lowered oversaturation guard trigger from >= 98% to >= 95%
- Added co-fire mandate: when humidifier turns ON, simultaneously fire `fan burst_120`
- Narrowed humidity band: `accept_max` from 95% to 93%

**Key insight:** The follow-up checker validated *direction* (humidity rising when humidifier ON), not *magnitude*. A runaway from 95% to 99% still passed as "humidity rising as expected." It is a safety net for divergence, not a ceiling for runaway.

---

### P-07: Follow-Up Checker Is Not a Ceiling

**What happened:** The `mycodo-followup-check.py` script registered "success" when humidity rose from 95% to 99% because it only validates that the metric moved in the expected direction after an action. It has no concept that exceeding 98% is dangerous.

**Root cause:** The follow-up checker was designed to catch actuator failures (humidifier ON but humidity not rising), not overshoot events.

**Fix:** Added an oversaturation warning to the follow-up checker when humidity >= 93% during a `humidifier:on` verification. Combined with the oversaturation guard in the decision engine, this provides two-layer protection.

---

### P-08: Physics Mismatch -- Fan Burst Cannot Offset Continuous Humidification

**What happened:** A 360-second fan burst was expected to reduce humidity, but the continuous humidifier added moisture faster than the fan could remove it (approximately 1% RH per minute net gain).

**Root cause:** The architecture assumed periodic venting could offset continuous humidification. It cannot when both are operating simultaneously.

**Fix:** Staggered duty cycles: fire fan burst first, wait for follow-up, then humidifier only if needed. When both CO2 and humidity are out of range, prioritize CO2 (fan) but flag the humidity risk for operator review.

---

## Sensor Pitfalls

### P-09: Sensor Divergence During Continuous Fan

**What happened:** SHT45 and SCD41 readings diverged dramatically during continuous fan operation (>1.5C or >12% humidity difference).

**Root cause:** SHT45 measures tent air directly; SCD41 may be influenced by localized effects near the exhaust path.

**Fix:** Trust SHT45 as tie-breaker for fan authority decisions when sensors diverge.

---

### P-10: Timestamp Estimation After Context Compaction

**What happened:** For two consecutive mornings, the agent reported actuator timestamps offset by approximately 4 hours from actual local time.

**Root cause:** After context compaction, the "Conversation started" timestamp in the system prompt is frozen at session start. Without recent explicit timestamps, the agent inferred current time from stale context clues and produced a 4-hour error (UTC vs local).

**Fix:** Added timestamp discipline rules:
- Never report timestamps by estimation
- Always verify with `date` before reporting when an action occurred
- Re-verify if current time has not been checked within the past 3 messages

**Applicability:** This is not specific to this project -- any agent reporting "I did X at Y time" is vulnerable after context compaction.

---

### P-11: Camera Service vs Agent Integration Confusion

**What happened:** Cron decision engine reported "no image" but manual `sensor-query.sh camera /tmp/test.jpg` returned a fresh 817 KB frame immediately.

**Root cause:** The cron prompt did not instruct the agent to run `sensor-query.sh camera`, and `mycodo-decision.py` has no camera call without the `--camera` flag. The camera *service* was healthy while the *agent's cron integration* never requested an image.

**Fix:** Add `--camera` to the decision engine invocation in the cron prompt.

**Diagnostic flow:**
1. Manual camera command succeeds? Service OK, fix cron/integration
2. Manual camera command fails? Service failure, operator intervention needed

Never assume "no image" means camera broken -- it usually means the agent was not told to fetch it.

---

## Agent Behavior Pitfalls

### P-12: Canonical Source Divergence

**What happened:** `phase_config.py` defined a `rest` phase with thresholds. The canonical `grow-phase.md` did NOT include this phase. Anyone editing thresholds in the markdown missed the rest phase entirely.

**Root cause:** The rest phase was added to the Python config directly but never back-ported to the markdown source.

**Prevention:** Every phase in `phase_config.py` must have a corresponding section in the markdown source. Before editing the Python config, verify the equivalent section exists in the documentation.

---

### P-13: JSON Logging Not Automatic

**What happened:** `mycodo-decision.py --json` writes JSON to stdout but does NOT auto-save to a log file. Agents running it interactively or from cron without stdout redirection lose the data.

**Fix:** Always redirect stdout when logging is needed:
```bash
python3 mycodo-decision.py --phase fruiting --json > ~/mycodo-skill-logs/mycodo_$(date +%Y%m%d_%H%M%S).json 2>&1
```

---

### P-14: Knowledge File Duplication via Append-Only Patterns

**What happened:** Knowledge files updated via append-only cron patterns accumulated duplicate sections when a session appended content that already existed earlier in the file.

**Prevention:** Before appending to any knowledge file, `grep -n` for the key phrase. Prefer `patch` with `old_string`/`new_string` over append-only patterns when updating existing sections.

---

### P-15: Cross-Layer State Drift

**What happened:** The agent's cached memory said "default dry-run" but the live cron had `--execute` since days earlier. Full autonomy was live, but an agent reading only cached memory might have treated actuators as safe to test.

**Root cause:** The agent's system-prompt cache falls out of sync with actual system state after migrations, autonomy toggles, or hardware swaps.

**Prevention:** Use the cross-layer state audit checklist:
1. Read cached memory -- note claims about autonomy, execution mode, hardware
2. Read the live `~/.mycodo-skill-override.json`
3. Verify the cron schedule (check for `--execute`)
4. Check the live relay states
5. Compare and flag any divergence

---

### P-16: Operator Doubt About Safety Mechanisms

**What happened:** The operator previously questioned whether the follow-up checker was working. The agent incorrectly reassured from memory instead of investigating empirically. The checker had been a complete no-op for an unknown duration.

**Root cause:** When an operator expresses doubt about a safety mechanism, the agent must verify it empirically (read the code, run a test) rather than reassure from memory.

**Prevention:** Treat operator doubt about safety as a direct instruction to verify. Read the code, run a manual test, and report the actual result.

---

## Species Config Pitfalls

### P-17: Missing Default Values in Species YAML

**What happened:** Adding an `inactive` phase to `species/lions_mane.yaml` without defining `fan_rules.co2_trigger`, `fan_rules.humidity_floor`, or `fan_rules.burst_duration` caused `KeyError` in the decision engine.

**Root cause:** `mycodo-decision.py` directly accesses `fan_rules["co2_trigger"]` without checking for missing keys.

**Fix:** The species loader now injects default values for all fan_rules and humidifier_rules fields:
- `fan_rules.co2_trigger`: 1200
- `fan_rules.co2_critical`: 2000
- `fan_rules.humidity_floor`: 88
- `fan_rules.burst_duration`: 30
- `humidifier_rules.humidity_target`: 92
- `humidifier_rules.deadband_low`: 85
- `humidifier_rules.deadband_high`: 98

**Prevention:** Always use the loader's default injection, or add explicit keys to every phase.

---

### P-18: YAML Phase Block Misplaced Inside Safety Section

**What happened:** A new `inactive` phase block was accidentally appended inside the `safety:` dictionary, not after it. The YAML parser treated it as a nested safety key rather than a top-level phase.

**Prevention:** After adding phases, verify:
```bash
python3 -c "import yaml; d=yaml.safe_load(open('species/lions_mane.yaml')); print(list(d['phases'].keys()))"
```
If the new phase is missing from the list, check for indentation or placement errors.

---

### P-19: YAML Null Threshold Guard Pattern

**What happened:** The `inactive` phase uses `null` thresholds. Python's `.get(key, default)` returns `None` (the stored value) rather than the default when the key exists but its value is `None`. This caused `TypeError: '<' not supported between instances of 'float' and 'NoneType'`.

**Fix:** Three guard levels:
1. Check if ALL thresholds are null -- return `"unmonitored"` immediately
2. Guard each individual comparison with `is not None`
3. Inject defaults for missing dictionary keys (not null values, missing keys)

**General applicability:** Any system that loads YAML configs with nullable thresholds into Python comparison code will hit this class of bug.

---

### P-20: Import Order When Species Loader Coexists With Legacy Config

**What happened:** After the `species_loader.py` refactor, `mycodo-decision.py` only imported `phase_config` in the `except ImportError` block. When species mode worked, legacy functions like `classify_all` and `get_phase` were missing from scope.

**Fix:** Always import both:
```python
try:
    from species_loader import ...
    from phase_config import classify_all, get_phase  # Still needed
    SPECIES_MODE = True
except ImportError:
    SPECIES_MODE = False
    from phase_config import classify_all, get_phase
```

---

## Timezone Pitfalls

### P-21: UTC Timestamps in User-Facing Reports

**What happened:** HTML report filenames and timestamps showed UTC time (4 hours ahead of local time during EDT). The operator saw `163004` when local time was 12:30 PM, causing cascading confusion.

**Root cause:** `datetime.now(timezone.utc)` was used for both filenames and report timestamps.

**Fix:**
```python
import zoneinfo
local_tz = zoneinfo.ZoneInfo("your configured timezone")  # MYCODO_SKILL_TZ
now_local = datetime.now(local_tz)
ts = now_local.strftime("%Y%m%d_%H%M%S")
```

**Rules:**
- All user-facing timestamps MUST be local time
- Internal timestamps (InfluxDB, epoch) can remain UTC
- The filename stem must match the human-readable timestamp
- Never estimate time from context -- always verify with `date`
- When reporting a timestamp to the operator, include the timezone abbreviation
