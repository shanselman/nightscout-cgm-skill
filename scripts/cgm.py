#!/usr/bin/env python3
"""
Nightscout CGM data fetcher and analyzer.
Usage: python cgm.py <command> [options]

Commands:
  current              Get the latest glucose reading
  analyze [--days N]   Analyze CGM data (default: 90 days)
  refresh [--days N]   Fetch latest data from Nightscout and update local database
"""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

# Configuration - Set NIGHTSCOUT_URL environment variable to your Nightscout API endpoint
API_BASE = os.environ.get("NIGHTSCOUT_URL")
if not API_BASE:
    print("Error: NIGHTSCOUT_URL environment variable not set.")
    print("Set it to your Nightscout API endpoint, e.g.:")
    print("  export NIGHTSCOUT_URL='https://your-site.herokuapp.com/api/v1/entries.json'")
    sys.exit(1)

# Derive the API root from the entries URL
API_ROOT = API_BASE.replace("/entries.json", "").rstrip("/")

# Nightscout settings cache
_cached_settings = None

# Constants for glucose thresholds and calculations
DEFAULT_URGENT_LOW = 55
DEFAULT_LOW = 70
DEFAULT_TARGET_LOW = 70
DEFAULT_TARGET_HIGH = 180
DEFAULT_HIGH = 250
CV_STABLE_THRESHOLD = 36
MGDL_TO_MMOL_FACTOR = 18.0182

# SQL queries
SQL_CREATE_READINGS_TABLE = '''CREATE TABLE IF NOT EXISTS readings (
    id TEXT PRIMARY KEY,
    sgv INTEGER,
    date_ms INTEGER,
    date_string TEXT,
    trend INTEGER,
    direction TEXT,
    device TEXT
)'''
SQL_CHECK_READING_EXISTS = "SELECT 1 FROM readings WHERE id = ?"
SQL_INSERT_READING = "INSERT INTO readings VALUES (?,?,?,?,?,?,?)"
SQL_COUNT_READINGS = "SELECT COUNT(*) FROM readings"
SQL_SELECT_READINGS_BY_DATE = "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms"

def get_nightscout_settings():
    """Fetch settings from Nightscout server (cached).
    
    Returns:
        Dictionary of Nightscout settings, or empty dict on error
    """
    global _cached_settings
    if _cached_settings is not None:
        return _cached_settings
    
    try:
        resp = requests.get(f"{API_ROOT}/status.json", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        _cached_settings = data.get("settings", {})
    except (requests.RequestException, ValueError, KeyError):
        # ValueError for JSON decode errors, KeyError for missing keys
        _cached_settings = {}
    
    return _cached_settings

def use_mmol():
    """Check if Nightscout is configured for mmol/L.
    
    Returns:
        True if units are mmol/L, False if mg/dL
    """
    units = get_nightscout_settings().get("units", "mg/dl")
    return units.lower().startswith("mmol")

def convert_glucose(value_mgdl):
    """Convert mg/dL to mmol/L if Nightscout is configured for mmol.
    
    Args:
        value_mgdl: Glucose value in mg/dL
    
    Returns:
        Glucose value in the configured units (mg/dL or mmol/L)
    """
    if use_mmol():
        return round(value_mgdl / MGDL_TO_MMOL_FACTOR, 1)
    return value_mgdl

def get_unit_label():
    """Get the appropriate unit label based on Nightscout settings.
    
    Returns:
        "mmol/L" or "mg/dL" based on Nightscout configuration
    """
    return "mmol/L" if use_mmol() else "mg/dL"

def get_thresholds():
    """Get glucose thresholds from Nightscout settings (in mg/dL).
    
    Returns:
        Dictionary with threshold values: urgent_low, low, target_low, 
        target_high, and high (all in mg/dL)
    """
    thresholds = get_nightscout_settings().get("thresholds", {})
    return {
        "urgent_low": thresholds.get("bgLow", DEFAULT_URGENT_LOW),
        "low": DEFAULT_LOW,  # Standard low threshold
        "target_low": thresholds.get("bgTargetBottom", DEFAULT_TARGET_LOW),
        "target_high": thresholds.get("bgTargetTop", DEFAULT_TARGET_HIGH),
        "high": thresholds.get("bgHigh", DEFAULT_HIGH),
    }
SKILL_DIR = Path(__file__).parent.parent
DB_PATH = SKILL_DIR / "cgm_data.db"


def create_database():
    """Initialize SQLite database for storing CGM readings.
    
    Returns:
        Database connection object
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute(SQL_CREATE_READINGS_TABLE)
    conn.commit()
    return conn


def fetch_and_store(days=90):
    """Fetch CGM data from Nightscout and store in database.
    
    Args:
        days: Number of days of historical data to fetch (default: 90)
    
    Returns:
        Dictionary with status, new readings count, total readings, and database path,
        or error dict if fetching fails
    """
    conn = create_database()
    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    total_new = 0
    oldest_date = None

    while True:
        params = {"count": 10000}
        if oldest_date:
            params["find[date][$lte]"] = oldest_date

        try:
            resp = requests.get(API_BASE, params=params, timeout=30)
            resp.raise_for_status()
            entries = resp.json()
        except (requests.RequestException, ValueError) as e:
            # ValueError for JSON decode errors
            conn.close()
            return {"error": f"Failed to fetch data: {e}"}

        if not entries:
            break

        for e in entries:
            if e.get("type") == "sgv":
                cursor = conn.execute(
                    SQL_CHECK_READING_EXISTS, (e.get("_id"),)
                )
                if not cursor.fetchone():
                    conn.execute(
                        SQL_INSERT_READING,
                        (e.get("_id"), e.get("sgv"), e.get("date"),
                         e.get("dateString"), e.get("trend"),
                         e.get("direction"), e.get("device"))
                    )
                    total_new += 1
        conn.commit()

        oldest = min(e.get("date", float("inf")) for e in entries)
        if oldest < cutoff_ms:
            break
        oldest_date = oldest - 1

    total_readings = conn.execute(
        SQL_COUNT_READINGS
    ).fetchone()[0]
    conn.close()
    
    return {
        "status": "success",
        "new_readings": total_new,
        "total_readings": total_readings,
        "database": str(DB_PATH)
    }


def get_stats(values):
    """Calculate basic statistics for glucose values.
    
    Args:
        values: List of glucose values in mg/dL
    
    Returns:
        Dictionary with count, mean, std, min, max, median (in configured units),
        unit label, and raw mean/std (in mg/dL for further calculations)
    """
    if not values:
        return {}
    values = sorted(values)
    n = len(values)
    mean = sum(values) / n
    std = (sum((x - mean) ** 2 for x in values) / n) ** 0.5
    return {
        "count": n,
        "mean": convert_glucose(round(mean, 1)),
        "std": convert_glucose(round(std, 1)),
        "min": convert_glucose(values[0]),
        "max": convert_glucose(values[-1]),
        "median": convert_glucose(values[n // 2]),
        "unit": get_unit_label(),
        "raw_mean": mean,  # Keep raw mean for GMI calculation
        "raw_std": std     # Keep raw std for CV calculation
    }


def get_time_in_range(values):
    """Calculate time-in-range percentages using Nightscout thresholds.
    
    Args:
        values: List of glucose values in mg/dL
    
    Returns:
        Dictionary with percentages for each glucose range category
    """
    if not values:
        return {}
    t = get_thresholds()
    n = len(values)
    return {
        "very_low_pct": round(sum(1 for v in values if v < t["urgent_low"]) / n * 100, 1),
        "low_pct": round(sum(1 for v in values if t["urgent_low"] <= v < t["target_low"]) / n * 100, 1),
        "in_range_pct": round(sum(1 for v in values if t["target_low"] <= v <= t["target_high"]) / n * 100, 1),
        "high_pct": round(sum(1 for v in values if t["target_high"] < v <= t["high"]) / n * 100, 1),
        "very_high_pct": round(sum(1 for v in values if v > t["high"]) / n * 100, 1),
    }


def get_glucose_status(glucose_value):
    """Determine glucose status based on thresholds.
    
    Args:
        glucose_value: Glucose value in mg/dL
    
    Returns:
        Status string describing the glucose level
    """
    t = get_thresholds()
    
    if glucose_value < t["urgent_low"]:
        return "VERY LOW - urgent"
    elif glucose_value < t["target_low"]:
        return "low"
    elif glucose_value <= t["target_high"]:
        return "in range"
    elif glucose_value <= t["high"]:
        return "high"
    else:
        return "VERY HIGH"


def analyze_cgm(days=90):
    """Analyze CGM data from database.
    
    Args:
        days: Number of days to analyze (default: 90)
    
    Returns:
        Dictionary containing analysis results including statistics, time in range,
        GMI, CV, and hourly averages, or error dict if data is not available
    """
    if not DB_PATH.exists():
        return {"error": "No database found. Run 'refresh' command first."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        SQL_SELECT_READINGS_BY_DATE,
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found for the specified period. Run 'refresh' command first."}

    values = [r[0] for r in rows]
    stats = get_stats(values)
    tir = get_time_in_range(values)

    # GMI (Glucose Management Indicator) - estimated A1C
    # Uses raw mg/dL mean from stats
    raw_mean = stats.get("raw_mean", 0)
    gmi = round(3.31 + (0.02392 * raw_mean), 1)
    
    # Coefficient of Variation (uses raw values from stats)
    raw_std = stats.get("raw_std", 0)
    cv = round((raw_std / raw_mean) * 100, 1) if raw_mean else 0

    # Hourly breakdown
    hourly = defaultdict(list)
    for sgv, _, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            hourly[dt.hour].append(sgv)
        except (ValueError, TypeError):
            pass

    hourly_avg = {h: convert_glucose(round(sum(v) / len(v), 0)) for h, v in sorted(hourly.items())}

    # Remove raw values from stats before returning
    stats_output = {k: v for k, v in stats.items() if k not in ("raw_mean", "raw_std")}

    return {
        "date_range": {
            "from": rows[0][2][:10] if rows[0][2] else "unknown",
            "to": rows[-1][2][:10] if rows[-1][2] else "unknown",
            "days_analyzed": days
        },
        "readings": len(values),
        "statistics": stats_output,
        "time_in_range": tir,
        "gmi_estimated_a1c": gmi,
        "cv_variability": cv,
        "cv_status": "stable" if cv < CV_STABLE_THRESHOLD else "high variability",
        "hourly_averages": hourly_avg,
        "unit": get_unit_label()
    }


def get_current_glucose():
    """Get the most recent glucose reading from Nightscout.
    
    Returns:
        Dictionary with current glucose value, unit, trend, timestamp, and status,
        or error dict if fetching fails
    """
    try:
        resp = requests.get(API_BASE, params={"count": 1}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        # ValueError for JSON decode errors
        return {"error": f"Failed to fetch current glucose: {e}"}

    if data:
        e = data[0]
        sgv = e.get("sgv", 0)
        status = get_glucose_status(sgv)

        return {
            "glucose": convert_glucose(sgv),
            "unit": get_unit_label(),
            "trend": e.get("direction"),
            "timestamp": e.get("dateString"),
            "status": status
        }
    return {"error": "No data available"}


def main():
    parser = argparse.ArgumentParser(
        description="Nightscout CGM data fetcher and analyzer"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Current glucose command
    subparsers.add_parser("current", help="Get the latest glucose reading")

    # Analyze command
    analyze_parser = subparsers.add_parser("analyze", help="Analyze CGM data")
    analyze_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to analyze (default: 90)"
    )

    # Refresh command
    refresh_parser = subparsers.add_parser(
        "refresh", help="Fetch latest data from Nightscout"
    )
    refresh_parser.add_argument(
        "--days", type=int, default=90,
        help="Days of data to fetch (default: 90)"
    )

    args = parser.parse_args()

    if args.command == "current":
        result = get_current_glucose()
    elif args.command == "analyze":
        result = analyze_cgm(args.days)
    elif args.command == "refresh":
        result = fetch_and_store(args.days)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
