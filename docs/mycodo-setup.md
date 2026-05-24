# Mycodo Setup Guide

This guide walks through configuring [Mycodo](https://github.com/kizniche/Mycodo) on your Raspberry Pi so that the Mycodo Hermes Skill can read sensors and control actuators via the API. It assumes Mycodo is already installed and accessible via its web dashboard.

If you haven't installed Mycodo yet, follow the official instructions at [github.com/kizniche/Mycodo](https://github.com/kizniche/Mycodo).

---

## 1. Enable the Mycodo API

The skill communicates with Mycodo through its built-in REST API.

1. Open the Mycodo web dashboard (usually `http://<your-pi-ip>` or `https://<your-pi-ip>`)
2. Navigate to **[Gear icon] > Configure > General**
3. Under **API**, ensure the API is enabled
4. Go to **[Gear icon] > Configure > Users** and create or select a user with API access
5. Navigate to **[Gear icon] > Configure > API Keys**
6. Generate a new API key and copy it — this is your `MYCODO_API_KEY`

**Security note:** The API key grants full control over your Mycodo instance. Treat it like a root password. Store it only in `sensor-creds.env` (which is `.gitignore`'d) and set permissions with `chmod 600`.

---

## 2. Configure InfluxDB 2.x

Mycodo stores sensor history in InfluxDB. The skill queries InfluxDB directly for trend analysis (phase transitions, follow-up verification).

### If Mycodo installed InfluxDB for you

Mycodo's installer may have set up InfluxDB automatically. Check:

```bash
influx version          # Confirm InfluxDB 2.x is running
influx auth list        # List existing tokens
influx bucket list      # List existing buckets
```

### If you need to configure InfluxDB manually

1. Open the InfluxDB dashboard (usually `http://<your-pi-ip>:8086`)
2. Create an organization if one doesn't exist (this is your `INFLUX_ORG`)
3. Create a bucket for sensor data (this is your `INFLUX_BUCKET` — Mycodo's default is typically `mycodo_db`)
4. Generate an API token with read access to your bucket (this is your `INFLUX_TOKEN`)

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
3. Set the measurement period (15 seconds is typical)
4. Activate the input and verify readings appear on the dashboard
5. Copy the **Input ID** (UUID format, visible in the input settings) — this is your `SHT45_ID`

### SCD41 (CO2 + Temperature + Humidity)

1. Add another input: select **Sensirion SCD41**
2. Set the measurement period (30 seconds is typical — SCD41 is slower)
3. Activate and verify CO2 readings appear
4. Copy the **Input ID** — this is your `SCD41_ID`

**I2C note:** Both sensors use I2C. If they don't appear, verify I2C is enabled on your Pi:

```bash
sudo raspi-config    # Interface Options > I2C > Enable
i2cdetect -y 1       # Should show device addresses (0x44 for SHT45, 0x62 for SCD41)
```

---

## 4. Set Up Actuator Outputs

The skill controls two relay-driven actuators through Mycodo outputs.

### Fan (Fresh Air Exchange)

1. Go to **Function > Outputs**
2. Add a new output: select **On/Off (GPIO)**
3. Set the GPIO pin (GPIO17 is the default in this skill's configs)
4. Set `on_state` to `1` (active-HIGH)
5. Activate and test: toggle the output manually to confirm the fan responds
6. Copy the **Output ID** — this is your `FAE_FAN_ID`

### Humidifier

1. Add another output: **On/Off (GPIO)**
2. Set the GPIO pin (GPIO5 is the default)
3. Set `on_state` to `1` (active-HIGH)
4. Activate and test manually
5. Copy the **Output ID** — this is your `HUMIDIFIER_RELAY_ID`

**Duration support:** The skill uses Mycodo's built-in duration commands for timed actuator bursts (e.g., "run humidifier for 60 seconds"). Mycodo handles the auto-off, so a crashed skill won't leave actuators stuck on.

---

## 5. Camera (Optional)

If you want visual monitoring in reports:

1. Connect a USB webcam to the Pi
2. In Mycodo, go to **Function > Camera**
3. Add a new camera function and configure it to use your USB device
4. Test a manual capture from the Mycodo dashboard

The skill queries the camera through `sensor-query.sh camera` which calls the Mycodo API's camera endpoint. Pass `--camera` to the decision engine to include snapshots in reports.

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
PI_HOST="192.168.1.xx"             # Your Pi's IP or hostname
MYCODO_API_KEY="your-api-key"      # From step 1
INFLUX_TOKEN="your-influx-token"   # From step 2
INFLUX_ORG="your-org-name"         # From step 2
INFLUX_BUCKET="mycodo_db"          # From step 2
SHT45_ID="xxxxxxxx-xxxx-..."      # From step 3
SCD41_ID="xxxxxxxx-xxxx-..."      # From step 3
FAE_FAN_ID="xxxxxxxx-xxxx-..."    # From step 4
HUMIDIFIER_RELAY_ID="xxxxxxxx-xxxx-..."  # From step 4
```

---

## 7. Verify the Full Stack

Run these commands from the machine that will host the Hermes agent:

```bash
# Test sensor connectivity
bash scripts/sensor-query.sh quick

# Test a dry-run decision (no relays fired)
python3 mycodo_skill/decision_engine.py --species lions_mane --phase fruiting
```

If `sensor-query.sh quick` returns temperature, humidity, and CO2 readings, your Mycodo and InfluxDB configuration is correct.

---

## Troubleshooting

**"Connection refused" on API calls**
- Verify `PI_HOST` is reachable: `ping $PI_HOST`
- Check Mycodo is running: `ssh pi@$PI_HOST "sudo systemctl status mycodo"`
- Confirm the API is enabled in Mycodo settings

**"401 Unauthorized" on API calls**
- Regenerate the API key in Mycodo's dashboard
- Verify the key in `sensor-creds.env` matches exactly (no trailing whitespace)

**InfluxDB returns empty results**
- Check the bucket name matches: `influx bucket list`
- Verify sensor inputs are active and logging: check Mycodo's Live Measurements page
- InfluxDB retention policies may have expired old data

**I2C sensors not detected**
- Run `i2cdetect -y 1` and check for device addresses
- Verify wiring: SDA → GPIO2 (pin 3), SCL → GPIO3 (pin 5)
- Check for I2C address conflicts if using other I2C devices

**Relays don't respond to commands**
- Test manually from Mycodo's dashboard first
- Verify GPIO pin numbers match between Mycodo config and `sensor-creds.env`
- Check relay wiring: normally-open (NO) contacts are recommended
