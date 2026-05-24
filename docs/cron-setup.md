# Mycodo Hermes Skill Cron Configuration Guide

This document covers the cron job setup for the Mycodo Hermes Skill decision engine, adaptive follow-up system, and optional contamination pipeline.

---

## Core Cron Jobs

### 1. Decision Engine (30-minute cycle)

The primary environmental control loop.

| Field | Value |
|-------|-------|
| **Name** | Mycodo Decision Engine -- 30min |
| **Schedule** | `*/30 * * * *` |
| **Type** | LLM agent (reasoned) |
| **Delivery** | Telegram DM (silent on no-action) |

```cron
*/30 * * * * python3 ~/scripts/mycodo-decision.py --species lions_mane --phase fruiting --auto-phase --execute --camera --html --html-dir ~/reports/
```

**What it does each run:**
1. Fetches live sensor snapshot
2. Detects or accepts phase
3. Classifies metrics vs species thresholds
4. Queries fan + humidifier relay state
5. Generates and executes actions
6. Writes follow-up flag if actions fired
7. Generates HTML report with embedded camera image

**Critical flags:**
- `--execute` -- REQUIRED for relay commands to actually fire (see pitfall P-01)
- `--camera` -- REQUIRED for camera image in reports (see pitfall P-11)
- `--html --html-dir <path>` -- generates self-contained HTML report
- `--species <id>` -- loads species-specific thresholds
- `--auto-phase` -- enables auto-transition between phases

---

### 2. Adaptive Follow-Up (10-minute cycle)

Zero-cost verification that actuator actions produced the expected environmental change.

| Field | Value |
|-------|-------|
| **Name** | Mycodo Adaptive Follow-up -- 10min |
| **Schedule** | `*/10 * * * *` |
| **Type** | no_agent (script, zero tokens) |
| **Delivery** | Origin chat (on failure only) |

```cron
*/10 * * * * bash ~/scripts/mycodo-followup-wrapper.sh
```

**What it does each run:**
1. Checks for `~/.mycodo-skill-followup`
2. If absent: silent exit (no output, no cost)
3. If present + 10min elapsed: re-reads sensors
4. Verifies environmental improvement (humidity rose after humidifier ON, CO2 dropped after fan burst, etc.)
5. Clears flag on success, alerts on failure

**Critical:** The flag path in the wrapper script MUST match the path used by the decision engine (`$HOME/.mycodo-skill-followup`). See pitfall P-05 for what happens when they diverge.

---

### 3. Scheduled Sensor Checks (Optional)

These provide baseline readings for trend analysis and evening audits.

```cron
# Morning sensor fetch
0 6 * * * bash ~/scripts/sensor-query.sh snapshot > ~/sensor-data/raw/sensor-overnight.md

# Morning brief
15 6 * * * # LLM agent run: morning brief with sensor + cron summary

# PM sensor fetch
0 15 * * * bash ~/scripts/sensor-query.sh snapshot > ~/sensor-data/raw/sensor-pm-fetch.md

# PM sensor analysis
15 15 * * * # LLM agent run: PM analysis with phase comparison

# Evening security check
0 20 * * * # LLM agent run: evening audit (sensor health, fan state, visual check)
```

---

## Evening Audit Pipeline

The evening audit combines sensor health verification, security inspection, and memory accuracy cross-checks.

### Protocol

1. **Current sensor readings** -- `sensor-query.sh quick` compared against current phase targets
2. **Fan status check** -- verify fan state matches protocol expectations
3. **Visual security scan** -- capture camera snapshot for operator review
4. **Memory accuracy cross-check** -- validate recent claims against raw sensor logs
5. **Outstanding risk summary** -- numbered list of flagged issues

### Robustness rules

- If the decision engine fails for any reason, the audit must NOT abort. Proceed with manual threshold comparison.
- If raw fetch files are absent (first run or stale cron), query live data instead using `sensor-query.sh trend <metric> 6h`.
- Use `trend` for routine status checks; use `history` only when investigating specific anomalies (trend produces ~1 KB, history produces 2+ MB).

---

## Token Economics

| Component | Per-Run Cost | Daily Runs | Est. Daily Cost |
|-----------|-------------|------------|-----------------|
| Decision Engine (30min) | Medium (reasoning + actuator execution) | 48 | ~48 mid-tier calls |
| Follow-up (10min) | **Zero** | 144 | 0 |
| Morning/PM/Evening checks | Low-to-medium | 5 | ~5 calls |
| **Total** | | **197** | **~53 LLM calls/day** |

The adaptive follow-up saves approximately 144 LLM calls per day by handling verification in pure Python.

---

## Frequency Tuning

| Goal | Decision Schedule | Follow-up Schedule | Token Impact |
|------|------------------|--------------------|-------------|
| Default | `*/30 * * * *` | `*/10 * * * *` | 53 calls/day |
| Faster decisions | `*/15 * * * *` | `*/10 * * * *` | 101 calls/day |
| Slower decisions | `0 */2 * * *` | `*/15 * * * *` | ~17 calls/day |

Adjust follow-up independently: keep 10min or increase to 15min for slower-responding environments.

### Why 30 minutes?

- **Faster than 60m:** Responsive species react to environmental swings quickly. 30m catches drift before it becomes a problem.
- **Not too fast:** 15m would over-fire during natural fluctuation. 30m gives the environment time to stabilize after actions.
- **Backed by follow-up:** Even if a decision misses something, the 10m follow-up catches it.

---

## Mycodo Restart Handling

On Pi reboot, Mycodo resets ALL outputs to OFF (both fan and humidifier). The next decision engine run:
1. Detects both actuators are OFF
2. Reads current conditions
3. Fires appropriate commands to restore target state
4. No manual intervention required

---

## Optional: Contamination Pipeline Schedule

If using the contamination monitoring pipeline, add Reddit fetch cron jobs:

```cron
# Morning contamination fetch (AM)
0 10 * * * python3 ~/scripts/reddit-fetch-parser.py --out ~/reddit-feeds/raw/contamination-fetch.md --days 7

# Evening contamination fetch (PM)
0 18 * * * python3 ~/scripts/reddit-fetch-parser.py --out ~/reddit-feeds/raw/contamination-fetch-pm.md --days 7
```

Check fetch freshness: if the latest `contamination-fetch.md` is older than 24 hours, the pipeline may be stalled. See the contamination pipeline documentation for manual fallback procedures.

---

## Common Cron Mistakes

1. **Missing `--execute`:** Decision engine defaults to dry-run mode. Reports show "Action Taken" but no relays fire. Always include `--execute` for live control.

2. **Missing `--camera`:** HTML reports will have no camera image. Camera fetching is NOT automatic.

3. **Dropping flags when editing:** When adding new flags to a cron prompt, append rather than replace. Always diff old vs new command strings.

4. **Relative paths in prompts:** Cron jobs run in isolated sessions. Use absolute paths or `$HOME`-relative paths, never `workspace/...` relative paths.

5. **Follow-up wrapper path mismatch:** The wrapper and decision engine MUST use the same flag path (`$HOME/.mycodo-skill-followup`). Verify both after any change.

---

## Directory Requirements

Ensure these directories exist before cron jobs run:

```bash
mkdir -p ~/sensor-data/raw \
         ~/sensor-data/snapshots \
         ~/reports/ \
         ~/mycodo-skill-logs/
```

Camera snapshots should save to `~/sensor-data/snapshots/` (not `/tmp/`) so they survive reboot and are available for later analysis.
