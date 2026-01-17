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

# Unit configuration - fetched from Nightscout settings
_cached_units = None

def get_nightscout_units():
    """Fetch the display units from Nightscout server settings."""
    global _cached_units
    if _cached_units is not None:
        return _cached_units
    
    try:
        resp = requests.get(f"{API_ROOT}/status.json", timeout=10)
        resp.raise_for_status()
        settings = resp.json().get("settings", {})
        units = settings.get("units", "mg/dl")
        _cached_units = units.lower().startswith("mmol")
    except Exception:
        _cached_units = False  # Default to mg/dL on error
    
    return _cached_units

def convert_glucose(value_mgdl):
    """Convert mg/dL to mmol/L if Nightscout is configured for mmol."""
    if get_nightscout_units():
        return round(value_mgdl / 18.0182, 1)
    return value_mgdl

def get_unit_label():
    """Get the appropriate unit label based on Nightscout settings."""
    return "mmol/L" if get_nightscout_units() else "mg/dL"
SKILL_DIR = Path(__file__).parent.parent
DB_PATH = SKILL_DIR / "cgm_data.db"

# Glucose ranges (mg/dL)
VERY_LOW = 54
LOW = 70
TARGET_LOW = 70
TARGET_HIGH = 180
HIGH = 250


def create_database():
    """Initialize SQLite database for storing CGM readings."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS readings (
        id TEXT PRIMARY KEY,
        sgv INTEGER,
        date_ms INTEGER,
        date_string TEXT,
        trend INTEGER,
        direction TEXT,
        device TEXT
    )''')
    conn.commit()
    return conn


def fetch_and_store(days=90):
    """Fetch CGM data from Nightscout and store in database."""
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
        except requests.RequestException as e:
            return {"error": f"Failed to fetch data: {e}"}

        if not entries:
            break

        for e in entries:
            if e.get("type") == "sgv":
                cursor = conn.execute(
                    "SELECT 1 FROM readings WHERE id = ?", (e.get("_id"),)
                )
                if not cursor.fetchone():
                    conn.execute(
                        '''INSERT INTO readings VALUES (?,?,?,?,?,?,?)''',
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

    conn.close()
    
    total_readings = sqlite3.connect(DB_PATH).execute(
        "SELECT COUNT(*) FROM readings"
    ).fetchone()[0]
    
    return {
        "status": "success",
        "new_readings": total_new,
        "total_readings": total_readings,
        "database": str(DB_PATH)
    }


def get_stats(values):
    """Calculate basic statistics for glucose values."""
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
        "unit": get_unit_label()
    }


def get_time_in_range(values):
    """Calculate time-in-range percentages."""
    if not values:
        return {}
    n = len(values)
    return {
        "very_low_pct": round(sum(1 for v in values if v < VERY_LOW) / n * 100, 1),
        "low_pct": round(sum(1 for v in values if VERY_LOW <= v < LOW) / n * 100, 1),
        "in_range_pct": round(sum(1 for v in values if TARGET_LOW <= v <= TARGET_HIGH) / n * 100, 1),
        "high_pct": round(sum(1 for v in values if TARGET_HIGH < v <= HIGH) / n * 100, 1),
        "very_high_pct": round(sum(1 for v in values if v > HIGH) / n * 100, 1),
    }


def analyze_cgm(days=90):
    """Analyze CGM data from database."""
    if not DB_PATH.exists():
        return {"error": "No database found. Run 'refresh' command first."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found for the specified period. Run 'refresh' command first."}

    values = [r[0] for r in rows]
    stats = get_stats(values)
    tir = get_time_in_range(values)

    # GMI (Glucose Management Indicator) - estimated A1C
    gmi = round(3.31 + (0.02392 * stats["mean"]), 1)
    
    # Coefficient of Variation
    cv = round((stats["std"] / stats["mean"]) * 100, 1) if stats["mean"] else 0

    # Hourly breakdown
    hourly = defaultdict(list)
    for sgv, _, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            hourly[dt.hour].append(sgv)
        except (ValueError, TypeError):
            pass

    hourly_avg = {h: convert_glucose(round(sum(v) / len(v), 0)) for h, v in sorted(hourly.items())}

    return {
        "date_range": {
            "from": rows[0][2][:10] if rows[0][2] else "unknown",
            "to": rows[-1][2][:10] if rows[-1][2] else "unknown",
            "days_analyzed": days
        },
        "readings": len(values),
        "statistics": stats,
        "time_in_range": tir,
        "gmi_estimated_a1c": gmi,
        "cv_variability": cv,
        "cv_status": "stable" if cv < 36 else "high variability",
        "hourly_averages": hourly_avg,
        "unit": get_unit_label()
    }


def get_current_glucose():
    """Get the most recent glucose reading from Nightscout."""
    try:
        resp = requests.get(API_BASE, params={"count": 1}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        return {"error": f"Failed to fetch current glucose: {e}"}

    if data:
        e = data[0]
        sgv = e.get("sgv", 0)
        
        if sgv < VERY_LOW:
            status = "VERY LOW - urgent"
        elif sgv < LOW:
            status = "low"
        elif sgv <= TARGET_HIGH:
            status = "in range"
        elif sgv <= HIGH:
            status = "high"
        else:
            status = "VERY HIGH"

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
