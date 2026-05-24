#!/bin/bash
# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# License: MIT
#
# sensor-query.sh — Wrapper for Mycodo/InfluxDB/Camera queries
# Credentials are sourced at runtime, never exposed to the agent context

set -euo pipefail

# Credential location (configurable via env var)
CREDS_FILE="${MYCODO_SKILL_CREDS:-$HOME/.mycodo/sensor-creds.env}"
if [ ! -f "$CREDS_FILE" ]; then
    echo "ERROR: Credentials file not found at $CREDS_FILE"
    exit 1
fi

source "$CREDS_FILE"

INFLUX_URL="http://${PI_HOST}:8086/api/v2/query?org=${INFLUX_ORG}"
MYCODO_URL="https://${PI_HOST}/api"

# Helper: Mycodo REST GET
mycodo_get() {
    curl -sk         -H "X-API-KEY: ${MYCODO_API_KEY}"         -H "Accept: application/vnd.mycodo.v1+json"         "${MYCODO_URL}${1}"
}

# Helper: Mycodo REST POST
mycodo_post() {
    curl -sk -X POST         -H "X-API-KEY: ${MYCODO_API_KEY}"         -H "Accept: application/vnd.mycodo.v1+json"         "${MYCODO_URL}${1}"
}

# Helper: InfluxDB Flux query
influx_query() {
    curl -s         -H "Authorization: Token ${INFLUX_TOKEN}"         -H "Content-Type: application/vnd.flux"         -H "Accept: application/csv"         "${INFLUX_URL}"         -d "$1"
}

CMD="${1:-help}"
shift || true

case "$CMD" in

    temperature)
        mycodo_get "/measurements/last/${SHT45_ID}/C/0/120"
        ;;

    humidity)
        mycodo_get "/measurements/last/${SHT45_ID}/percent/1/120"
        ;;

    co2)
        mycodo_get "/measurements/last/${SCD41_ID}/ppm/0/120"
        ;;

    quick)
        echo "=== Temperature (SHT45) ==="
        mycodo_get "/measurements/last/${SHT45_ID}/C/0/120"
        echo ""
        echo "=== Humidity (SHT45) ==="
        mycodo_get "/measurements/last/${SHT45_ID}/percent/1/120"
        echo ""
        echo "=== CO2 (SCD41) ==="
        mycodo_get "/measurements/last/${SCD41_ID}/ppm/0/120"
        ;;

    snapshot)
        influx_query "from(bucket:\"${INFLUX_BUCKET}\") |> range(start:-5m) |> last()"
        ;;

    history)
        DURATION="${1:-1h}"
        influx_query "from(bucket:\"${INFLUX_BUCKET}\") |> range(start:-${DURATION})"
        ;;

    trend)
        MEASURE="${1:-co2}"
        DURATION="${2:-6h}"
        if [ "$MEASURE" = "co2" ]; then
            FILTER="r._measurement == \"ppm\" and r.measure == \"co2\""
        elif [ "$MEASURE" = "temperature" ]; then
            FILTER="r._measurement == \"C\" and r.measure == \"temperature\""
        elif [ "$MEASURE" = "humidity" ]; then
            FILTER="r._measurement == \"percent\" and r.measure == \"humidity\""
        else
            echo "ERROR: Unknown measure '$MEASURE'. Use: co2, temperature, humidity"
            exit 1
        fi
        influx_query "from(bucket:\"${INFLUX_BUCKET}\") |> range(start:-${DURATION}) |> filter(fn: (r) => ${FILTER}) |> aggregateWindow(every: 15m, fn: mean)"
        ;;

    camera)
        OUTPUT="${1:-/tmp/latest.jpg}"
        curl -s -o "$OUTPUT" "http://${PI_HOST}:8080/latest.jpg"
        if [ -f "$OUTPUT" ]; then
            SIZE=$(stat -c%s "$OUTPUT" 2>/dev/null || stat -f%z "$OUTPUT" 2>/dev/null)
            echo "Saved to ${OUTPUT} (${SIZE} bytes)"
        else
            echo "ERROR: Failed to download camera image"
            exit 1
        fi
        ;;

    camera-list)
        curl -s "http://${PI_HOST}:8080/"
        ;;

    camera-history)
        FILENAME="${1:?Usage: sensor-query.sh camera-history <filename> <output_path>}"
        OUTPUT="${2:-/tmp/${FILENAME}}"
        curl -s -o "$OUTPUT" "http://${PI_HOST}:8080/${FILENAME}"
        if [ -f "$OUTPUT" ]; then
            SIZE=$(stat -c%s "$OUTPUT" 2>/dev/null || stat -f%z "$OUTPUT" 2>/dev/null)
            echo "Saved to ${OUTPUT} (${SIZE} bytes)"
        else
            echo "ERROR: Failed to download ${FILENAME}"
            exit 1
        fi
        ;;

    status)
        mycodo_get "/daemon/"
        ;;

    force-read)
        SENSOR="${1:-sht45}"
        if [ "$SENSOR" = "sht45" ]; then
            mycodo_post "/inputs/${SHT45_ID}/force-measurement"
        elif [ "$SENSOR" = "scd41" ]; then
            mycodo_post "/inputs/${SCD41_ID}/force-measurement"
        else
            echo "ERROR: Unknown sensor '$SENSOR'. Use: sht45, scd41"
            exit 1
        fi
        ;;

    fan_on)
        curl -sk -X POST             -H "X-API-KEY: ${MYCODO_API_KEY}"             -H "Content-Type: application/json"             -H "Accept: application/vnd.mycodo.v1+json"             -d '{"state": true, "channel": 0}'             "${MYCODO_URL}/outputs/${FAE_FAN_ID}"
        ;;

    fan_off)
        curl -sk -X POST             -H "X-API-KEY: ${MYCODO_API_KEY}"             -H "Content-Type: application/json"             -H "Accept: application/vnd.mycodo.v1+json"             -d '{"state": false, "channel": 0}'             "${MYCODO_URL}/outputs/${FAE_FAN_ID}"
        ;;

    fan_burst)
        DURATION="${1:?Usage: sensor-query.sh fan_burst <seconds>}"
        curl -sk -X POST \
            -H "X-API-KEY: ${MYCODO_API_KEY}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/vnd.mycodo.v1+json" \
            -d "{\"state\": true, \"channel\": 0, \"duration\": ${DURATION}}" \
            "${MYCODO_URL}/outputs/${FAE_FAN_ID}"
        ;;

    fan_status)
        mycodo_get "/outputs/${FAE_FAN_ID}"
        ;;

    humidifier_on)
        curl -sk -X POST \
            -H "X-API-KEY: ${MYCODO_API_KEY}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/vnd.mycodo.v1+json" \
            -d '{"state": true, "channel": 0}' \
            "${MYCODO_URL}/outputs/${HUMIDIFIER_RELAY_ID}"
        ;;

    humidifier_off)
        curl -sk -X POST \
            -H "X-API-KEY: ${MYCODO_API_KEY}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/vnd.mycodo.v1+json" \
            -d '{"state": false, "channel": 0}' \
            "${MYCODO_URL}/outputs/${HUMIDIFIER_RELAY_ID}"
        ;;

    humidifier_burst)
        DURATION="${1:?Usage: sensor-query.sh humidifier_burst <seconds>}"
        curl -sk -X POST \
            -H "X-API-KEY: ${MYCODO_API_KEY}" \
            -H "Content-Type: application/json" \
            -H "Accept: application/vnd.mycodo.v1+json" \
            -d "{\"state\": true, \"channel\": 0, \"duration\": ${DURATION}}" \
            "${MYCODO_URL}/outputs/${HUMIDIFIER_RELAY_ID}"
        ;;

    humidifier_status)
        mycodo_get "/outputs/${HUMIDIFIER_RELAY_ID}"
        ;;

    help)
        echo "Usage: sensor-query.sh <command> [args]"
        echo ""
        echo "Quick reads:"
        echo "  temperature          SHT45 current temp (C)"
        echo "  humidity             SHT45 current humidity (%)"
        echo "  co2                  SCD41 current CO2 (ppm)"
        echo "  quick                All three at once"
        echo ""
        echo "InfluxDB queries:"
        echo "  snapshot             All 9 channels, latest reading"
        echo "  history <duration>   Raw data (e.g., 1h, 6h, 24h)"
        echo "  trend <measure> <duration>"
        echo "                       15-min averages (co2|temperature|humidity)"
        echo ""
        echo "Camera:"
        echo "  camera <path>        Download latest snapshot"
        echo "  camera-list          List available snapshots"
        echo "  camera-history <file> <path>"
        echo "                       Download specific snapshot"
        echo ""
        echo "Fan control:"
        echo "  fan_on               Turn FAE fan ON"
        echo "  fan_off              Turn FAE fan OFF"
        echo "  fan_burst <seconds>  Turn fan ON for N seconds (auto-off)"
        echo "  fan_status           Check FAE fan state"
        echo ""
        echo "Humidifier control:"
        echo "  humidifier_on        Turn humidifier ON"
        echo "  humidifier_off       Turn humidifier OFF"
        echo "  humidifier_burst <seconds>"
        echo "                       Turn humidifier ON for N seconds (auto-off)"
        echo "  humidifier_status    Check humidifier relay state"
        echo ""
        echo "System:"
        echo "  status               Mycodo daemon status"
        echo "  force-read <sensor>  Force immediate read (sht45|scd41)"
        ;;

    *)
        echo "ERROR: Unknown command '$CMD'. Run with 'help' for usage."
        exit 1
        ;;
esac
