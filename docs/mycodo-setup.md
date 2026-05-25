# Mycodo Setup Guide

This guide walks through configuring [Mycodo](https://github.com/kizniche/Mycodo) on your Raspberry Pi so that the Mycodo Hermes Skill can read sensors and control actuators via the API. It assumes Mycodo is already installed and accessible via its web dashboard.

If you haven't installed Mycodo yet, follow the official instructions at [github.com/kizniche/Mycodo](https://github.com/kizniche/Mycodo).

---

## 1. Enable the Mycodo API

The skill communicates with Mycodo through its built-in REST API.

1. Open the Mycodo web dashboard (usually `https://<your-pi-ip>` — Mycodo uses a self-signed HTTPS certificate by default)
2. Navigate to **[Gear icon] > Configure > General**
3. Under **API**, ensure the API is enabled (it is enabled by default in Mycodo 8.15+)
4. Go to **[Gear icon] > Configure > Users** and create or select a user with API access
5. Navigate to **[Gear icon] > Configure > API Keys**
6. Generate a new API key and copy it — this is your `MYCODO_API_KEY`

**Security note:** The API key grants full control over your Mycodo instance. Treat it like a root password. Store it only in `sensor-creds.env` (which is `.gitignore`'d) and set permissions with `chmod 600`.

**Self-signed certificate note:** The skill's `sensor-query.sh` uses `curl -k` to skip certificate verification when talking to the Mycodo API. This is acceptable when the Pi is on a private network (e.g., Tailscale). If your Pi is exposed to the internet, consider configuring a proper TLS certificate.

---

## 2. Configure InfluxDB 2.x

Mycodo stores sensor history in InfluxDB. The skill queries InfluxDB directly for trend analysis, phase transition detection, and follow-up verification using Flux queries.

**Important:** This skill requires **InfluxDB 2.x** (it uses the v2 API, Flux query language, and token-based auth). Mycodo's default installer may set up InfluxDB 1.x depending on your Mycodo version. If your Mycodo instance is running InfluxDB 1.x, you have two options:

- **Upgrade to InfluxDB 2.x** — see the [InfluxDB upgrade guide](https://docs.influxdata.com/influxdb/v2/upgrade/v1-to-v2/)
- **Install InfluxDB 2.x alongside** — run it on port 8086 and configure Mycodo to write to both (advanced)

Check your current version:

```bash
influx version          # Should report 2.x
```

### If InfluxDB 2.x is already running

```bash
influx auth list        # List existing tokens
influx bucket list      # List existing buckets
```

### If you need to configure InfluxDB 2.x

1. Open the InfluxDB dashboard (usually `http://<your-pi-ip>:8086`)
2. Create an organization if one doesn't exist (this is your `INFLUX_ORG`)
3. Create a bucket for sensor data (this is your `INFLUX_BUCKET` — Mycodo's default is typically `mycodo_db`)
4. Generate an API token with **read access** to your sensor bucket (this is your `INFLUX_TOKEN`)

### Verify InfluxDB connectivity

From the machine that will run the skill:

```bash
curl -s -H "Authorization: Token YOUR_INFLUX_TOKEN" \
  "http://YOUR_PI_IP:8086/api/v2/buckets" | jq '.buckets[].name'
```

You should see your bucket name in the output.

---

## 3. Set Up Sensor Inputs

The skill expects two sensors registered in Mycodo as inputs.

### SHT45 (Temperature + Humidity)

1. In the Mycodo dashboard, go to **Data > Inputs**
2. Add a new input: select **Sensirion SHT45** from the dropdown
3. Set the measurement period (15 seconds is recommended — querying more often returns stale values)
4. Activate the input and verify readings appear on the Live Measurements page
5. Copy the **Unique ID** (UUID format, visible in the input settings or the URL bar when viewing the input) — this is your `SHT45_ID`

The SHT45 provides four channels: temperature (°C), humidity (%), dewpoint (°C), and VPD (Pa). The skill uses channels 0 (temperature) and 1 (humidity) as the primary accuracy reference.

### SCD41 (CO2 + Temperature + Humidity)

1. Add another input: select **Sensirion SCD41**
2. Set the measurement period (30 seconds is typical — SCD41 samples slower than SHT45)
3. Activate and verify CO2 readings appear on the Live Measurements page
4. Copy the **Unique ID** — this is your `SCD41_ID`

The SCD41 provides five channels: CO2 (ppm), temperature (°C), humidity (%), dewpoint (°C), and VPD (Pa). The skill uses channel 0 (CO2) as the primary reference. SCD41 temperature and humidity are secondary — expect approximately ±0.3°C and ±10% delta vs the SHT45.

**I2C note:** Both sensors use I2C. If they don't appear in the input dropdown, verify I2C is enabled on your Pi:

```bash
sudo raspi-config    # Interface Options > I2C > Enable
i2cdetect -y 1       # Should show 0x44 (SHT45) and 0x62 (SCD41)
```

If you see the addresses but Mycodo doesn't list the sensors, you may need to install additional Python dependencies for the sensor drivers. Check Mycodo's documentation for your version.

---

## 4. Set Up Actuator Outputs

The skill controls two relay-driven actuators through Mycodo outputs.

### Fan (Fresh Air Exchange)

1. Go to **Function > Outputs**
2. Add a new output: select **On/Off (GPIO)**
3. Set the GPIO pin (GPIO17 is the default in this skill's configs)
4. Set `on_state` to `1` (active-HIGH)
5. Activate and test: toggle the output manually from the Mycodo dashboard to confirm the fan responds
6. Copy the **Unique ID** — this is your `FAE_FAN_ID`

### Humidifier

1. Add another output: **On/Off (GPIO)**
2. Set the GPIO pin (GPIO5 is the default)
3. Set `on_state` to `1` (active-HIGH)
4. Activate and test manually
5. Copy the **Unique ID** — this is your `HUMIDIFIER_RELAY_ID`

**Relay wiring note:** The GPIO pin controls a relay module (e.g., a DLI IoT Power Relay), which in turn switches the humidifier's mains power. The relay sits between the Pi and the humidifier — the Pi never drives the humidifier directly. Use normally-open (NO) contacts so the humidifier defaults to OFF if the Pi loses power.

**Duration support:** The skill uses Mycodo's built-in duration commands for timed actuator bursts (e.g., `fan_burst 60` runs the fan for 60 seconds, then Mycodo automatically turns it off). This is a critical safety feature — if the skill crashes or the agent stops, Mycodo handles the auto-off. Always prefer `fan_burst` / `humidifier_burst` over indefinite `fan_on` / `humidifier_on`.

**Mycodo restart warning:** Restarting the Mycodo daemon resets ALL output states — both fan and humidifier will turn OFF. The decision engine will re-assert the correct state on its next cycle (up to 30 minutes later). If conditions are critical, manually re-enable the appropriate actuators after a Mycodo restart.

---

## 5. Camera (Optional)

If you want visual monitoring with embedded snapshots in reports, you need a USB webcam serving frames via HTTP on the Pi. The skill does **not** use Mycodo's built-in camera function — it downloads frames from a simple nginx-served endpoint.

### Setup

1. **Install fswebcam** (captures frames from USB webcams):

```bash
sudo apt install fswebcam
```

2. **Create a capture script** (e.g., `/usr/local/bin/capture-webcam.sh`):

```bash
#!/bin/bash
fswebcam -r 1920x1080 --no-banner -q /var/www/html/camera/latest.jpg
```

3. **Set up a systemd timer** to capture frames periodically:

```bash
# /etc/systemd/system/webcam-capture.service
[Unit]
Description=Capture webcam frame
[Service]
ExecStart=/usr/local/bin/capture-webcam.sh
User=root

# /etc/systemd/system/webcam-capture.timer
[Unit]
Description=Capture webcam frame every 5 minutes
[Timer]
OnBootSec=60
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
```

Enable it:

```bash
sudo systemctl enable --now webcam-capture.timer
```

4. **Serve the image via nginx**:

```bash
sudo apt install nginx
```

Create `/etc/nginx/sites-available/camera`:

```nginx
server {
    listen 8080;
    root /var/www/html/camera;
    location / {
        try_files $uri =404;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/camera /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

5. **Verify** by opening `http://<your-pi-ip>:8080/latest.jpg` in a browser.

### How the skill uses it

`sensor-query.sh camera` downloads the latest frame from `http://${PI_HOST}:8080/latest.jpg` via curl. When `--camera` is passed to the decision engine, the JPEG is base64-encoded and embedded inline in the HTML report. A raw `.jpg` copy is also saved alongside the HTML for contamination detection training data.

No authentication is needed — the camera endpoint relies on network-level security (e.g., Tailscale or a private LAN). Do not expose port 8080 to the public internet.

---

## 6. Fill In Your Credentials File

Copy the template and fill in the values you collected above:

```bash
mkdir -p ~/.mycodo
cp docs/templates/sensor-creds.env.example ~/.mycodo/sensor-creds.env
chmod 600 ~/.mycodo/sensor-creds.env
```

Edit `~/.mycodo/sensor-creds.env`:

```bash
PI_HOST="192.168.1.xx"             # Your Pi's IP or Tailscale hostname
MYCODO_API_KEY="your-api-key"      # From step 1
INFLUX_TOKEN="your-influx-token"   # From step 2
INFLUX_ORG="your-org-name"         # From step 2
INFLUX_BUCKET="mycodo_db"          # From step 2
SHT45_ID="xxxxxxxx-xxxx-..."      # From step 3
SCD41_ID="xxxxxxxx-xxxx-..."      # From step 3
FAE_FAN_ID="xxxxxxxx-xxxx-..."    # From step 4
HUMIDIFIER_RELAY_ID="xxxxxxxx-xxxx-..."  # From step 4
```

**Credential path note:** The `sensor-query.sh` script must be configured to source this file. Open `scripts/sensor-query.sh` and verify the `CREDS_FILE` variable on line 8 points to `~/.mycodo/sensor-creds.env` (or wherever you placed the file). If you're running this as a Hermes skill, you may prefer a profile-specific path like `~/.hermes/profiles/<name>/credentials/sensor-creds.env`.

---

## 7. Verify the Full Stack

Run these commands from the machine that will host the Hermes agent:

```bash
# Test sensor connectivity (should print temperature, humidity, CO2)
bash scripts/sensor-query.sh quick

# Test a full snapshot (all 9 sensor channels)
bash scripts/sensor-query.sh snapshot

# Test camera (optional — downloads latest frame)
bash scripts/sensor-query.sh camera /tmp/test-frame.jpg

# Test fan relay (timed burst — auto-off after 5 seconds)
bash scripts/sensor-query.sh fan_burst 5

# Test a dry-run decision (no relays fired)
python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting
```

If `sensor-query.sh quick` returns temperature, humidity, and CO2 readings, your Mycodo and InfluxDB configuration is correct. The dry-run decision should print a report showing readings classified against Lion's Mane fruiting thresholds with a `DRY RUN` banner.

---

## Troubleshooting

**"Connection refused" on API calls**
- Verify `PI_HOST` is reachable: `ping $PI_HOST`
- Check Mycodo is running: `ssh pi@$PI_HOST "sudo systemctl status mycodo"`
- Confirm the API is enabled in Mycodo settings

**"401 Unauthorized" on API calls**
- Regenerate the API key in Mycodo's dashboard
- Verify the key in `sensor-creds.env` matches exactly (no trailing whitespace)
- Check the file is being sourced correctly: `source ~/.mycodo/sensor-creds.env && echo $MYCODO_API_KEY`

**Empty credential file (0 bytes)**
- `sensor-query.sh` checks that the credential file exists (`-f`) but does not check that it's non-empty. A 0-byte file will silently source nothing, causing cryptic auth failures. Always verify: `ls -l ~/.mycodo/sensor-creds.env` — size should be > 0.

**InfluxDB returns empty results**
- Check the bucket name matches: `influx bucket list`
- Verify sensor inputs are active and logging: check Mycodo's Live Measurements page
- Confirm you're running InfluxDB 2.x, not 1.x: `influx version`
- InfluxDB retention policies may have expired old data

**I2C sensors not detected**
- Run `i2cdetect -y 1` and check for device addresses (0x44 for SHT45, 0x62 for SCD41)
- Verify wiring: SDA → GPIO2 (pin 3), SCL → GPIO3 (pin 5)
- Check for I2C address conflicts if using other I2C devices

**Relays don't respond to commands**
- Test manually from Mycodo's dashboard first (toggle the output on/off)
- Verify the Unique IDs in `sensor-creds.env` match the outputs in Mycodo (not the inputs)
- Check relay wiring: normally-open (NO) contacts are recommended
- After a Mycodo restart, all outputs reset to OFF — this is expected behavior

**Camera returns "no image"**
- Verify the capture service is running: `systemctl status webcam-capture.timer`
- Check that a fresh image exists: `ls -la /var/www/html/camera/latest.jpg`
- Test the HTTP endpoint directly: `curl -o /tmp/test.jpg http://localhost:8080/latest.jpg`
- If the image exists on the Pi but `sensor-query.sh camera` fails from the agent machine, it's a network/firewall issue — check that port 8080 is accessible
