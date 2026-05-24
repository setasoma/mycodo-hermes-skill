# Part of mycodo-hermes-skill — autonomous mushroom cultivation for Hermes agents
# https://github.com/YOUR_GITHUB_USERNAME/mycodo-hermes-skill
# License: MIT

"""
Phase Detector — Automatic Cultivation Phase Classification
==========================================================

Based on 46 days of sensor archaeology (366 records across 99 files).
Core insight: CO2 is the most diagnostic signal because it directly
measures biological metabolism.

Algorithm v2 (boundary-aware):
- CO2 > 1500 ppm  -> colonization   (high confidence >0.85)
- 800 <= CO2 <= 1500 and spread > 200 -> primordia (medium confidence)
- CO2 < 800 ppm   -> fruiting       (high confidence >0.75)
- CO2 < 500 ppm and temp > 20 C -> post-harvest (medium confidence)

Usage:
    from mycodo_skill.phase_detector import PhaseDetector, detect_phase

    # Single snapshot
    phase, confidence, reasoning = PhaseDetector.classify_snapshot(
        co2=744, temp=18.5, humidity=89.6
    )

    # From sequence (more robust)
    phase, confidence, reasoning = PhaseDetector.classify_sequence([
        {"co2": 562, "timestamp": "2026-05-18T10:00:00Z"},
        {"co2": 775, "timestamp": "2026-05-18T15:00:00Z"},
    ])
"""

import math
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class PhaseResult:
    phase: str          # colonization | primordia | fruiting | post_harvest | unknown
    confidence: float   # 0.0-1.0
    reasoning: str      # human-readable explanation
    alert: bool = False # True if readings are in critical/anomalous ranges
    recommended_action: str = ""


class PhaseDetector:
    """Automatic cultivation phase detection from environmental sensor data."""

    # Phase boundaries (tuned from 46-day sensor archaeology)
    COLONIZATION_THRESHOLD = 1500  # CO2 ppm — above this, colonization is highly likely
    PRIMORDIA_UPPER = 1500         # CO2 ppm — upper bound of primordia range
    PRIMORDIA_LOWER = 800          # CO2 ppm — lower bound of primordia range
    FRUITING_THRESHOLD = 800       # CO2 ppm — below this, fruiting is likely
    POST_HARVEST_CO2 = 500         # CO2 ppm — very low CO2 + ambient temp = post-harvest

    # Confidence calibration
    COLONIZATION_BASE_CONF = 0.70
    FRUITING_BASE_CONF = 0.75
    PRIMORDIA_BASE_CONF = 0.60
    HUMIDITY_BOOST = 0.15

    @classmethod
    def classify_snapshot(cls, co2: Optional[float], temp: Optional[float] = None,
                          humidity: Optional[float] = None) -> 'PhaseResult':
        """
        Classify a single sensor snapshot.

        Args:
            co2: CO2 concentration in ppm
            temp: Temperature in C (optional, improves confidence)
            humidity: Relative humidity in % (optional, improves confidence)

        Returns:
            PhaseResult with phase, confidence, reasoning
        """
        if co2 is None:
            return PhaseResult(
                phase="unknown", confidence=0.0,
                reasoning="No CO2 data available — cannot classify without metabolic signal"
            )

        co2 = float(co2)
        confidence = 0.0
        reasons = []
        phase = "unknown"
        alert = False
        action = ""

        # --- COLONIZATION ---
        if co2 > cls.COLONIZATION_THRESHOLD:
            phase = "colonization"
            # Confidence increases with CO2 level (max 0.98 at 4000+)
            confidence = min(0.98, cls.COLONIZATION_BASE_CONF + (co2 - cls.COLONIZATION_THRESHOLD) / 5000)
            reasons.append(f"CO2 {co2:.0f} ppm exceeds {cls.COLONIZATION_THRESHOLD} ppm — active colonization metabolism")
            if co2 > 3000:
                reasons.append("Very high CO2 — late colonization / peak metabolic activity")
            alert = co2 > 8000
            if alert:
                action = "Consider brief ventilation to prevent anaerobic conditions"

        # --- PRIMORDIA (transition zone) ---
        elif cls.PRIMORDIA_LOWER <= co2 <= cls.PRIMORDIA_UPPER:
            phase = "primordia"
            confidence = cls.PRIMORDIA_BASE_CONF
            reasons.append(f"CO2 {co2:.0f} ppm in {cls.PRIMORDIA_LOWER}–{cls.PRIMORDIA_UPPER} range — transitional phase")

            # Humidity adds confidence
            if humidity is not None:
                if humidity > 90:
                    confidence += cls.HUMIDITY_BOOST
                    reasons.append(f"High humidity ({humidity:.1f}%) supports primordia/pinning")
                elif humidity < 70:
                    confidence -= 0.10
                    reasons.append(f"Low humidity ({humidity:.1f}%) may stress primordia")

            # Temperature adds confidence
            if temp is not None and 15 <= temp <= 20:
                confidence += 0.05
                reasons.append(f"Temperature {temp:.1f} C in primordia trigger range")

            alert = co2 > 1200 and (humidity is not None and humidity < 85)
            if alert:
                action = "CO2 elevated for primordia — increase fresh air exchange if humidity allows"

        # --- FRUITING or POST-HARVEST ---
        elif co2 < cls.FRUITING_THRESHOLD:
            # Distinguish post-harvest from active fruiting
            if co2 < cls.POST_HARVEST_CO2 and temp is not None and temp > 20:
                phase = "post_harvest"
                confidence = 0.55
                reasons.append(f"CO2 {co2:.0f} ppm very low + temp {temp:.1f} C elevated — post-harvest / ambient conditions")
            else:
                phase = "fruiting"
                confidence = cls.FRUITING_BASE_CONF
                reasons.append(f"CO2 {co2:.0f} ppm below {cls.FRUITING_THRESHOLD} — low metabolic, fruiting phase")

                if humidity is not None:
                    if 85 <= humidity <= 100:
                        confidence += cls.HUMIDITY_BOOST
                        reasons.append(f"Humidity {humidity:.1f}% in fruiting range (85-100%)")
                    elif humidity < 70:
                        confidence -= 0.15
                        reasons.append(f"WARNING: Humidity {humidity:.1f}% below survival threshold — manual humidification needed")
                        alert = True
                        action = "URGENT: Rehumidify immediately to prevent fruiting body desiccation"
                    elif humidity < 85:
                        alert = True
                        action = "Humidity below ideal — manual misting recommended"

                if temp is not None:
                    if temp > 21:
                        confidence -= 0.05
                        reasons.append(f"Temperature {temp:.1f} C approaching upper limit (21 C)")
                    elif temp < 15:
                        alert = True
                        reasons.append(f"WARNING: Temperature {temp:.1f} C below fruiting floor (15 C)")
                        action = "Temperature too low — consider environmental heating"

        else:
            reasons.append(f"CO2 {co2:.0f} ppm does not match any known phase boundary")

        confidence = max(0.0, min(1.0, confidence))

        return PhaseResult(
            phase=phase,
            confidence=round(confidence, 2),
            reasoning="; ".join(reasons),
            alert=alert,
            recommended_action=action
        )

    @classmethod
    def classify_sequence(cls, readings: List[Dict], window_hours: float = 24.0) -> 'PhaseResult':
        """
        Classify phase from a sequence of readings (more robust than single snapshot).

        Args:
            readings: List of dicts with 'co2', 'timestamp', optionally 'temp', 'humidity'
            window_hours: Time window for trend analysis

        Returns:
            PhaseResult with phase, confidence, reasoning
        """
        if not readings:
            return PhaseResult("unknown", 0.0, "No readings provided")

        co2_values = [float(r["co2"]) for r in readings if r.get("co2") is not None]
        if not co2_values:
            return PhaseResult("unknown", 0.0, "No CO2 readings in sequence")

        # Statistics
        co2_mean = sum(co2_values) / len(co2_values)
        co2_min = min(co2_values)
        co2_max = max(co2_values)
        co2_spread = co2_max - co2_min
        n = len(co2_values)

        # Trend (last vs first)
        if n >= 2:
            first_half = co2_values[:n//2]
            second_half = co2_values[n//2:]
            first_mean = sum(first_half) / len(first_half)
            second_mean = sum(second_half) / len(second_half)
            trend_delta = second_mean - first_mean
            trend_pct = (trend_delta / first_mean * 100) if first_mean > 0 else 0

            if trend_delta > 100:
                trend = "rising"
            elif trend_delta < -100:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"
            trend_pct = 0

        # Get latest reading for boundary check
        latest = None
        for r in reversed(readings):
            if r.get("co2") is not None:
                latest = r
                break

        if latest:
            snapshot = cls.classify_snapshot(
                latest.get("co2"),
                latest.get("temp"),
                latest.get("humidity")
            )
            base_phase = snapshot.phase
        else:
            base_phase = "unknown"

        # Sequence-informed overrides
        phase = base_phase
        confidence = snapshot.confidence if latest else 0.5
        reasons = [f"Sequence: mean={co2_mean:.0f}ppm, spread={co2_spread:.0f}, trend={trend}({trend_pct:+.1f}%)"]

        # Override rules based on sequence characteristics
        if co2_mean > cls.COLONIZATION_THRESHOLD:
            phase = "colonization"
            confidence = max(confidence, 0.85)
            reasons.append("Mean CO2 confirms colonization across entire sequence")
        elif co2_spread > 400 and cls.PRIMORDIA_LOWER < co2_mean < cls.PRIMORDIA_UPPER:
            phase = "primordia"
            confidence = 0.70
            reasons.append(f"High spread ({co2_spread:.0f} ppm) in transition zone = active primordia")
        elif co2_mean < cls.FRUITING_THRESHOLD and trend in ("stable", "falling"):
            phase = "fruiting"
            confidence = max(confidence, 0.80)
            reasons.append("Low and stable CO2 confirms fruiting")

        alert = snapshot.alert if latest else False
        action = snapshot.recommended_action if latest else ""

        return PhaseResult(
            phase=phase,
            confidence=round(confidence, 2),
            reasoning="; ".join(reasons),
            alert=alert,
            recommended_action=action
        )


# Convenience function for CLI/scripts
def detect_phase(co2: float, temp: Optional[float] = None, humidity: Optional[float] = None,
                 readings: Optional[List[Dict]] = None) -> PhaseResult:
    """Main entry point — auto-detects whether to use snapshot or sequence classification."""
    if readings is not None and len(readings) > 1:
        return PhaseDetector.classify_sequence(readings)
    return PhaseDetector.classify_snapshot(co2, temp, humidity)


# Script execution
if __name__ == "__main__":
    import argparse, json
    parser = argparse.ArgumentParser(description="Detect cultivation phase from sensor data")
    parser.add_argument("--co2", type=float, required=True, help="CO2 reading in ppm")
    parser.add_argument("--temp", type=float, help="Temperature in C")
    parser.add_argument("--humidity", type=float, help="Relative humidity in %")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    result = detect_phase(args.co2, args.temp, args.humidity)

    if args.json:
        print(json.dumps({
            "phase": result.phase,
            "confidence": result.confidence,
            "reasoning": result.reasoning,
            "alert": result.alert,
            "recommended_action": result.recommended_action
        }, indent=2))
    else:
        print(f"Phase: {result.phase.upper()} (confidence: {result.confidence})")
        print(f"Reasoning: {result.reasoning}")
        if result.alert:
            print(f"ALERT: {result.recommended_action}")
