# Mycodo Hermes Skill Hardware Setup and Known Issues

This document covers hardware setup, known defect patterns, sensor calibration notes, and the camera integration architecture.

---

## Hardware Overview

| Component | Model | Interface | GPIO | Purpose |
|-----------|-------|-----------|------|---------|
| Temperature + Humidity | Sensirion SHT45 | I2C | -- | Primary tent environment sensor |
| CO2 + Temperature + Humidity | Sensirion SCD41 | I2C | -- | CO2 measurement, secondary temp/humidity |
| FAE Exhaust Fan | 4" inline | Relay | GPIO17 | Fresh air exchange, CO2 control |
| Humidifier | VIVOSUN AeroStream H05 | Relay (mains power) | GPIO5 | Humidity control |
| Humidifier Relay | DLI IoT Power Relay v2 | GPIO | GPIO5 | Mains power switching for humidifier |
| Camera | Logitech C920x | USB | -- | Visual monitoring, contamination dataset |
| Controller | Raspberry Pi | -- | -- | Runs Mycodo, InfluxDB, sensor queries |

### Relay configuration

| Relay | GPIO | Signal | Boot Default |
|-------|------|--------|-------------|
| Fan | GPIO17 | Active-HIGH (on_state: 1) | OFF |
| Humidifier | GPIO5 | Active-HIGH (on_state: 1) | OFF |

Both relays default to OFF at boot and shutdown. After a Pi reboot, the decision engine's next run will re-activate them as needed based on current conditions.

---

## Known Defect Patterns

### VIVOSUN AeroStream H05 -- False "No Water" Sensor

**Defect:** Internal water sensor falsely reports "no water" when tank is full, triggering auto-shutoff.

**Confirmed failure pattern:**
- Overnight failure: unit shut off despite full tank
- Repeated same afternoon after reseating tank
- Same false "no water" auto-shutoff both times

**Resolution:** DLI IoT Power Relay v2 installed on GPIO5. The relay controls mains power, not the humidifier's logic board. When ON, the humidifier receives 120V AC and runs regardless of internal sensor state. The defect was bypassed entirely by moving the control point upstream of the defective component.

**Key insight:** The defect did not need to be fixed. It was eliminated by controlling mains power directly. The internal "no water" sensor and auto-shutoff are on the humidifier's PCB -- they need the humidifier to be powered to matter at all.

**Sensor analysis impact:** When the humidifier auto-shuts off (on units without the relay bypass), humidity drops. Sensor readings showing less than 85% RH during fruiting may indicate equipment failure rather than environmental drift.

### Relay control commands

```bash
sensor-query.sh humidifier_on      # Turn relay ON, humidifier gets power
sensor-query.sh humidifier_off     # Turn relay OFF, humidifier stops
sensor-query.sh humidifier_burst   # Timed ON with auto-off (prevents orphaned state)
sensor-query.sh humidifier_status  # Query relay state (on/off)
```

**Safety note:** `humidifier_burst <seconds>` is preferred over `humidifier_on` because it prevents accidental continuous operation if the decision engine crashes or loses connectivity. Mycodo handles duration-based auto-off for burst commands.

---

### Camera Service Silence -- Snapshot Gaps

**Observation:** Camera snapshots may cease for multiple days despite the Pi and Mycodo daemon remaining operational.

**Detection:**
1. Check `sensor-data/snapshots/` for files newer than the last expected capture
2. Run `sensor-query.sh camera-list` to verify whether Mycodo has fresh history entries
3. Check `sensor-query.sh status` -- Mycodo daemon may be running while the camera module fails

**Impact during high-risk phases:**
- Second flush contamination risk is approximately 9.5x higher than first flush
- Visual confirmation is the primary early-detection channel for green mold, bacterial spots, and abnormal morphology
- Sensor data (CO2, humidity, temperature) cannot replace visual inspection for contamination identification
- Loss of camera during second flush means loss of the most critical sensory channel at the most dangerous time

**Response protocol:**
1. Log the gap with exact last-successful timestamp
2. Flag immediately in daily reports
3. Do NOT downgrade urgency because "sensors still work" -- sensors detect metabolic drift, cameras detect morphology
4. Suggested operator checks: USB connection, Mycodo camera module status, Pi storage fullness (`df -h`)

---

### Sensor Divergence During Continuous Fan

**Observation:** SHT45 and SCD41 may diverge dramatically during continuous fan operation (greater than 1.5C or 12% humidity difference).

**Rationale:** SHT45 measures tent air directly; SCD41 may be influenced by localized effects near the exhaust path.

**Rule:** Trust SHT45 as tie-breaker for fan authority decisions when sensors diverge.

---

## Camera Service vs Agent Integration

There are two independent failure modes that produce "no image" in reports:

### 1. Camera service failure (Pi-side)

The Raspberry Pi's camera module stops producing snapshots. Causes: Mycodo service restart, camera disconnected, USB power issue, Mycodo camera function disabled.

**Detection:**
```bash
sensor-query.sh camera-list          # stale timestamps?
sensor-query.sh camera /tmp/test.jpg # fails or 0 bytes?
```

If both fail, this is a Pi-side service failure requiring operator attention.

### 2. Agent integration failure (cron-side)

The camera service is healthy, but the cron job prompt never requests the image.

**Detection:**
- Manual `sensor-query.sh camera /tmp/test.jpg` succeeds with fresh data -- service is fine
- Check the cron job prompt -- does it include `--camera`?

If the cron prompt does NOT mention camera retrieval, this is an integration failure. Fix the cron configuration, not the Pi.

### Why this distinction matters

`mycodo-decision.py` does NOT automatically capture camera images. The `--camera` flag must be passed explicitly. Without it, the script skips the camera step entirely.

**Diagnostic flow chart:**
1. Manual camera command succeeds? -> Service OK, fix cron/integration
2. Manual camera command fails? -> Service failure, operator intervention needed

---

## Camera Image Embedding

When `--camera` is passed, the decision engine:

1. Downloads a JPEG from the Pi via `sensor-query.sh camera`
2. Base64-encodes the image
3. Embeds it inline in the HTML report as a data URI

This makes the HTML fully self-contained -- no external image links that break, no separate file dependencies. Firefox headless screenshots capture the image as part of the page for Telegram delivery.

### Storage estimates

| Grow cycle length | Embedded HTML only | Split HTML + raw JPG |
|-------------------|-------------------|---------------------|
| 14 days | 0.76 GB | 0.57 GB |
| 30 days | 1.63 GB | 1.23 GB |
| 45 days | 2.45 GB | 1.84 GB |

Use the split model. Keep raw `.jpg` alongside `.html` for contamination model training. Archive per-cycle to external storage.

### Fallback behavior

If the camera is unreachable, the HTML shows a warning message rather than silently omitting the section. The operator knows a visual check was attempted.

---

## Sensor Calibration Notes

### SHT45 (Primary for temperature and humidity)

- Measures tent air directly
- Preferred sensor for fan authority decisions
- Accuracy: typically within 1.0% RH, 0.1C

### SCD41 (Primary for CO2, secondary for temperature and humidity)

- CO2 is the most diagnostic metabolic signal for phase detection
- May be influenced by localized airflow effects near the exhaust path
- Use as primary for CO2 decisions, secondary for temperature/humidity

### Sensor authority configuration

Configured per-species in the YAML:
```yaml
sensor_authority:
  temperature: sht45
  humidity: sht45
  co2: scd41
```

---

## Mycodo Restart Behavior

On Pi reboot, Mycodo resets ALL GPIO outputs to OFF:
- Fan (GPIO17) turns OFF
- Humidifier (GPIO5) turns OFF

The next decision engine run detects both actuators are OFF, reads current conditions, and fires appropriate commands to restore the target state. No manual intervention is required.

---

## Adding New Hardware

When adding a new actuator or sensor:

1. Configure it in the Mycodo dashboard on the Pi
2. Note the Mycodo output/input ID (UUID format)
3. Add query commands to `sensor-query.sh`
4. Update `mycodo-decision.py` to query the new device's state
5. Add the device to the species YAML rules if it affects phase logic
6. Update `~/.mycodo-skill-override.json` to include override controls for the new actuator
7. Test with `--execute` disabled first (dry-run mode)
