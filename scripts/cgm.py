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
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests library required. Install with: pip install requests")
    sys.exit(1)

# Configuration - Set NIGHTSCOUT_URL environment variable to your Nightscout API endpoint
_raw_url = os.environ.get("NIGHTSCOUT_URL")
if not _raw_url:
    print("Error: NIGHTSCOUT_URL environment variable not set.")
    print("Set it to your Nightscout site URL, e.g.:")
    print("  export NIGHTSCOUT_URL='https://your-site.herokuapp.com'")
    print("Or the full API endpoint:")
    print("  export NIGHTSCOUT_URL='https://your-site.herokuapp.com/api/v1/entries.json'")
    sys.exit(1)

# Normalize the URL - support both full endpoint and just the domain
def _normalize_nightscout_url(url):
    """Normalize NIGHTSCOUT_URL to always point to /api/v1/entries.json"""
    url = url.rstrip("/")
    if url.endswith("/api/v1/entries.json"):
        return url
    if url.endswith("/api/v1/entries"):
        return url + ".json"
    if url.endswith("/api/v1"):
        return url + "/entries.json"
    if url.endswith("/api"):
        return url + "/v1/entries.json"
    # Just the domain
    return url + "/api/v1/entries.json"

API_BASE = _normalize_nightscout_url(_raw_url)

# Derive the API root from the entries URL
API_ROOT = API_BASE.replace("/entries.json", "").rstrip("/")

# Nightscout settings cache
_cached_settings = None

def get_nightscout_settings():
    """Fetch settings from Nightscout server (cached)."""
    global _cached_settings
    if _cached_settings is not None:
        return _cached_settings
    
    try:
        resp = requests.get(f"{API_ROOT}/status.json", timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            _cached_settings = data.get("settings", {})
        else:
            _cached_settings = {}
    except (requests.RequestException, ValueError):
        _cached_settings = {}
    
    return _cached_settings

def use_mmol():
    """Check if Nightscout is configured for mmol/L."""
    units = get_nightscout_settings().get("units", "mg/dl")
    return units.lower().startswith("mmol")

def convert_glucose(value_mgdl):
    """Convert mg/dL to mmol/L if Nightscout is configured for mmol."""
    if use_mmol():
        return round(value_mgdl / 18.0182, 1)
    return value_mgdl

def get_unit_label():
    """Get the appropriate unit label based on Nightscout settings."""
    return "mmol/L" if use_mmol() else "mg/dL"

def get_thresholds():
    """Get glucose thresholds from Nightscout settings (in mg/dL)."""
    thresholds = get_nightscout_settings().get("thresholds", {})
    return {
        "urgent_low": thresholds.get("bgLow", 55),
        "target_low": thresholds.get("bgTargetBottom", 70),
        "target_high": thresholds.get("bgTargetTop", 180),
        "urgent_high": thresholds.get("bgHigh", 250),
    }

SKILL_DIR = Path(__file__).parent.parent
DB_PATH = SKILL_DIR / "cgm_data.db"

# Trend alert detection thresholds
HIGH_SEVERITY_DAY_THRESHOLD = 3  # Number of unique days to trigger high severity
SIGNIFICANT_TIR_CHANGE = 5  # Percentage change in TIR to be considered significant
OVERNIGHT_START_HOUR = 22  # Hour when overnight period begins
OVERNIGHT_END_HOUR = 6  # Hour when overnight period ends


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


def ensure_data(days=90):
    """
    Ensure we have data in the database. Auto-fetches on first use.
    Returns True if data is available, False if fetch failed.
    """
    if DB_PATH.exists():
        # Check if we actually have readings
        conn = sqlite3.connect(DB_PATH)
        count = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
        conn.close()
        if count > 0:
            return True
    
    # No data - auto-fetch
    print("No local data found. Fetching from Nightscout (this may take a moment)...")
    result = fetch_and_store(days)
    if "error" in result:
        print(f"Error: {result['error']}")
        return False
    print(f"Fetched {result['new_readings']} readings. Total: {result['total_readings']}\n")
    return True


def fetch_and_store(days=90):
    """Fetch CGM data from Nightscout and store in database."""
    conn = create_database()
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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

    # Get total count before closing connection
    total_readings = conn.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
    conn.close()
    
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
    """Calculate time-in-range percentages using Nightscout thresholds."""
    if not values:
        return {}
    t = get_thresholds()
    n = len(values)
    return {
        "very_low_pct": round(sum(1 for v in values if v < t["urgent_low"]) / n * 100, 1),
        "low_pct": round(sum(1 for v in values if t["urgent_low"] <= v < t["target_low"]) / n * 100, 1),
        "in_range_pct": round(sum(1 for v in values if t["target_low"] <= v <= t["target_high"]) / n * 100, 1),
        "high_pct": round(sum(1 for v in values if t["target_high"] < v <= t["urgent_high"]) / n * 100, 1),
        "very_high_pct": round(sum(1 for v in values if v > t["urgent_high"]) / n * 100, 1),
    }


def analyze_cgm(days=90):
    """Analyze CGM data from database."""
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found for the specified period."}

    values = [r[0] for r in rows]
    stats = get_stats(values)
    tir = get_time_in_range(values)

    # GMI (Glucose Management Indicator) - estimated A1C
    # Uses raw mg/dL mean, not converted value
    raw_mean = sum(values) / len(values)
    gmi = round(3.31 + (0.02392 * raw_mean), 1)
    
    # Coefficient of Variation (uses raw values)
    raw_std = (sum((x - raw_mean) ** 2 for x in values) / len(values)) ** 0.5
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
        t = get_thresholds()
        
        if sgv < t["urgent_low"]:
            status = "VERY LOW - urgent"
        elif sgv < t["target_low"]:
            status = "low"
        elif sgv <= t["target_high"]:
            status = "in range"
        elif sgv <= t["urgent_high"]:
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


def make_sparkline(values, min_val=40, max_val=400):
    """
    Create a sparkline string from a list of glucose values.
    Uses Unicode block characters: ▁▂▃▄▅▆▇█
    """
    if not values:
        return ""
    
    blocks = " ▁▂▃▄▅▆▇█"
    
    sparkline = []
    for v in values:
        # Clamp value to range
        v = max(min_val, min(max_val, v))
        # Normalize to 0-8 range (9 characters including space)
        normalized = (v - min_val) / (max_val - min_val)
        idx = int(normalized * 8)
        idx = max(0, min(8, idx))
        sparkline.append(blocks[idx])
    
    return "".join(sparkline)


def show_sparkline(hours=24, use_color=True, date_str=None, hour_start=None, hour_end=None):
    """
    Display a sparkline of glucose readings.
    If date_str is provided, shows that specific date (with optional hour range).
    Otherwise shows the last N hours from now.
    """
    if not ensure_data():
        return
    
    conn = sqlite3.connect(DB_PATH)
    
    if date_str:
        # Specific date mode
        try:
            target_date = parse_date_arg(date_str)
        except ValueError as e:
            print(f"Error: {e}")
            return
        
        query = """
        SELECT sgv, date_string FROM readings 
        WHERE date(datetime(date_ms/1000, 'unixepoch', 'localtime')) = ?
          AND sgv > 0
        """
        params = [target_date.isoformat()]
        
        if hour_start is not None and hour_end is not None:
            query += """ AND CAST(strftime('%H', datetime(date_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) 
                         BETWEEN ? AND ?"""
            params.extend([hour_start, hour_end])
        
        query += " ORDER BY date_ms"
        rows = conn.execute(query, params).fetchall()
        
        # Build title
        if hour_start is not None:
            title = f"{target_date.strftime('%b %d')} {hour_start}:00-{hour_end}:59"
        else:
            title = target_date.strftime('%b %d')
    else:
        # Recent hours mode (original behavior)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cutoff_ms = int(cutoff.timestamp() * 1000)
        
        rows = conn.execute(
            "SELECT sgv, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
            (cutoff_ms,)
        ).fetchall()
        title = f"{hours}h"
    
    conn.close()
    
    if not rows:
        print("No data found for the requested period.")
        return
    
    values = [r[0] for r in rows]
    t = get_thresholds()
    
    # Calculate stats
    avg = sum(values) / len(values)
    min_v = min(values)
    max_v = max(values)
    in_range = sum(1 for v in values if t["target_low"] <= v <= t["target_high"])
    tir = (in_range / len(values)) * 100
    
    # Get time range (convert to local time for display)
    try:
        first_dt = datetime.fromisoformat(rows[0][1].replace("Z", "+00:00")).astimezone()
        last_dt = datetime.fromisoformat(rows[-1][1].replace("Z", "+00:00")).astimezone()
    except (ValueError, TypeError):
        print("Error: Invalid date format in database. Try running 'refresh' command.")
        return
    
    # Create colored sparkline if requested
    if use_color:
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        RESET = '\033[0m'
        BOLD = '\033[1m'
        
        blocks = " ▁▂▃▄▅▆▇█"
        sparkline = []
        for v in values:
            # Determine color based on range
            if v < t["urgent_low"]:
                color = RED  # Urgent low
            elif v < t["target_low"]:
                color = YELLOW  # Low
            elif v <= t["target_high"]:
                color = GREEN  # In range
            elif v <= t["urgent_high"]:
                color = YELLOW  # High
            else:
                color = RED  # Urgent high
            
            # Normalize to block character
            clamped = max(40, min(400, v))
            normalized = (clamped - 40) / 360
            idx = int(normalized * 8)
            idx = max(0, min(8, idx))
            sparkline.append(f"{color}{blocks[idx]}{RESET}")
        
        spark_str = "".join(sparkline)
        print(f"\n{BOLD}Glucose Sparkline ({title}){RESET}")
        print(f"  {first_dt.strftime('%H:%M')} {spark_str} {last_dt.strftime('%H:%M')}")
        print(f"\n  {GREEN}█{RESET} In Range ({convert_glucose(t['target_low'])}-{convert_glucose(t['target_high'])} {get_unit_label()})  {YELLOW}█{RESET} Low/High  {RED}█{RESET} Urgent")
    else:
        # ASCII mode - no colors
        spark_str = make_sparkline(values)
        print(f"\nGlucose Sparkline ({title})")
        print(f"  {first_dt.strftime('%H:%M')} {spark_str} {last_dt.strftime('%H:%M')}")
        print(f"\n  Target: {convert_glucose(t['target_low'])}-{convert_glucose(t['target_high'])} {get_unit_label()}")
    
    # Format average with proper precision
    avg_display = convert_glucose(avg)
    if use_mmol():
        avg_str = f"{avg_display:.1f}"
    else:
        avg_str = f"{avg_display:.0f}"
    
    print(f"\n  Readings: {len(values)} | Avg: {avg_str} {get_unit_label()} | Range: {convert_glucose(min_v)}-{convert_glucose(max_v)} | TIR: {tir:.0f}%")
    print()


def show_sparkline_week(days=7, use_color=True):
    """
    Display sparklines for each day, one line per day.
    Each line shows 24 hours of data, sampled to ~48 points to fit terminal width.
    """
    if not ensure_data(days):
        return
    
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    
    rows = conn.execute(
        "SELECT sgv, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()
    
    if not rows:
        print("No data found for the requested period.")
        return
    
    t = get_thresholds()
    
    # Group readings by date
    by_date = defaultdict(list)
    for sgv, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            date_key = dt.strftime("%Y-%m-%d")
            by_date[date_key].append((dt.hour + dt.minute/60, sgv))
        except (ValueError, TypeError):
            pass
    
    if use_color:
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        RESET = '\033[0m'
        BOLD = '\033[1m'
        DIM = '\033[2m'
    else:
        GREEN = YELLOW = RED = RESET = BOLD = DIM = ''
    
    blocks = " ▁▂▃▄▅▆▇█"
    
    print(f"\n{BOLD}Glucose Sparklines (Last {days} Days){RESET}")
    print(f"  {DIM}midnight                  noon                  midnight{RESET}")
    print(f"  {DIM}|                         |                         |{RESET}")
    
    # Sort dates and show most recent at top
    sorted_dates = sorted(by_date.keys(), reverse=True)
    
    for date_str in sorted_dates[:days]:
        readings = by_date[date_str]
        if not readings:
            continue
        
        # Create 48 buckets (30-min intervals)
        buckets = [[] for _ in range(48)]
        for hour_frac, sgv in readings:
            bucket_idx = int(hour_frac * 2)  # 2 buckets per hour
            bucket_idx = max(0, min(47, bucket_idx))
            buckets[bucket_idx].append(sgv)
        
        # Build sparkline
        sparkline = []
        for bucket in buckets:
            if not bucket:
                sparkline.append(f"{DIM}·{RESET}" if use_color else "·")
            else:
                avg_sgv = sum(bucket) / len(bucket)
                
                # Color based on range
                if use_color:
                    if avg_sgv < t["urgent_low"]:
                        color = RED
                    elif avg_sgv < t["target_low"]:
                        color = YELLOW
                    elif avg_sgv <= t["target_high"]:
                        color = GREEN
                    elif avg_sgv <= t["urgent_high"]:
                        color = YELLOW
                    else:
                        color = RED
                else:
                    color = ''
                
                # Normalize to block character
                clamped = max(40, min(400, avg_sgv))
                normalized = (clamped - 40) / 360
                idx = int(normalized * 8)
                idx = max(0, min(8, idx))
                sparkline.append(f"{color}{blocks[idx]}{RESET}" if use_color else blocks[idx])
        
        spark_str = "".join(sparkline)
        
        # Calculate day stats
        day_values = [r[1] for r in readings]
        avg = sum(day_values) / len(day_values)
        in_range = sum(1 for v in day_values if t["target_low"] <= v <= t["target_high"])
        tir = (in_range / len(day_values)) * 100
        
        # Parse date for display
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = dt.strftime("%a")
        date_display = dt.strftime("%m/%d")
        
        # TIR color
        if tir >= 80:
            tir_color = GREEN
        elif tir >= 70:
            tir_color = YELLOW
        else:
            tir_color = RED
        
        print(f"  {day_name} {date_display} {spark_str} {tir_color}{tir:3.0f}%{RESET} avg:{convert_glucose(avg):.0f}")
    
    print(f"\n  {GREEN}█{RESET} In Range  {YELLOW}█{RESET} Low/High  {RED}█{RESET} Urgent  {DIM}·{RESET} No data")
    print(f"  Target: {convert_glucose(t['target_low'])}-{convert_glucose(t['target_high'])} {get_unit_label()}")
    print()


def show_heatmap(days=90, use_color=True):
    """Display a terminal heatmap of time-in-range by day and hour."""
    if not ensure_data(days):
        return

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_string FROM readings WHERE date_ms >= ? AND sgv > 0",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    by_day_hour = defaultdict(list)
    for sgv, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            by_day_hour[(dt.weekday(), dt.hour)].append(sgv)
        except (ValueError, TypeError):
            pass

    days_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    t = get_thresholds()

    if use_color:
        # ANSI colors for direct terminal use
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        ORANGE = '\033[38;5;208m'
        RED = '\033[91m'
        RESET = '\033[0m'
        BOLD = '\033[1m'

        def tir_block(values):
            if not values:
                return ' '
            tir = sum(1 for v in values if t["target_low"] <= v <= t["target_high"]) / len(values) * 100
            if tir >= 90:
                return f'{GREEN}█{RESET}'
            if tir >= 80:
                return f'{YELLOW}█{RESET}'
            if tir >= 70:
                return f'{ORANGE}█{RESET}'
            return f'{RED}█{RESET}'

        print()
        print(f'  {BOLD}Time-in-Range Heatmap ({days} days){RESET}')
        print(f'  {GREEN}█{RESET} >90%  {YELLOW}█{RESET} 80-90%  {ORANGE}█{RESET} 70-80%  {RED}█{RESET} <70%')
        print()
        print('       0  2  4  6  8 10 12 14 16 18 20 22')
        print('      ' + '─' * 48)

        for d in range(7):
            row = ''
            for h in range(24):
                row += tir_block(by_day_hour.get((d, h), [])) + ' '
            print(f'  {days_names[d]} │{row}│')

        print('      ' + '─' * 48)
        print('       12am     6am      12pm     6pm      12am')
        print()
    else:
        # ASCII for Copilot/non-color terminals
        def tir_block(values):
            if not values:
                return ' '
            tir = sum(1 for v in values if t["target_low"] <= v <= t["target_high"]) / len(values) * 100
            if tir >= 90:
                return '+'
            if tir >= 80:
                return 'o'
            if tir >= 70:
                return '*'
            return 'X'

        print()
        print(f'  Time-in-Range Heatmap ({days} days)')
        print('  + >90%   o 80-90%   * 70-80%   X <70%')
        print()
        print('       0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3')
        print('       a a a a a a a a a a a a p p p p p p p p p p p p')
        print('      ------------------------------------------------')

        for d in range(7):
            row = ''
            for h in range(24):
                row += tir_block(by_day_hour.get((d, h), [])) + ' '
            print(f'  {days_names[d]} |{row}|')

        print('      ------------------------------------------------')
        print()

        # Show problem spots
        problems = []
        for d in range(7):
            for h in range(24):
                vals = by_day_hour.get((d, h), [])
                if vals:
                    tir = sum(1 for v in vals if t["target_low"] <= v <= t["target_high"]) / len(vals) * 100
                    if tir < 70:
                        problems.append((days_names[d], h, tir))
        
        if problems:
            print('  Problem spots (X = <70% in range):')
            for day, hour, tir in problems:
                print(f'    {day} {hour:02d}:00 - {tir:.0f}% in range')
            print()


def show_day_chart(day_name, days=90, use_color=True):
    """Display a bar chart for a specific day."""
    if not ensure_data(days):
        return

    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    day_idx = day_names.index(day_name.lower()) if day_name.lower() in day_names else None
    if day_idx is None:
        print(f"Invalid day: {day_name}")
        return

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_string FROM readings WHERE date_ms >= ? AND sgv > 0",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    hourly = defaultdict(list)
    for sgv, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            if dt.weekday() == day_idx:
                hourly[dt.hour].append(sgv)
        except (ValueError, TypeError):
            pass

    t = get_thresholds()

    if use_color:
        # ANSI colors for direct terminal use
        GREEN = '\033[92m'
        YELLOW = '\033[93m'
        RED = '\033[91m'
        RESET = '\033[0m'
        BOLD = '\033[1m'

        print()
        print(f'  {BOLD}{day_name.capitalize()} Glucose by Hour ({days} days){RESET}')
        print('  ' + '─' * 50)
        print()

        for h in range(24):
            values = hourly.get(h, [])
            if not values:
                continue
            avg = sum(values) / len(values)
            
            if avg < t["target_low"]:
                color = RED
            elif avg > t["target_high"]:
                color = YELLOW
            else:
                color = GREEN
            
            bar_len = max(0, min(30, int((avg - 50) / 150 * 30)))
            bar = '█' * bar_len
            
            status = '✓' if t["target_low"] <= avg <= t["target_high"] else '!'
            converted = convert_glucose(round(avg))
            print(f'  {h:02d}:00 │{color}{bar:<30}{RESET}│ {converted} {status}')

        print()
        print(f'  Target: {convert_glucose(t["target_low"])}-{convert_glucose(t["target_high"])} {get_unit_label()}')
        print()
    else:
        # ASCII version for Copilot
        print()
        print(f'  {day_name.capitalize()} Glucose by Hour ({days} days)')
        print('  ' + '-' * 50)
        print()

        for h in range(24):
            values = hourly.get(h, [])
            if not values:
                continue
            avg = sum(values) / len(values)
            
            bar_len = max(0, min(30, int((avg - 50) / 150 * 30)))
            bar = '#' * bar_len
            
            if avg < t["target_low"]:
                status = 'LOW'
            elif avg > t["target_high"]:
                status = 'HIGH'
            else:
                status = 'ok'
            
            converted = convert_glucose(round(avg))
            print(f'  {h:02d}:00 |{bar:<30}| {converted} {status}')

        print()
        print(f'  Target: {convert_glucose(t["target_low"])}-{convert_glucose(t["target_high"])} {get_unit_label()}')
        print()


def query_patterns(days=90, day_of_week=None, hour_start=None, hour_end=None):
    """
    Query CGM data with flexible filters for pattern analysis.
    
    Args:
        days: Number of days to analyze
        day_of_week: Filter by day (0=Monday, 6=Sunday, or name like "Tuesday")
        hour_start: Start hour (0-23) for time window
        hour_end: End hour (0-23) for time window
    """
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found for the specified period."}

    # Parse day_of_week if it's a string name
    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    if isinstance(day_of_week, str):
        day_lower = day_of_week.lower()
        if day_lower in day_names:
            day_of_week = day_names.index(day_lower)

    # Filter readings
    filtered = []
    for sgv, date_ms, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            
            # Filter by day of week
            if day_of_week is not None and dt.weekday() != day_of_week:
                continue
            
            # Filter by hour range
            if hour_start is not None and hour_end is not None:
                if hour_start <= hour_end:
                    if not (hour_start <= dt.hour < hour_end):
                        continue
                else:  # Handles overnight ranges like 22-6
                    if not (dt.hour >= hour_start or dt.hour < hour_end):
                        continue
            
            filtered.append((sgv, dt))
        except (ValueError, TypeError):
            pass

    if not filtered:
        return {"error": "No readings match the specified filters."}

    values = [r[0] for r in filtered]
    stats = get_stats(values)
    tir = get_time_in_range(values)

    # Build filter description
    filter_desc = []
    if day_of_week is not None:
        filter_desc.append(f"day={day_names[day_of_week].capitalize()}")
    if hour_start is not None and hour_end is not None:
        filter_desc.append(f"hours={hour_start:02d}:00-{hour_end:02d}:00")

    # Hourly breakdown within filtered data
    hourly = defaultdict(list)
    for sgv, dt in filtered:
        hourly[dt.hour].append(sgv)
    hourly_avg = {h: convert_glucose(round(sum(v) / len(v), 0)) for h, v in sorted(hourly.items())}

    # Day of week breakdown
    daily = defaultdict(list)
    for sgv, dt in filtered:
        daily[day_names[dt.weekday()].capitalize()].append(sgv)
    daily_avg = {d: convert_glucose(round(sum(v) / len(v), 0)) for d, v in daily.items()}

    return {
        "filter": " & ".join(filter_desc) if filter_desc else "none",
        "days_analyzed": days,
        "readings_matched": len(filtered),
        "statistics": stats,
        "time_in_range": tir,
        "hourly_averages": hourly_avg,
        "daily_averages": daily_avg,
        "unit": get_unit_label()
    }


def find_patterns(days=90):
    """
    Automatically find interesting patterns in the data.
    Identifies best/worst times, days, and trends.
    """
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found for the specified period."}

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Collect by hour and day
    by_hour = defaultdict(list)
    by_day = defaultdict(list)
    by_day_hour = defaultdict(list)
    
    t = get_thresholds()
    lows = []
    highs = []
    
    for sgv, date_ms, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            by_hour[dt.hour].append(sgv)
            by_day[dt.weekday()].append(sgv)
            by_day_hour[(dt.weekday(), dt.hour)].append(sgv)
            
            if sgv < t["target_low"]:
                lows.append((sgv, dt))
            elif sgv > t["target_high"]:
                highs.append((sgv, dt))
        except (ValueError, TypeError):
            pass

    # Find best/worst hours
    hour_avgs = {h: sum(v)/len(v) for h, v in by_hour.items()}
    hour_tir = {h: sum(1 for x in v if t["target_low"] <= x <= t["target_high"])/len(v)*100 
                for h, v in by_hour.items()}
    
    best_hour = max(hour_tir, key=hour_tir.get)
    worst_hour = min(hour_tir, key=hour_tir.get)
    
    # Find best/worst days
    day_avgs = {d: sum(v)/len(v) for d, v in by_day.items()}
    day_tir = {d: sum(1 for x in v if t["target_low"] <= x <= t["target_high"])/len(v)*100 
               for d, v in by_day.items()}
    
    best_day = max(day_tir, key=day_tir.get)
    worst_day = min(day_tir, key=day_tir.get)
    
    # Find problematic day+hour combinations
    combo_tir = {}
    for (d, h), values in by_day_hour.items():
        if len(values) >= 10:  # Need enough data
            tir_pct = sum(1 for x in values if t["target_low"] <= x <= t["target_high"])/len(values)*100
            combo_tir[(d, h)] = tir_pct
    
    worst_combos = sorted(combo_tir.items(), key=lambda x: x[1])[:3]
    best_combos = sorted(combo_tir.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Low patterns
    low_hours = defaultdict(int)
    low_days = defaultdict(int)
    for sgv, dt in lows:
        low_hours[dt.hour] += 1
        low_days[dt.weekday()] += 1
    
    return {
        "days_analyzed": days,
        "total_readings": len(rows),
        "insights": {
            "best_time_of_day": {
                "hour": f"{best_hour:02d}:00",
                "time_in_range": round(hour_tir[best_hour], 1),
                "avg_glucose": convert_glucose(round(hour_avgs[best_hour], 0))
            },
            "worst_time_of_day": {
                "hour": f"{worst_hour:02d}:00",
                "time_in_range": round(hour_tir[worst_hour], 1),
                "avg_glucose": convert_glucose(round(hour_avgs[worst_hour], 0))
            },
            "best_day": {
                "day": day_names[best_day],
                "time_in_range": round(day_tir[best_day], 1),
                "avg_glucose": convert_glucose(round(day_avgs[best_day], 0))
            },
            "worst_day": {
                "day": day_names[worst_day],
                "time_in_range": round(day_tir[worst_day], 1),
                "avg_glucose": convert_glucose(round(day_avgs[worst_day], 0))
            },
            "problem_times": [
                {
                    "when": f"{day_names[d]} {h:02d}:00",
                    "time_in_range": round(tir, 1)
                } for (d, h), tir in worst_combos
            ],
            "best_times": [
                {
                    "when": f"{day_names[d]} {h:02d}:00",
                    "time_in_range": round(tir, 1)
                } for (d, h), tir in best_combos
            ],
            "low_events": {
                "total": len(lows),
                "most_common_hour": f"{max(low_hours, key=low_hours.get):02d}:00" if low_hours else "N/A",
                "most_common_day": day_names[max(low_days, key=low_days.get)] if low_days else "N/A"
            }
        },
        "unit": get_unit_label()
    }


def detect_trend_alerts(days=90, min_occurrences=2):
    """
    Detect concerning patterns and trends in CGM data.
    Proactively surfaces issues like recurring lows/highs.
    
    Args:
        days: Number of days to analyze
        min_occurrences: Minimum number of occurrences to trigger an alert (default: 2)
    
    Returns:
        Dictionary with detected alerts categorized by type
    """
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}
    
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    
    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()
    
    if not rows:
        return {"error": "No data found for the specified period."}
    
    t = get_thresholds()
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # Track events by various dimensions
    lows_by_hour = defaultdict(list)
    lows_by_day = defaultdict(list)
    lows_by_day_hour = defaultdict(list)
    highs_by_hour = defaultdict(list)
    highs_by_day = defaultdict(list)
    highs_by_day_hour = defaultdict(list)
    
    # Track weekly patterns (week number for trending)
    lows_by_week = defaultdict(int)
    highs_by_week = defaultdict(int)
    tir_by_week = defaultdict(lambda: {"in_range": 0, "total": 0})
    
    for sgv, date_ms, ds in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            week_num = dt.isocalendar()[1]
            
            # Track time in range by week for trend analysis
            tir_by_week[week_num]["total"] += 1
            if t["target_low"] <= sgv <= t["target_high"]:
                tir_by_week[week_num]["in_range"] += 1
            
            # Track low events
            if sgv < t["target_low"]:
                lows_by_hour[dt.hour].append((sgv, dt))
                lows_by_day[dt.weekday()].append((sgv, dt))
                lows_by_day_hour[(dt.weekday(), dt.hour)].append((sgv, dt))
                lows_by_week[week_num] += 1
            
            # Track high events  
            elif sgv > t["target_high"]:
                highs_by_hour[dt.hour].append((sgv, dt))
                highs_by_day[dt.weekday()].append((sgv, dt))
                highs_by_day_hour[(dt.weekday(), dt.hour)].append((sgv, dt))
                highs_by_week[week_num] += 1
        except (ValueError, TypeError):
            pass
    
    alerts = []
    
    # Detect recurring low patterns by time of day
    for hour, events in lows_by_hour.items():
        if len(events) >= min_occurrences:
            # Count unique days to avoid counting multiple lows on same day
            unique_days = len(set(dt.date() for _, dt in events))
            if unique_days >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                alerts.append({
                    "severity": "high" if unique_days >= HIGH_SEVERITY_DAY_THRESHOLD else "medium",
                    "category": "recurring_lows",
                    "pattern": f"time_of_day",
                    "message": f"You've had {unique_days} lows around {hour:02d}:00 in the last {days} days",
                    "details": {
                        "hour": hour,
                        "occurrences": len(events),
                        "unique_days": unique_days,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Detect recurring low patterns by day of week
    for day, events in lows_by_day.items():
        if len(events) >= min_occurrences:
            unique_weeks = len(set((dt.isocalendar()[0], dt.isocalendar()[1]) for _, dt in events))
            if unique_weeks >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                alerts.append({
                    "severity": "medium",
                    "category": "recurring_lows",
                    "pattern": "day_of_week",
                    "message": f"{day_names[day]}s tend to have lows ({len(events)} events over {unique_weeks} weeks)",
                    "details": {
                        "day": day_names[day],
                        "occurrences": len(events),
                        "unique_weeks": unique_weeks,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Detect recurring high patterns by time of day
    for hour, events in highs_by_hour.items():
        if len(events) >= min_occurrences:
            unique_days = len(set(dt.date() for _, dt in events))
            if unique_days >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                alerts.append({
                    "severity": "medium",
                    "category": "recurring_highs",
                    "pattern": "time_of_day",
                    "message": f"Consistently high around {hour:02d}:00 ({unique_days} days in the last {days} days)",
                    "details": {
                        "hour": hour,
                        "occurrences": len(events),
                        "unique_days": unique_days,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Detect recurring high patterns by day of week
    for day, events in highs_by_day.items():
        if len(events) >= min_occurrences:
            unique_weeks = len(set((dt.isocalendar()[0], dt.isocalendar()[1]) for _, dt in events))
            if unique_weeks >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                alerts.append({
                    "severity": "medium",
                    "category": "recurring_highs",
                    "pattern": "day_of_week",
                    "message": f"{day_names[day]}s are consistently high ({len(events)} events over {unique_weeks} weeks)",
                    "details": {
                        "day": day_names[day],
                        "occurrences": len(events),
                        "unique_weeks": unique_weeks,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Detect specific day+hour combinations (e.g., "Friday lunches are consistently high")
    for (day, hour), events in highs_by_day_hour.items():
        if len(events) >= min_occurrences:
            unique_weeks = len(set((dt.isocalendar()[0], dt.isocalendar()[1]) for _, dt in events))
            if unique_weeks >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                time_label = "lunch" if 11 <= hour <= 14 else "dinner" if 17 <= hour <= 20 else "breakfast" if 6 <= hour <= 9 else f"{hour:02d}:00"
                alerts.append({
                    "severity": "medium",
                    "category": "recurring_highs",
                    "pattern": "day_hour_combination",
                    "message": f"{day_names[day]} {time_label} is consistently high",
                    "details": {
                        "day": day_names[day],
                        "hour": hour,
                        "time_label": time_label,
                        "occurrences": len(events),
                        "unique_weeks": unique_weeks,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Similar for low patterns at specific day+hour
    for (day, hour), events in lows_by_day_hour.items():
        if len(events) >= min_occurrences:
            unique_weeks = len(set((dt.isocalendar()[0], dt.isocalendar()[1]) for _, dt in events))
            if unique_weeks >= min_occurrences:
                avg_glucose = sum(sgv for sgv, _ in events) / len(events)
                time_label = "lunch" if 11 <= hour <= 14 else "dinner" if 17 <= hour <= 20 else "breakfast" if 6 <= hour <= 9 else "overnight" if hour < OVERNIGHT_END_HOUR or hour >= OVERNIGHT_START_HOUR else f"{hour:02d}:00"
                
                # Overnight lows are particularly concerning
                severity = "high" if (hour < OVERNIGHT_END_HOUR or hour >= OVERNIGHT_START_HOUR) else "medium"
                alerts.append({
                    "severity": severity,
                    "category": "recurring_lows",
                    "pattern": "day_hour_combination",
                    "message": f"{day_names[day]} {time_label} has recurring lows",
                    "details": {
                        "day": day_names[day],
                        "hour": hour,
                        "time_label": time_label,
                        "occurrences": len(events),
                        "unique_weeks": unique_weeks,
                        "avg_glucose": convert_glucose(round(avg_glucose, 0)),
                        "unit": get_unit_label()
                    }
                })
    
    # Detect improving/worsening trends in TIR
    if len(tir_by_week) >= 3:
        sorted_weeks = sorted(tir_by_week.keys())
        recent_weeks = sorted_weeks[-3:]  # Last 3 weeks
        older_weeks = sorted_weeks[-6:-3] if len(sorted_weeks) >= 6 else sorted_weeks[:-3]
        
        if older_weeks:
            recent_tir = sum(tir_by_week[w]["in_range"] / tir_by_week[w]["total"] * 100 
                           for w in recent_weeks) / len(recent_weeks)
            older_tir = sum(tir_by_week[w]["in_range"] / tir_by_week[w]["total"] * 100 
                          for w in older_weeks) / len(older_weeks)
            
            change = recent_tir - older_tir
            
            if abs(change) >= SIGNIFICANT_TIR_CHANGE:  # Significant change threshold
                if change > 0:
                    alerts.append({
                        "severity": "low",
                        "category": "trend_improvement",
                        "pattern": "time_in_range_trend",
                        "message": f"Your control has improved {abs(change):.1f}% in recent weeks",
                        "details": {
                            "recent_tir": round(recent_tir, 1),
                            "older_tir": round(older_tir, 1),
                            "change": round(change, 1)
                        }
                    })
                else:
                    alerts.append({
                        "severity": "medium",
                        "category": "trend_worsening",
                        "pattern": "time_in_range_trend",
                        "message": f"Your control has declined {abs(change):.1f}% in recent weeks",
                        "details": {
                            "recent_tir": round(recent_tir, 1),
                            "older_tir": round(older_tir, 1),
                            "change": round(change, 1)
                        }
                    })
    
    # Sort alerts by severity (high > medium > low)
    severity_order = {"high": 0, "medium": 1, "low": 2}
    alerts.sort(key=lambda x: severity_order.get(x["severity"], 99))
    
    return {
        "days_analyzed": days,
        "alert_count": len(alerts),
        "alerts": alerts,
        "thresholds": {
            "min_occurrences": min_occurrences,
            "target_low": convert_glucose(t["target_low"]),
            "target_high": convert_glucose(t["target_high"]),
            "unit": get_unit_label()
        }
    }


def parse_date_arg(date_str):
    """Parse a date argument like 'today', 'yesterday', '2026-01-16', or 'Jan 16'."""
    date_str = date_str.lower().strip()
    today = datetime.now().date()
    
    if date_str == "today":
        return today
    elif date_str == "yesterday":
        return today - timedelta(days=1)
    
    # Try ISO format (2026-01-16)
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        pass
    
    # Try short formats (Jan 16, January 16)
    for fmt in ["%b %d", "%B %d", "%m/%d", "%m-%d"]:
        try:
            parsed = datetime.strptime(date_str, fmt).date()
            # Assume current year
            return parsed.replace(year=today.year)
        except ValueError:
            pass
    
    raise ValueError(f"Could not parse date: {date_str}. Try 'today', 'yesterday', '2026-01-16', or 'Jan 16'")


def view_day(date_str, hour_start=None, hour_end=None):
    """
    View all glucose readings for a specific date.
    Shows detailed timeline with trends and statistics.
    """
    if not ensure_data(90):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}
    
    try:
        target_date = parse_date_arg(date_str)
    except ValueError as e:
        return {"error": str(e)}
    
    conn = sqlite3.connect(DB_PATH)
    
    # Build query for the specific date
    query = """
    SELECT sgv, date_ms, date_string, direction
    FROM readings
    WHERE date(datetime(date_ms/1000, 'unixepoch', 'localtime')) = ?
    """
    params = [target_date.isoformat()]
    
    # Add hour filter if specified
    if hour_start is not None and hour_end is not None:
        query += """ AND CAST(strftime('%H', datetime(date_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) 
                     BETWEEN ? AND ?"""
        params.extend([hour_start, hour_end])
    
    query += " ORDER BY date_ms"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    if not rows:
        return {"error": f"No readings found for {target_date.isoformat()}"}
    
    t = get_thresholds()
    readings = []
    sgv_values = []
    
    for sgv, date_ms, date_string, direction in rows:
        try:
            dt = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            local_time = dt.astimezone().strftime("%H:%M")
        except (ValueError, TypeError):
            local_time = "??:??"
        
        status = "in_range"
        if sgv < t["urgent_low"]:
            status = "very_low"
        elif sgv < t["target_low"]:
            status = "low"
        elif sgv > t["urgent_high"]:
            status = "very_high"
        elif sgv > t["target_high"]:
            status = "high"
        
        readings.append({
            "time": local_time,
            "glucose": convert_glucose(sgv),
            "trend": direction or "Unknown",
            "status": status
        })
        sgv_values.append(sgv)
    
    # Calculate statistics
    avg_sgv = sum(sgv_values) / len(sgv_values)
    min_sgv = min(sgv_values)
    max_sgv = max(sgv_values)
    in_range = sum(1 for v in sgv_values if t["target_low"] <= v <= t["target_high"])
    tir_pct = (in_range / len(sgv_values)) * 100
    
    # Find peak and trough times
    peak_idx = sgv_values.index(max_sgv)
    trough_idx = sgv_values.index(min_sgv)
    
    time_filter = None
    if hour_start is not None:
        time_filter = f"hours={hour_start}:00-{hour_end}:00"
    
    return {
        "date": target_date.isoformat(),
        "filter": time_filter,
        "readings_count": len(readings),
        "statistics": {
            "average": convert_glucose(round(avg_sgv)),
            "min": convert_glucose(min_sgv),
            "max": convert_glucose(max_sgv),
            "time_in_range_pct": round(tir_pct, 1),
            "peak_time": readings[peak_idx]["time"],
            "trough_time": readings[trough_idx]["time"]
        },
        "readings": readings,
        "unit": get_unit_label()
    }


def find_worst_days(days=21, hour_start=None, hour_end=None, limit=5):
    """
    Find the worst days for glucose control in a given period.
    Ranks days by peak glucose and time out of range.
    """
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}
    
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    
    t = get_thresholds()
    
    # Build query
    query = """
    SELECT date(datetime(date_ms/1000, 'unixepoch', 'localtime')) as day,
           MAX(sgv) as peak,
           MIN(sgv) as trough,
           AVG(sgv) as avg_glucose,
           COUNT(*) as readings,
           SUM(CASE WHEN sgv > ? THEN 1 ELSE 0 END) as high_count,
           SUM(CASE WHEN sgv < ? THEN 1 ELSE 0 END) as low_count,
           SUM(CASE WHEN sgv BETWEEN ? AND ? THEN 1 ELSE 0 END) as in_range_count
    FROM readings
    WHERE date_ms >= ?
    """
    params = [t["target_high"], t["target_low"], t["target_low"], t["target_high"], cutoff_ms]
    
    if hour_start is not None and hour_end is not None:
        query += """ AND CAST(strftime('%H', datetime(date_ms/1000, 'unixepoch', 'localtime')) AS INTEGER) 
                     BETWEEN ? AND ?"""
        params.extend([hour_start, hour_end])
    
    query += " GROUP BY day ORDER BY peak DESC"
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    
    if not rows:
        return {"error": "No data found for the specified period."}
    
    # Process and rank days
    worst_days = []
    for row in rows[:limit]:
        day, peak, trough, avg, readings, high_count, low_count, in_range_count = row
        tir_pct = (in_range_count / readings) * 100 if readings > 0 else 0
        
        worst_days.append({
            "date": day,
            "peak": convert_glucose(peak),
            "trough": convert_glucose(trough),
            "average": convert_glucose(round(avg)),
            "readings": readings,
            "time_in_range_pct": round(tir_pct, 1),
            "high_readings": high_count,
            "low_readings": low_count
        })
    
    time_filter = None
    if hour_start is not None:
        time_filter = f"hours={hour_start}:00-{hour_end}:00"
    
    return {
        "days_analyzed": days,
        "filter": time_filter,
        "worst_days": worst_days,
        "unit": get_unit_label()
    }


def generate_html_report(days=90, output_path=None):
    """
    Generate a comprehensive, self-contained HTML report with interactive charts.
    Similar to tally's spending reports but for diabetes/CGM data.
    
    Args:
        days: Number of days to include in the report
        output_path: Path to save the HTML file (default: nightscout_report.html in skill dir)
    
    Returns:
        Path to the generated HTML file, or error dict
    """
    if not ensure_data(days):
        return {"error": "Could not fetch data from Nightscout. Check your NIGHTSCOUT_URL."}
    
    conn = sqlite3.connect(DB_PATH)
    
    # Fetch ALL readings for interactive filtering in the browser
    all_rows = conn.execute(
        "SELECT sgv, date_ms, date_string, direction FROM readings WHERE sgv > 0 ORDER BY date_ms"
    ).fetchall()
    conn.close()
    
    if not all_rows:
        return {"error": "No data found."}
    
    # Filter for the initial display (default days)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    rows = [r for r in all_rows if r[1] >= cutoff_ms]
    
    if not rows:
        return {"error": "No data found for the specified period."}
    
    # Create raw readings array for JavaScript (for interactive filtering)
    all_readings_data = []
    for sgv, date_ms, date_str, direction in all_rows:
        all_readings_data.append({
            "sgv": sgv,
            "date": date_str,
            "direction": direction
        })
    
    t = get_thresholds()
    unit = get_unit_label()
    is_mmol = use_mmol()
    
    # =========================================================================
    # Data Processing for Charts
    # =========================================================================
    
    # Basic statistics
    all_values = [r[0] for r in rows]
    raw_mean = sum(all_values) / len(all_values)
    raw_std = (sum((x - raw_mean) ** 2 for x in all_values) / len(all_values)) ** 0.5
    gmi = round(3.31 + (0.02392 * raw_mean), 1)
    cv = round((raw_std / raw_mean) * 100, 1) if raw_mean else 0
    
    # Time in range calculation
    very_low = sum(1 for v in all_values if v < t["urgent_low"])
    low = sum(1 for v in all_values if t["urgent_low"] <= v < t["target_low"])
    in_range = sum(1 for v in all_values if t["target_low"] <= v <= t["target_high"])
    high = sum(1 for v in all_values if t["target_high"] < v <= t["urgent_high"])
    very_high = sum(1 for v in all_values if v > t["urgent_high"])
    total = len(all_values)
    
    tir_data = {
        "very_low": round(very_low / total * 100, 1),
        "low": round(low / total * 100, 1),
        "in_range": round(in_range / total * 100, 1),
        "high": round(high / total * 100, 1),
        "very_high": round(very_high / total * 100, 1)
    }
    
    # Hourly data for Modal Day chart (all days overlaid)
    hourly_all = defaultdict(list)
    for sgv, _, ds, _ in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            hourly_all[dt.hour].append(sgv)
        except (ValueError, TypeError):
            pass
    
    modal_day_data = []
    for hour in range(24):
        values = hourly_all.get(hour, [])
        if values:
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            modal_day_data.append({
                "hour": hour,
                "mean": convert_glucose(round(sum(values) / n, 1)),
                "median": convert_glucose(sorted_vals[n // 2]),
                "p10": convert_glucose(sorted_vals[int(n * 0.1)]) if n > 10 else convert_glucose(sorted_vals[0]),
                "p25": convert_glucose(sorted_vals[int(n * 0.25)]) if n > 4 else convert_glucose(sorted_vals[0]),
                "p75": convert_glucose(sorted_vals[int(n * 0.75)]) if n > 4 else convert_glucose(sorted_vals[-1]),
                "p90": convert_glucose(sorted_vals[int(n * 0.9)]) if n > 10 else convert_glucose(sorted_vals[-1]),
                "min": convert_glucose(sorted_vals[0]),
                "max": convert_glucose(sorted_vals[-1])
            })
        else:
            modal_day_data.append({
                "hour": hour, "mean": None, "median": None,
                "p10": None, "p25": None, "p75": None, "p90": None,
                "min": None, "max": None
            })
    
    # Daily data for trend chart
    daily_data = defaultdict(list)
    for sgv, _, ds, _ in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            date_key = dt.strftime("%Y-%m-%d")
            daily_data[date_key].append(sgv)
        except (ValueError, TypeError):
            pass
    
    daily_stats = []
    for date_str in sorted(daily_data.keys()):
        values = daily_data[date_str]
        if values:
            in_r = sum(1 for v in values if t["target_low"] <= v <= t["target_high"])
            daily_stats.append({
                "date": date_str,
                "mean": convert_glucose(round(sum(values) / len(values), 1)),
                "min": convert_glucose(min(values)),
                "max": convert_glucose(max(values)),
                "tir": round(in_r / len(values) * 100, 1),
                "readings": len(values)
            })
    
    # Day of week data
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    dow_data = defaultdict(list)
    for sgv, _, ds, _ in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            dow_data[dt.weekday()].append(sgv)
        except (ValueError, TypeError):
            pass
    
    dow_stats = []
    for day_idx in range(7):
        values = dow_data.get(day_idx, [])
        if values:
            in_r = sum(1 for v in values if t["target_low"] <= v <= t["target_high"])
            dow_stats.append({
                "day": day_names[day_idx],
                "mean": convert_glucose(round(sum(values) / len(values), 1)),
                "tir": round(in_r / len(values) * 100, 1),
                "readings": len(values)
            })
        else:
            dow_stats.append({
                "day": day_names[day_idx],
                "mean": 0,
                "tir": 0,
                "readings": 0
            })
    
    # Heatmap data (day x hour)
    heatmap_data = defaultdict(lambda: defaultdict(list))
    for sgv, _, ds, _ in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            heatmap_data[dt.weekday()][dt.hour].append(sgv)
        except (ValueError, TypeError):
            pass
    
    heatmap_tir = []
    for day_idx in range(7):
        day_row = []
        for hour in range(24):
            values = heatmap_data[day_idx].get(hour, [])
            if values:
                in_r = sum(1 for v in values if t["target_low"] <= v <= t["target_high"])
                tir_pct = round(in_r / len(values) * 100, 1)
            else:
                tir_pct = None
            day_row.append(tir_pct)
        heatmap_tir.append(day_row)
    
    # Glucose distribution (histogram)
    bin_size = 10 if not is_mmol else 1
    min_bin = 40 if not is_mmol else 2
    max_bin = 350 if not is_mmol else 20
    
    bins = defaultdict(int)
    for v in all_values:
        bin_start = (v // bin_size) * bin_size
        bin_start = max(min_bin, min(max_bin, bin_start))
        bins[bin_start] += 1
    
    histogram_data = []
    for b in range(min_bin, max_bin + bin_size, bin_size):
        histogram_data.append({
            "bin": convert_glucose(b) if is_mmol else b,
            "count": bins.get(b, 0)
        })
    
    # Weekly summaries (for the period selector)
    weekly_data = defaultdict(list)
    for sgv, _, ds, _ in rows:
        try:
            dt = datetime.fromisoformat(ds.replace("Z", "+00:00"))
            week_start = (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")
            weekly_data[week_start].append(sgv)
        except (ValueError, TypeError):
            pass
    
    weekly_stats = []
    for week_start in sorted(weekly_data.keys()):
        values = weekly_data[week_start]
        if values:
            in_r = sum(1 for v in values if t["target_low"] <= v <= t["target_high"])
            weekly_stats.append({
                "week": week_start,
                "mean": convert_glucose(round(sum(values) / len(values), 1)),
                "tir": round(in_r / len(values) * 100, 1),
                "readings": len(values)
            })
    
    # Date range info
    first_date = rows[0][2][:10] if rows[0][2] else "unknown"
    last_date = rows[-1][2][:10] if rows[-1][2] else "unknown"
    
    # =========================================================================
    # Detect Trend Alerts
    # =========================================================================
    alerts_result = detect_trend_alerts(days, min_occurrences=2)
    alerts = alerts_result.get("alerts", []) if "error" not in alerts_result else []
    
    # =========================================================================
    # HTML Template with embedded Chart.js
    # =========================================================================
    
    html_template = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nightscout CGM Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
    <style>
        :root {
            --bg-primary: #1a1a2e;
            --bg-secondary: #16213e;
            --bg-card: #0f3460;
            --text-primary: #eee;
            --text-secondary: #aaa;
            --accent: #e94560;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --info: #3b82f6;
            --in-range: #10b981;
            --low: #3b82f6;
            --high: #eab308;
            --very-low: #1d4ed8;
            --very-high: #ef4444;
        }
        
        /* Date Controls - Tally-style */
        .date-controls {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            flex-wrap: wrap;
            margin: 20px 0;
            padding: 15px;
            background: var(--bg-secondary);
            border-radius: 12px;
        }
        
        .date-controls label {
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-right: 8px;
        }
        
        .date-btn {
            padding: 8px 16px;
            border: 1px solid var(--bg-card);
            background: var(--bg-card);
            color: var(--text-primary);
            border-radius: 6px;
            cursor: pointer;
            transition: all 0.2s;
            font-size: 0.9rem;
        }
        
        .date-btn:hover {
            background: var(--accent);
            border-color: var(--accent);
        }
        
        .date-btn.active {
            background: var(--accent);
            border-color: var(--accent);
            font-weight: bold;
        }
        
        .date-separator {
            color: var(--text-secondary);
            margin: 0 4px;
        }
        
        .custom-date-inputs {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-left: 16px;
            padding-left: 16px;
            border-left: 1px solid var(--bg-card);
        }
        
        .custom-date-inputs input[type="date"] {
            padding: 6px 10px;
            border: 1px solid var(--bg-card);
            background: var(--bg-primary);
            color: var(--text-primary);
            border-radius: 6px;
            font-size: 0.85rem;
        }
        
        .custom-date-inputs input[type="date"]::-webkit-calendar-picker-indicator {
            filter: invert(1);
        }
        
        .date-range-display {
            text-align: center;
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-top: 10px;
        }
        
        .date-range-display strong {
            color: var(--text-primary);
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            line-height: 1.6;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid var(--bg-card);
            margin-bottom: 30px;
        }
        
        header h1 {
            font-size: 2.5rem;
            margin-bottom: 10px;
            background: linear-gradient(135deg, var(--accent), var(--info));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        header .subtitle {
            color: var(--text-secondary);
            font-size: 1.1rem;
        }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        
        .stat-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }
        
        .stat-card .value {
            font-size: 2.5rem;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .stat-card .label {
            color: var(--text-secondary);
            font-size: 0.9rem;
        }
        
        .stat-card.tir .value { color: var(--in-range); }
        .stat-card.gmi .value { color: var(--info); }
        .stat-card.cv .value { color: var(--warning); }
        
        .alerts-section {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
        }
        
        .alerts-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            cursor: pointer;
            user-select: none;
        }
        
        .alerts-header:hover {
            opacity: 0.8;
        }
        
        .alerts-section.collapsed .alerts-header {
            margin-bottom: 0;
        }
        
        .alerts-section:not(.collapsed) .alerts-header {
            margin-bottom: 15px;
        }
        
        .alerts-toggle {
            font-size: 1rem;
            color: var(--text-secondary);
            transition: transform 0.2s;
        }
        
        .alerts-section:not(.collapsed) .alerts-toggle {
            transform: rotate(90deg);
        }
        
        .alerts-body {
            display: none;
        }
        
        .alerts-section:not(.collapsed) .alerts-body {
            display: block;
        }
        
        .alerts-section h2 {
            margin: 0;
            font-size: 1.3rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .alerts-section h2::before {
            content: '⚠️';
            font-size: 1.5rem;
        }
        
        .alerts-summary {
            display: flex;
            gap: 12px;
            align-items: center;
            margin-right: 10px;
        }
        
        .alert-badge {
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 4px 10px;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 600;
        }
        
        .alert-badge.high {
            background: rgba(239, 68, 68, 0.15);
            color: var(--danger);
        }
        
        .alert-badge.medium {
            background: rgba(234, 179, 8, 0.15);
            color: var(--warning);
        }
        
        .alerts-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }
        
        .alert-item {
            background: var(--bg-card);
            border-left: 4px solid;
            border-radius: 8px;
            padding: 15px;
            display: flex;
            align-items: start;
            gap: 12px;
        }
        
        .alert-item.severity-high {
            border-left-color: var(--danger);
        }
        
        .alert-item.severity-medium {
            border-left-color: var(--warning);
        }
        
        .alert-item.severity-low {
            border-left-color: var(--info);
        }
        
        .alert-icon {
            font-size: 1.5rem;
            flex-shrink: 0;
        }
        
        .alert-content {
            flex: 1;
        }
        
        .alert-message {
            font-size: 1rem;
            color: var(--text-primary);
            margin-bottom: 5px;
        }
        
        .alert-details {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }
        
        .alerts-expand {
            margin-top: 12px;
            text-align: center;
        }
        
        .alerts-expand button {
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: all 0.2s;
        }
        
        .alerts-expand button:hover {
            background: var(--bg-secondary);
            color: var(--text-primary);
        }
        
        .hidden-alerts {
            display: none;
        }
        
        .hidden-alerts.expanded {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-top: 12px;
        }
        
        .no-alerts {
            text-align: center;
            padding: 30px;
            color: var(--text-secondary);
        }
        
        .no-alerts-icon {
            font-size: 3rem;
            margin-bottom: 10px;
            color: var(--success);
        }
        
        .chart-section {
            background: var(--bg-secondary);
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 30px;
        }
        
        .chart-section h2 {
            margin-bottom: 15px;
            font-size: 1.3rem;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .chart-section h2::before {
            content: '';
            display: inline-block;
            width: 4px;
            height: 24px;
            background: var(--accent);
            border-radius: 2px;
        }
        
        .chart-container {
            position: relative;
            height: 350px;
        }
        
        .chart-container.tall {
            height: 450px;
        }
        
        .grid-2 {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(450px, 1fr));
            gap: 30px;
        }
        
        .tir-breakdown {
            display: flex;
            justify-content: center;
            gap: 20px;
            flex-wrap: wrap;
            margin-top: 15px;
        }
        
        .tir-item {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        .tir-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%%;
        }
        
        .tir-dot.very-low { background: var(--very-low); }
        .tir-dot.low { background: var(--low); }
        .tir-dot.in-range { background: var(--in-range); }
        .tir-dot.high { background: var(--high); }
        .tir-dot.very-high { background: var(--very-high); }
        
        .heatmap-container {
            overflow-x: auto;
        }
        
        .heatmap {
            display: grid;
            grid-template-columns: 60px repeat(24, 1fr);
            gap: 2px;
            font-size: 0.75rem;
        }
        
        .heatmap-cell {
            aspect-ratio: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 4px;
            min-width: 28px;
            position: relative;
            cursor: pointer;
            transition: transform 0.15s ease, box-shadow 0.15s ease, filter 0.15s ease;
        }
        
        .heatmap-cell:not(.heatmap-header):not(.heatmap-label):hover {
            transform: scale(1.15);
            box-shadow: 0 0 12px rgba(255, 255, 255, 0.3);
            filter: brightness(1.2);
            z-index: 10;
        }
        
        .heatmap-cell .tooltip {
            display: none;
            position: absolute;
            bottom: 120%%;
            left: 50%%;
            transform: translateX(-50%%);
            background: var(--bg-primary);
            border: 1px solid var(--accent);
            color: var(--text-primary);
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 0.8rem;
            white-space: nowrap;
            z-index: 100;
            pointer-events: none;
        }
        
        .heatmap-cell .tooltip::after {
            content: '';
            position: absolute;
            top: 100%%;
            left: 50%%;
            transform: translateX(-50%%);
            border: 6px solid transparent;
            border-top-color: var(--accent);
        }
        
        .heatmap-cell:hover .tooltip {
            display: block;
        }
        
        .heatmap-header {
            background: transparent;
            color: var(--text-secondary);
            font-weight: bold;
        }
        
        .heatmap-label {
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 8px;
            color: var(--text-secondary);
            font-weight: 500;
        }
        
        footer {
            text-align: center;
            padding: 30px;
            color: var(--text-secondary);
            font-size: 0.9rem;
            border-top: 1px solid var(--bg-card);
            margin-top: 30px;
        }
        
        footer a {
            color: var(--accent);
            text-decoration: none;
        }
        
        .disclaimer {
            background: var(--bg-card);
            border-left: 4px solid var(--warning);
            padding: 15px;
            margin: 20px 0;
            border-radius: 0 8px 8px 0;
            font-size: 0.9rem;
        }
        
        @media (max-width: 768px) {
            .grid-2 {
                grid-template-columns: 1fr;
            }
            
            .chart-container {
                height: 300px;
            }
            
            header h1 {
                font-size: 1.8rem;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 Nightscout CGM Report</h1>
            <p class="subtitle" id="reportSubtitle">%(first_date)s to %(last_date)s (%(days)s days) • %(readings)s readings</p>
        </header>
        
        <!-- Date Range Controls (tally-style) -->
        <div class="date-controls">
            <label>Period:</label>
            <button class="date-btn" onclick="setDateRange(7)" data-days="7">7 days</button>
            <button class="date-btn" onclick="setDateRange(14)" data-days="14">14 days</button>
            <button class="date-btn" onclick="setDateRange(30)" data-days="30">30 days</button>
            <button class="date-btn active" onclick="setDateRange(90)" data-days="90">90 days</button>
            <button class="date-btn" onclick="setDateRange(180)" data-days="180">6 months</button>
            <button class="date-btn" onclick="setDateRange(365)" data-days="365">1 year</button>
            <button class="date-btn" onclick="setDateRange(0)" data-days="0">All</button>
            
            <div class="custom-date-inputs">
                <input type="date" id="startDate" onchange="applyCustomDateRange()" title="Start date">
                <span class="date-separator">to</span>
                <input type="date" id="endDate" onchange="applyCustomDateRange()" title="End date">
            </div>
        </div>
        
        <div class="disclaimer">
            ⚠️ <strong>Not medical advice.</strong> This report is for informational purposes only. 
            Always consult your healthcare provider for diabetes management decisions.
        </div>
        
        <!-- Key Metrics -->
        <div class="stats-grid">
            <div class="stat-card tir">
                <div class="value">%(tir_in_range).1f%%</div>
                <div class="label">Time in Range (%(target_low)s-%(target_high)s %(unit)s)</div>
            </div>
            <div class="stat-card gmi">
                <div class="value">%(gmi).1f%%</div>
                <div class="label">GMI (Estimated A1C)</div>
            </div>
            <div class="stat-card cv">
                <div class="value">%(cv).1f%%</div>
                <div class="label">CV (%(cv_status)s)</div>
            </div>
            <div class="stat-card">
                <div class="value">%(mean)s</div>
                <div class="label">Average Glucose (%(unit)s)</div>
            </div>
        </div>
        
        <!-- Trend Alerts (collapsed by default) -->
        <div class="alerts-section collapsed" id="alertsSection">
            <div class="alerts-header" onclick="toggleAlertsSection()">
                <h2>Trend Alerts</h2>
                <div class="alerts-summary" id="alertsSummary"></div>
                <span class="alerts-toggle">▶</span>
            </div>
            <div class="alerts-body" id="alertsBody">
                <div class="alerts-container" id="alertsContainer">
                    <!-- Top alerts will be rendered here by JavaScript -->
                </div>
                <div class="hidden-alerts" id="hiddenAlerts">
                    <!-- Additional alerts shown when expanded -->
                </div>
                <div class="alerts-expand" id="alertsExpand" style="display: none;">
                    <button onclick="toggleMoreAlerts(event)">Show all alerts</button>
                </div>
            </div>
        </div>
        
        <!-- Time in Range Pie Chart -->
        <div class="chart-section">
            <h2>Time in Range Distribution</h2>
            <div class="chart-container">
                <canvas id="tirPieChart"></canvas>
            </div>
            <div class="tir-breakdown">
                <div class="tir-item"><span class="tir-dot very-low"></span> Very Low (&lt;%(urgent_low)s): %(tir_very_low).1f%%</div>
                <div class="tir-item"><span class="tir-dot low"></span> Low (%(urgent_low)s-%(target_low_minus)s): %(tir_low).1f%%</div>
                <div class="tir-item"><span class="tir-dot in-range"></span> In Range (%(target_low)s-%(target_high)s): %(tir_in_range).1f%%</div>
                <div class="tir-item"><span class="tir-dot high"></span> High (%(target_high_plus)s-%(urgent_high)s): %(tir_high).1f%%</div>
                <div class="tir-item"><span class="tir-dot very-high"></span> Very High (&gt;%(urgent_high)s): %(tir_very_high).1f%%</div>
            </div>
        </div>
        
        <!-- Modal Day Chart -->
        <div class="chart-section">
            <h2>Modal Day (Typical 24-Hour Profile)</h2>
            <p style="color: var(--text-secondary); margin-bottom: 15px; font-size: 0.9rem;">
                Shows your typical glucose pattern throughout the day. The shaded area represents the 10th-90th percentile range.
            </p>
            <div class="chart-container tall">
                <canvas id="modalDayChart"></canvas>
            </div>
        </div>
        
        <div class="grid-2">
            <!-- Daily Trend -->
            <div class="chart-section">
                <h2>Daily Average & Time in Range</h2>
                <div class="chart-container">
                    <canvas id="dailyTrendChart"></canvas>
                </div>
            </div>
            
            <!-- Day of Week -->
            <div class="chart-section">
                <h2>Day of Week Comparison</h2>
                <div class="chart-container">
                    <canvas id="dowChart"></canvas>
                </div>
            </div>
        </div>
        
        <!-- Glucose Distribution -->
        <div class="chart-section">
            <h2>Glucose Distribution</h2>
            <div class="chart-container">
                <canvas id="histogramChart"></canvas>
            </div>
        </div>
        
        <!-- Heatmap -->
        <div class="chart-section">
            <h2>Time-in-Range Heatmap (Day × Hour)</h2>
            <p style="color: var(--text-secondary); margin-bottom: 15px; font-size: 0.9rem;">
                Darker green = higher time in range. Red/orange = problem areas needing attention.
            </p>
            <div class="heatmap-container">
                <div class="heatmap" id="heatmapGrid">
                    <!-- Generated by JavaScript -->
                </div>
            </div>
        </div>
        
        <!-- Weekly Summary -->
        <div class="chart-section">
            <h2>Weekly Summary</h2>
            <div class="chart-container">
                <canvas id="weeklyChart"></canvas>
            </div>
        </div>
        
        <footer>
            Generated by <a href="https://github.com/shanselman/nightscout-cgm-skill">Nightscout CGM Skill</a> on %(generated_date)s
            <br>
            Data stays local. Your privacy is protected. 🔒
        </footer>
    </div>
    
    <script>
        // Chart.js global defaults
        Chart.defaults.color = '#aaa';
        Chart.defaults.borderColor = 'rgba(255,255,255,0.1)';
        
        // Raw data from Python (for filtering)
        const allReadings = %(all_readings_json)s;
        const thresholds = {
            urgentLow: %(urgent_low)s,
            targetLow: %(target_low)s,
            targetHigh: %(target_high)s,
            urgentHigh: %(urgent_high)s
        };
        const unit = '%(unit)s';
        const isMMOL = %(is_mmol_js)s;
        
        // Alerts data from Python
        const allAlerts = %(alerts_json)s;
        
        // Current filter state
        let currentDays = %(initial_days)s;
        let customStartDate = null;
        let customEndDate = null;
        
        // Chart instances (for updates)
        let tirChart, modalChart, dailyChart, dowChart, histChart, weeklyChart;
        
        // Colors
        const colors = {
            veryLow: '#1d4ed8',
            low: '#3b82f6',
            inRange: '#10b981',
            high: '#eab308',
            veryHigh: '#ef4444',
            accent: '#e94560',
            info: '#3b82f6'
        };
        
        // Initialize date inputs with data range
        function initDateControls() {
            if (allReadings.length === 0) return;
            
            const dates = allReadings.map(r => r.date.split('T')[0]);
            const minDate = dates[0];
            const maxDate = dates[dates.length - 1];
            
            document.getElementById('startDate').min = minDate;
            document.getElementById('startDate').max = maxDate;
            document.getElementById('endDate').min = minDate;
            document.getElementById('endDate').max = maxDate;
            
            // Set default to current filter
            const endDate = new Date(maxDate);
            const startDate = new Date(endDate);
            startDate.setDate(startDate.getDate() - currentDays + 1);
            
            document.getElementById('endDate').value = maxDate;
            document.getElementById('startDate').value = startDate.toISOString().split('T')[0];
            
            // Highlight active button
            updateActiveButton(currentDays);
        }
        
        function updateActiveButton(days) {
            document.querySelectorAll('.date-btn').forEach(btn => {
                btn.classList.toggle('active', parseInt(btn.dataset.days) === days);
            });
        }
        
        function setDateRange(days) {
            currentDays = days;
            customStartDate = null;
            customEndDate = null;
            updateActiveButton(days);
            
            const filteredData = filterReadingsByDays(days);
            updateAllCharts(filteredData);
            
            // Update date inputs to reflect selection
            if (filteredData.length > 0) {
                const dates = filteredData.map(r => r.date.split('T')[0]);
                document.getElementById('startDate').value = dates[0];
                document.getElementById('endDate').value = dates[dates.length - 1];
            }
        }
        
        function applyCustomDateRange() {
            const start = document.getElementById('startDate').value;
            const end = document.getElementById('endDate').value;
            
            if (!start || !end) return;
            
            customStartDate = start;
            customEndDate = end;
            updateActiveButton(-1); // Deselect all preset buttons
            
            const filteredData = filterReadingsByDateRange(start, end);
            updateAllCharts(filteredData);
        }
        
        function filterReadingsByDays(days) {
            if (days === 0 || !days) return allReadings; // All data
            
            const now = new Date();
            const cutoff = new Date(now);
            cutoff.setDate(cutoff.getDate() - days);
            
            return allReadings.filter(r => new Date(r.date) >= cutoff);
        }
        
        function filterReadingsByDateRange(start, end) {
            const startDate = new Date(start);
            const endDate = new Date(end);
            endDate.setHours(23, 59, 59, 999);
            
            return allReadings.filter(r => {
                const d = new Date(r.date);
                return d >= startDate && d <= endDate;
            });
        }
        
        function convertGlucose(val) {
            return isMMOL ? Math.round(val / 18.0 * 10) / 10 : val;
        }
        
        // Calculate all statistics from filtered data
        function calcStats(readings) {
            if (readings.length === 0) {
                return {
                    tir: { very_low: 0, low: 0, in_range: 0, high: 0, very_high: 0 },
                    mean: 0, gmi: 0, cv: 0, count: 0
                };
            }
            
            const values = readings.map(r => r.sgv);
            const mean = values.reduce((a, b) => a + b, 0) / values.length;
            const variance = values.reduce((sum, v) => sum + Math.pow(v - mean, 2), 0) / values.length;
            const std = Math.sqrt(variance);
            const cv = mean > 0 ? (std / mean) * 100 : 0;
            const gmi = 3.31 + (0.02392 * mean);
            
            const t = thresholds;
            const veryLow = values.filter(v => v < t.urgentLow).length;
            const low = values.filter(v => v >= t.urgentLow && v < t.targetLow).length;
            const inRange = values.filter(v => v >= t.targetLow && v <= t.targetHigh).length;
            const high = values.filter(v => v > t.targetHigh && v <= t.urgentHigh).length;
            const veryHigh = values.filter(v => v > t.urgentHigh).length;
            const total = values.length;
            
            return {
                tir: {
                    very_low: (veryLow / total * 100).toFixed(1),
                    low: (low / total * 100).toFixed(1),
                    in_range: (inRange / total * 100).toFixed(1),
                    high: (high / total * 100).toFixed(1),
                    very_high: (veryHigh / total * 100).toFixed(1)
                },
                mean: convertGlucose(Math.round(mean)),
                gmi: gmi.toFixed(1),
                cv: cv.toFixed(1),
                cvStatus: cv < 36 ? 'stable' : 'variable',
                count: total
            };
        }
        
        // Build modal day data
        function buildModalDay(readings) {
            const hourly = {};
            for (let h = 0; h < 24; h++) hourly[h] = [];
            
            readings.forEach(r => {
                const d = new Date(r.date);
                hourly[d.getHours()].push(r.sgv);
            });
            
            const result = [];
            for (let h = 0; h < 24; h++) {
                const vals = hourly[h].sort((a, b) => a - b);
                if (vals.length > 0) {
                    const n = vals.length;
                    result.push({
                        hour: h,
                        mean: convertGlucose(vals.reduce((a, b) => a + b, 0) / n),
                        median: convertGlucose(vals[Math.floor(n / 2)]),
                        p10: convertGlucose(vals[Math.floor(n * 0.1)] || vals[0]),
                        p25: convertGlucose(vals[Math.floor(n * 0.25)] || vals[0]),
                        p75: convertGlucose(vals[Math.floor(n * 0.75)] || vals[n - 1]),
                        p90: convertGlucose(vals[Math.floor(n * 0.9)] || vals[n - 1])
                    });
                } else {
                    result.push({ hour: h, mean: null, median: null, p10: null, p25: null, p75: null, p90: null });
                }
            }
            return result;
        }
        
        // Build daily stats
        function buildDailyStats(readings) {
            const daily = {};
            readings.forEach(r => {
                const dateKey = r.date.split('T')[0];
                if (!daily[dateKey]) daily[dateKey] = [];
                daily[dateKey].push(r.sgv);
            });
            
            const t = thresholds;
            return Object.keys(daily).sort().map(date => {
                const vals = daily[date];
                const inR = vals.filter(v => v >= t.targetLow && v <= t.targetHigh).length;
                return {
                    date: date,
                    mean: convertGlucose(Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)),
                    tir: (inR / vals.length * 100).toFixed(1),
                    readings: vals.length
                };
            });
        }
        
        // Build day of week stats
        function buildDowStats(readings) {
            const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
            const dow = {};
            for (let d = 0; d < 7; d++) dow[d] = [];
            
            readings.forEach(r => {
                const d = new Date(r.date);
                dow[d.getDay()].push(r.sgv);
            });
            
            const t = thresholds;
            // Reorder to Monday-Sunday
            const ordered = [1, 2, 3, 4, 5, 6, 0];
            return ordered.map(dayIdx => {
                const vals = dow[dayIdx];
                if (vals.length === 0) return { day: dayNames[dayIdx], mean: 0, tir: 0, readings: 0 };
                const inR = vals.filter(v => v >= t.targetLow && v <= t.targetHigh).length;
                return {
                    day: dayNames[dayIdx],
                    mean: convertGlucose(Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)),
                    tir: (inR / vals.length * 100).toFixed(1),
                    readings: vals.length
                };
            });
        }
        
        // Build histogram data
        function buildHistogram(readings) {
            const binSize = isMMOL ? 1 : 10;
            const minBin = isMMOL ? 2 : 40;
            const maxBin = isMMOL ? 20 : 350;
            
            const bins = {};
            readings.forEach(r => {
                let v = isMMOL ? r.sgv / 18.0 : r.sgv;
                let binStart = Math.floor(v / binSize) * binSize;
                binStart = Math.max(minBin, Math.min(maxBin, binStart));
                bins[binStart] = (bins[binStart] || 0) + 1;
            });
            
            const result = [];
            for (let b = minBin; b <= maxBin; b += binSize) {
                result.push({ bin: b, count: bins[b] || 0 });
            }
            return result;
        }
        
        // Build weekly stats
        function buildWeeklyStats(readings) {
            const weekly = {};
            readings.forEach(r => {
                const d = new Date(r.date);
                const dayOfWeek = d.getDay();
                const diff = d.getDate() - dayOfWeek + (dayOfWeek === 0 ? -6 : 1);
                const weekStart = new Date(d.setDate(diff)).toISOString().split('T')[0];
                if (!weekly[weekStart]) weekly[weekStart] = [];
                weekly[weekStart].push(r.sgv);
            });
            
            const t = thresholds;
            return Object.keys(weekly).sort().map(week => {
                const vals = weekly[week];
                const inR = vals.filter(v => v >= t.targetLow && v <= t.targetHigh).length;
                return {
                    week: week,
                    mean: convertGlucose(Math.round(vals.reduce((a, b) => a + b, 0) / vals.length)),
                    tir: (inR / vals.length * 100).toFixed(1),
                    readings: vals.length
                };
            });
        }
        
        // Build heatmap data
        function buildHeatmap(readings) {
            const data = {};
            for (let d = 0; d < 7; d++) {
                data[d] = {};
                for (let h = 0; h < 24; h++) data[d][h] = [];
            }
            
            readings.forEach(r => {
                const dt = new Date(r.date);
                // Convert Sunday=0 to Monday=0 format
                const dayIdx = (dt.getDay() + 6) %% 7;
                data[dayIdx][dt.getHours()].push(r.sgv);
            });
            
            const t = thresholds;
            const result = [];
            for (let d = 0; d < 7; d++) {
                const row = [];
                for (let h = 0; h < 24; h++) {
                    const vals = data[d][h];
                    if (vals.length > 0) {
                        const inR = vals.filter(v => v >= t.targetLow && v <= t.targetHigh).length;
                        row.push((inR / vals.length * 100).toFixed(1));
                    } else {
                        row.push(null);
                    }
                }
                result.push(row);
            }
            return result;
        }
        
        // Update subtitle with current filter info
        function updateSubtitle(readings) {
            if (readings.length === 0) {
                document.getElementById('reportSubtitle').textContent = 'No data for selected period';
                return;
            }
            
            const dates = readings.map(r => r.date.split('T')[0]);
            const firstDate = dates[0];
            const lastDate = dates[dates.length - 1];
            const daysDiff = Math.ceil((new Date(lastDate) - new Date(firstDate)) / (1000 * 60 * 60 * 24)) + 1;
            
            document.getElementById('reportSubtitle').textContent = 
                `${firstDate} to ${lastDate} (${daysDiff} days) • ${readings.length.toLocaleString()} readings`;
        }
        
        // Update stat cards
        function updateStatCards(stats) {
            document.querySelector('.stat-card.tir .value').textContent = stats.tir.in_range + '%%';
            document.querySelector('.stat-card.gmi .value').textContent = stats.gmi + '%%';
            document.querySelector('.stat-card.cv .value').textContent = stats.cv + '%%';
            document.querySelector('.stat-card.cv .label').textContent = 'CV (' + stats.cvStatus + ')';
            document.querySelector('.stat-card:last-child .value').textContent = stats.mean;
            
            // Update TIR breakdown
            const breakdown = document.querySelectorAll('.tir-item');
            if (breakdown.length >= 5) {
                breakdown[0].innerHTML = `<span class="tir-dot very-low"></span> Very Low (<${convertGlucose(thresholds.urgentLow)}): ${stats.tir.very_low}%%`;
                breakdown[1].innerHTML = `<span class="tir-dot low"></span> Low (${convertGlucose(thresholds.urgentLow)}-${convertGlucose(thresholds.targetLow - 1)}): ${stats.tir.low}%%`;
                breakdown[2].innerHTML = `<span class="tir-dot in-range"></span> In Range (${convertGlucose(thresholds.targetLow)}-${convertGlucose(thresholds.targetHigh)}): ${stats.tir.in_range}%%`;
                breakdown[3].innerHTML = `<span class="tir-dot high"></span> High (${convertGlucose(thresholds.targetHigh + 1)}-${convertGlucose(thresholds.urgentHigh)}): ${stats.tir.high}%%`;
                breakdown[4].innerHTML = `<span class="tir-dot very-high"></span> Very High (>${convertGlucose(thresholds.urgentHigh)}): ${stats.tir.very_high}%%`;
            }
        }
        
        // Update all charts with filtered data
        function updateAllCharts(readings) {
            const stats = calcStats(readings);
            const modalData = buildModalDay(readings);
            const dailyData = buildDailyStats(readings);
            const dowData = buildDowStats(readings);
            const histData = buildHistogram(readings);
            const weeklyData = buildWeeklyStats(readings);
            const heatmapData = buildHeatmap(readings);
            
            updateSubtitle(readings);
            updateStatCards(stats);
            
            // Update TIR pie
            tirChart.data.datasets[0].data = [
                parseFloat(stats.tir.very_low), parseFloat(stats.tir.low), 
                parseFloat(stats.tir.in_range), parseFloat(stats.tir.high), parseFloat(stats.tir.very_high)
            ];
            tirChart.update();
            
            // Update modal day
            modalChart.data.labels = modalData.map(d => d.hour + ':00');
            modalChart.data.datasets[0].data = modalData.map(d => d.p90);
            modalChart.data.datasets[1].data = modalData.map(d => d.p10);
            modalChart.data.datasets[2].data = modalData.map(d => d.p75);
            modalChart.data.datasets[3].data = modalData.map(d => d.p25);
            modalChart.data.datasets[4].data = modalData.map(d => d.median);
            modalChart.update();
            
            // Update daily trend
            dailyChart.data.labels = dailyData.map(d => d.date);
            dailyChart.data.datasets[0].data = dailyData.map(d => d.mean);
            dailyChart.data.datasets[1].data = dailyData.map(d => parseFloat(d.tir));
            dailyChart.update();
            
            // Update day of week
            dowChart.data.labels = dowData.map(d => d.day);
            dowChart.data.datasets[0].data = dowData.map(d => d.mean);
            dowChart.data.datasets[1].data = dowData.map(d => parseFloat(d.tir));
            dowChart.data.datasets[1].backgroundColor = dowData.map(d => 
                parseFloat(d.tir) >= 70 ? colors.inRange : parseFloat(d.tir) >= 50 ? colors.low : colors.veryLow
            );
            dowChart.update();
            
            // Update histogram
            histChart.data.labels = histData.map(d => d.bin);
            histChart.data.datasets[0].data = histData.map(d => d.count);
            histChart.data.datasets[0].backgroundColor = histData.map(d => {
                const v = isMMOL ? d.bin * 18 : d.bin;
                if (v < thresholds.urgentLow) return colors.veryLow;
                if (v < thresholds.targetLow) return colors.low;
                if (v <= thresholds.targetHigh) return colors.inRange;
                if (v <= thresholds.urgentHigh) return colors.high;
                return colors.veryHigh;
            });
            histChart.update();
            
            // Update weekly
            weeklyChart.data.labels = weeklyData.map(d => 'Week of ' + d.week.slice(5));
            weeklyChart.data.datasets[0].data = weeklyData.map(d => d.mean);
            weeklyChart.data.datasets[1].data = weeklyData.map(d => parseFloat(d.tir));
            weeklyChart.data.datasets[1].backgroundColor = weeklyData.map(d => 
                parseFloat(d.tir) >= 70 ? colors.inRange : parseFloat(d.tir) >= 50 ? colors.low : colors.veryLow
            );
            weeklyChart.update();
            
            // Update heatmap
            updateHeatmap(heatmapData);
        }
        
        function updateHeatmap(heatmapTir) {
            const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
            const fullDayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
            const heatmapGrid = document.getElementById('heatmapGrid');
            heatmapGrid.innerHTML = '';
            
            // Header row
            const headerCell = document.createElement('div');
            headerCell.className = 'heatmap-cell heatmap-header';
            heatmapGrid.appendChild(headerCell);
            
            for (let h = 0; h < 24; h++) {
                const cell = document.createElement('div');
                cell.className = 'heatmap-cell heatmap-header';
                cell.textContent = h;
                heatmapGrid.appendChild(cell);
            }
            
            // Data rows
            for (let d = 0; d < 7; d++) {
                const labelCell = document.createElement('div');
                labelCell.className = 'heatmap-cell heatmap-label';
                labelCell.textContent = dayNames[d];
                heatmapGrid.appendChild(labelCell);
                
                for (let h = 0; h < 24; h++) {
                    const cell = document.createElement('div');
                    cell.className = 'heatmap-cell';
                    const tir = heatmapTir[d][h];
                    
                    // Create styled tooltip
                    const tooltip = document.createElement('span');
                    tooltip.className = 'tooltip';
                    
                    const hourLabel = h.toString().padStart(2, '0') + ':00';
                    
                    if (tir === null) {
                        cell.style.background = 'rgba(255,255,255,0.05)';
                        tooltip.innerHTML = `<strong>${fullDayNames[d]}</strong> ${hourLabel}<br>No data`;
                    } else {
                        const tirVal = parseFloat(tir);
                        let color;
                        if (tirVal >= 80) {
                            color = `rgba(16, 185, 129, ${0.3 + (tirVal - 80) / 100})`;
                        } else if (tirVal >= 60) {
                            color = `rgba(234, 179, 8, ${0.5 + (tirVal - 60) / 100})`;
                        } else {
                            color = `rgba(239, 68, 68, ${0.4 + (60 - tirVal) / 150})`;
                        }
                        cell.style.background = color;
                        
                        const status = tirVal >= 70 ? '✓ Good' : tirVal >= 50 ? '⚠ Fair' : '✗ Needs work';
                        tooltip.innerHTML = `<strong>${fullDayNames[d]}</strong> ${hourLabel}<br>TIR: ${Math.round(tirVal)}%% ${status}`;
                    }
                    
                    cell.appendChild(tooltip);
                    heatmapGrid.appendChild(cell);
                }
            }
        }
        
        // Initial data (pre-filtered by Python for performance)
        const modalDayData = %(modal_day_json)s;
        const dailyStats = %(daily_stats_json)s;
        const dowStats = %(dow_stats_json)s;
        const histogramData = %(histogram_json)s;
        const heatmapTir = %(heatmap_json)s;
        const weeklyStats = %(weekly_stats_json)s;
        const tirData = %(tir_data_json)s;
        
        // Time in Range Pie Chart
        tirChart = new Chart(document.getElementById('tirPieChart'), {
            type: 'doughnut',
            data: {
                labels: ['Very Low', 'Low', 'In Range', 'High', 'Very High'],
                datasets: [{
                    data: [tirData.very_low, tirData.low, tirData.in_range, tirData.high, tirData.very_high],
                    backgroundColor: [colors.veryLow, colors.low, colors.inRange, colors.high, colors.veryHigh],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'right',
                        labels: { padding: 20 }
                    },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `${ctx.label}: ${ctx.parsed.toFixed(1)}%%`
                        }
                    }
                }
            }
        });
        
        // Modal Day Chart (with percentile bands)
        const modalHours = modalDayData.map(d => d.hour + ':00');
        const modalMean = modalDayData.map(d => d.mean);
        const modalMedian = modalDayData.map(d => d.median);
        const modalP10 = modalDayData.map(d => d.p10);
        const modalP90 = modalDayData.map(d => d.p90);
        const modalP25 = modalDayData.map(d => d.p25);
        const modalP75 = modalDayData.map(d => d.p75);
        
        modalChart = new Chart(document.getElementById('modalDayChart'), {
            type: 'line',
            data: {
                labels: modalHours,
                datasets: [
                    {
                        label: '90th Percentile',
                        data: modalP90,
                        borderColor: 'transparent',
                        backgroundColor: 'rgba(59, 130, 246, 0.1)',
                        fill: '+1',
                        pointRadius: 0,
                        order: 4
                    },
                    {
                        label: '10th Percentile',
                        data: modalP10,
                        borderColor: 'transparent',
                        backgroundColor: 'transparent',
                        fill: false,
                        pointRadius: 0,
                        order: 5
                    },
                    {
                        label: '75th Percentile',
                        data: modalP75,
                        borderColor: 'transparent',
                        backgroundColor: 'rgba(59, 130, 246, 0.2)',
                        fill: '+1',
                        pointRadius: 0,
                        order: 2
                    },
                    {
                        label: '25th Percentile',
                        data: modalP25,
                        borderColor: 'transparent',
                        backgroundColor: 'transparent',
                        fill: false,
                        pointRadius: 0,
                        order: 3
                    },
                    {
                        label: 'Median',
                        data: modalMedian,
                        borderColor: colors.info,
                        backgroundColor: colors.info,
                        borderWidth: 3,
                        fill: false,
                        pointRadius: 2,
                        tension: 0.3,
                        order: 1
                    },
                    {
                        label: 'Mean',
                        data: modalMean,
                        borderColor: colors.accent,
                        backgroundColor: colors.accent,
                        borderWidth: 2,
                        borderDash: [5, 5],
                        fill: false,
                        pointRadius: 0,
                        tension: 0.3,
                        order: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { 
                        position: 'top',
                        labels: { 
                            filter: (item) => ['Median', 'Mean'].includes(item.text)
                        }
                    },
                    annotation: {
                        annotations: {
                            targetLow: {
                                type: 'line',
                                yMin: thresholds.targetLow,
                                yMax: thresholds.targetLow,
                                borderColor: colors.inRange,
                                borderWidth: 1,
                                borderDash: [5, 5]
                            },
                            targetHigh: {
                                type: 'line',
                                yMin: thresholds.targetHigh,
                                yMax: thresholds.targetHigh,
                                borderColor: colors.inRange,
                                borderWidth: 1,
                                borderDash: [5, 5]
                            }
                        }
                    }
                },
                scales: {
                    y: {
                        title: { display: true, text: unit },
                        min: %(chart_min)s,
                        max: %(chart_max)s
                    }
                }
            }
        });
        
        // Daily Trend Chart
        dailyChart = new Chart(document.getElementById('dailyTrendChart'), {
            type: 'bar',
            data: {
                labels: dailyStats.map(d => d.date.slice(5)),
                datasets: [
                    {
                        type: 'line',
                        label: 'Average',
                        data: dailyStats.map(d => d.mean),
                        borderColor: colors.accent,
                        backgroundColor: colors.accent,
                        borderWidth: 2,
                        fill: false,
                        yAxisID: 'y',
                        pointRadius: 1,
                        tension: 0.3,
                        order: 0
                    },
                    {
                        type: 'bar',
                        label: 'TIR %%',
                        data: dailyStats.map(d => d.tir),
                        backgroundColor: dailyStats.map(d => 
                            d.tir >= 70 ? colors.inRange : d.tir >= 50 ? colors.low : colors.veryLow
                        ),
                        yAxisID: 'y1',
                        order: 1
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: { position: 'top' }
                },
                scales: {
                    y: {
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: unit }
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 100,
                        title: { display: true, text: 'TIR %%' },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
        
        // Day of Week Chart
        dowChart = new Chart(document.getElementById('dowChart'), {
            type: 'bar',
            data: {
                labels: dowStats.map(d => d.day.slice(0, 3)),
                datasets: [
                    {
                        label: 'Average Glucose',
                        data: dowStats.map(d => d.mean),
                        backgroundColor: colors.info,
                        yAxisID: 'y'
                    },
                    {
                        label: 'TIR %%',
                        data: dowStats.map(d => d.tir),
                        backgroundColor: dowStats.map(d => 
                            d.tir >= 70 ? colors.inRange : d.tir >= 50 ? colors.low : colors.veryLow
                        ),
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top' }
                },
                scales: {
                    y: {
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: unit }
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 100,
                        title: { display: true, text: 'TIR %%' },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
        
        // Histogram
        histChart = new Chart(document.getElementById('histogramChart'), {
            type: 'bar',
            data: {
                labels: histogramData.map(d => d.bin),
                datasets: [{
                    label: 'Readings',
                    data: histogramData.map(d => d.count),
                    backgroundColor: histogramData.map(d => {
                        const v = d.bin;
                        if (v < thresholds.urgentLow) return colors.veryLow;
                        if (v < thresholds.targetLow) return colors.low;
                        if (v <= thresholds.targetHigh) return colors.inRange;
                        if (v <= thresholds.urgentHigh) return colors.high;
                        return colors.veryHigh;
                    })
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false }
                },
                scales: {
                    x: { title: { display: true, text: unit } },
                    y: { title: { display: true, text: 'Number of Readings' } }
                }
            }
        });
        
        // Heatmap - use the same function for initial render
        updateHeatmap(heatmapTir);
        
        // Weekly Chart
        weeklyChart = new Chart(document.getElementById('weeklyChart'), {
            type: 'bar',
            data: {
                labels: weeklyStats.map(d => 'Week of ' + d.week.slice(5)),
                datasets: [
                    {
                        type: 'line',
                        label: 'Average',
                        data: weeklyStats.map(d => d.mean),
                        borderColor: colors.accent,
                        backgroundColor: colors.accent,
                        borderWidth: 2,
                        fill: false,
                        yAxisID: 'y',
                        pointRadius: 3,
                        tension: 0.3
                    },
                    {
                        type: 'bar',
                        label: 'TIR %%',
                        data: weeklyStats.map(d => d.tir),
                        backgroundColor: weeklyStats.map(d => 
                            d.tir >= 70 ? colors.inRange : d.tir >= 50 ? colors.low : colors.veryLow
                        ),
                        yAxisID: 'y1'
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { position: 'top' }
                },
                scales: {
                    y: {
                        type: 'linear',
                        position: 'left',
                        title: { display: true, text: unit }
                    },
                    y1: {
                        type: 'linear',
                        position: 'right',
                        min: 0,
                        max: 100,
                        title: { display: true, text: 'TIR %%' },
                        grid: { drawOnChartArea: false }
                    }
                }
            }
        });
        
        // Initialize date controls
        initDateControls();
        
        // Render alerts
        renderAlerts();
        
        // Function to render alerts
        function renderAlerts() {
            const container = document.getElementById('alertsContainer');
            const hiddenContainer = document.getElementById('hiddenAlerts');
            const expandBtn = document.getElementById('alertsExpand');
            const summaryDiv = document.getElementById('alertsSummary');
            const section = document.getElementById('alertsSection');
            
            if (!allAlerts || allAlerts.length === 0) {
                container.innerHTML = `
                    <div class="no-alerts">
                        <div class="no-alerts-icon">✅</div>
                        <div>No concerning patterns detected. Great job!</div>
                    </div>
                `;
                summaryDiv.innerHTML = '';
                return;
            }
            
            // Group and summarize alerts (returns max 10 most impactful)
            const summarized = summarizeAlerts(allAlerts);
            
            if (summarized.length === 0) {
                container.innerHTML = `
                    <div class="no-alerts">
                        <div class="no-alerts-icon">✅</div>
                        <div>No significant patterns detected. Keep up the good work!</div>
                    </div>
                `;
                summaryDiv.innerHTML = '';
                expandBtn.style.display = 'none';
                return;
            }
            
            // Count high priority only (don't show overwhelming counts)
            const highCount = summarized.filter(a => a.severity === 'high').length;
            
            // Render simple summary - just high priority if any
            let summaryHTML = '';
            if (highCount > 0) {
                summaryHTML = `<span class="alert-badge high">🔴 ${highCount} need${highCount === 1 ? 's' : ''} attention</span>`;
            } else {
                summaryHTML = `<span class="alert-badge medium">🟡 ${summarized.length} pattern${summarized.length === 1 ? '' : 's'} to review</span>`;
            }
            summaryDiv.innerHTML = summaryHTML;
            
            // Show top 5 alerts, hide rest (up to 5 more)
            const maxVisible = 5;
            const visibleAlerts = summarized.slice(0, maxVisible);
            const hiddenAlerts = summarized.slice(maxVisible);
            
            container.innerHTML = visibleAlerts.map(alert => renderAlertItem(alert)).join('');
            
            if (hiddenAlerts.length > 0) {
                hiddenContainer.innerHTML = hiddenAlerts.map(alert => renderAlertItem(alert)).join('');
                expandBtn.style.display = 'block';
                expandBtn.querySelector('button').textContent = `Show ${hiddenAlerts.length} more`;
            } else {
                expandBtn.style.display = 'none';
            }
        }
        
        function summarizeAlerts(alerts) {
            // Filter: require 3+ days minimum to be a real pattern
            const significantAlerts = alerts.filter(alert => {
                const days = alert.details?.unique_days || alert.details?.unique_weeks || 0;
                return days >= 3;
            });
            
            // Group alerts by time blocks and category
            const groups = {};
            
            significantAlerts.forEach(alert => {
                const key = getAlertGroupKey(alert);
                if (!groups[key]) {
                    groups[key] = {
                        alerts: [],
                        severity: alert.severity,
                        category: alert.category,
                        pattern: alert.pattern
                    };
                }
                groups[key].alerts.push(alert);
                // Upgrade severity if any alert in group is high
                if (alert.severity === 'high') {
                    groups[key].severity = 'high';
                }
            });
            
            // Create summarized alerts with impact scores
            const summarized = Object.entries(groups).map(([key, group]) => {
                let alert;
                if (group.alerts.length === 1) {
                    alert = { ...group.alerts[0] };
                } else {
                    alert = mergeAlerts(group);
                }
                
                // Calculate impact score: frequency × severity × consistency
                const occurrences = alert.details?.total_occurrences || alert.details?.occurrences || 0;
                const days = alert.details?.unique_days || alert.details?.unique_weeks || 1;
                const severityMultiplier = alert.severity === 'high' ? 3 : alert.severity === 'medium' ? 2 : 1;
                
                // Lows are more dangerous than highs
                const categoryMultiplier = alert.category === 'recurring_lows' ? 1.5 : 1;
                
                alert.impactScore = occurrences * severityMultiplier * categoryMultiplier * Math.sqrt(days);
                
                return alert;
            });
            
            // Sort by impact score (highest first)
            summarized.sort((a, b) => b.impactScore - a.impactScore);
            
            // Return only top 10 most impactful
            return summarized.slice(0, 10);
        }
        
        function getAlertGroupKey(alert) {
            const details = alert.details || {};
            const hour = details.hour;
            
            // Group by time block for time_of_day patterns
            if (alert.pattern === 'time_of_day' && hour !== undefined) {
                const block = getTimeBlock(hour);
                return `${alert.category}_${block}`;
            }
            
            // Group day_hour_combination by day + time block
            if (alert.pattern === 'day_hour_combination' && details.day && hour !== undefined) {
                const block = getTimeBlock(hour);
                return `${alert.category}_${details.day}_${block}`;
            }
            
            // Keep day_of_week separate
            if (alert.pattern === 'day_of_week') {
                return `${alert.category}_dow_${details.day}`;
            }
            
            // Default: unique key
            return `${alert.category}_${alert.pattern}_${JSON.stringify(details)}`;
        }
        
        function getTimeBlock(hour) {
            if (hour >= 5 && hour < 10) return 'morning';
            if (hour >= 10 && hour < 14) return 'midday';
            if (hour >= 14 && hour < 18) return 'afternoon';
            if (hour >= 18 && hour < 22) return 'evening';
            return 'overnight';
        }
        
        function mergeAlerts(group) {
            const alerts = group.alerts;
            const details = alerts[0].details || {};
            const category = group.category;
            
            // Calculate combined stats
            const totalOccurrences = alerts.reduce((sum, a) => sum + (a.details?.occurrences || 0), 0);
            const daysValues = alerts.map(a => a.details?.unique_days).filter(d => d !== undefined);
            const uniqueDays = daysValues.length > 0 ? Math.max(...daysValues) : null;
            const avgGlucose = Math.round(
                alerts.reduce((sum, a) => sum + (a.details?.avg_glucose || 0), 0) / alerts.length
            );
            
            // Get hours covered
            const hours = alerts.map(a => a.details?.hour).filter(h => h !== undefined).sort((a,b) => a-b);
            
            // Handle overnight wrap-around (22:00-04:00)
            let timeRange;
            const block = getTimeBlock(hours[0]);
            if (block === 'overnight' && hours.length > 1) {
                // Overnight spans across midnight, show it properly
                const lateHours = hours.filter(h => h >= 22);
                const earlyHours = hours.filter(h => h < 5);
                if (lateHours.length > 0 && earlyHours.length > 0) {
                    timeRange = `${String(Math.min(...lateHours)).padStart(2,'0')}:00-${String(Math.max(...earlyHours)).padStart(2,'0')}:00`;
                } else if (lateHours.length > 0) {
                    timeRange = `${String(Math.min(...lateHours)).padStart(2,'0')}:00-${String(Math.max(...lateHours)).padStart(2,'0')}:00`;
                } else {
                    timeRange = `${String(Math.min(...earlyHours)).padStart(2,'0')}:00-${String(Math.max(...earlyHours)).padStart(2,'0')}:00`;
                }
            } else {
                timeRange = hours.length > 1 
                    ? `${String(hours[0]).padStart(2,'0')}:00-${String(hours[hours.length-1]).padStart(2,'0')}:00`
                    : `${String(hours[0]).padStart(2,'0')}:00`;
            }
            
            // Build summary message
            const blockName = block.charAt(0).toUpperCase() + block.slice(1);
            const daysText = uniqueDays ? `${uniqueDays} days affected` : `${totalOccurrences} occurrences`;
            
            let message;
            if (category === 'recurring_lows') {
                message = `${blockName} lows (${timeRange}) - ${daysText}`;
            } else if (category === 'recurring_highs') {
                message = `${blockName} highs (${timeRange}) - ${daysText}`;
            } else {
                message = alerts[0].message;
            }
            
            return {
                severity: group.severity,
                category: category,
                pattern: 'grouped',
                message: message,
                details: {
                    total_occurrences: totalOccurrences,
                    unique_days: uniqueDays,
                    avg_glucose: avgGlucose,
                    unit: details.unit || 'mg/dL',
                    hours_covered: hours
                }
            };
        }
        
        function renderAlertItem(alert) {
            const icon = alert.severity === 'high' ? '🔴' : 
                       alert.severity === 'medium' ? '🟡' : '🔵';
            
            return `
                <div class="alert-item severity-${alert.severity}">
                    <div class="alert-icon">${icon}</div>
                    <div class="alert-content">
                        <div class="alert-message">${alert.message}</div>
                        <div class="alert-details">${formatAlertDetails(alert)}</div>
                    </div>
                </div>
            `;
        }
        
        let moreAlertsExpanded = false;
        function toggleMoreAlerts(event) {
            event.stopPropagation(); // Don't trigger section collapse
            const hiddenContainer = document.getElementById('hiddenAlerts');
            const btn = document.getElementById('alertsExpand').querySelector('button');
            moreAlertsExpanded = !moreAlertsExpanded;
            
            if (moreAlertsExpanded) {
                hiddenContainer.classList.add('expanded');
                btn.textContent = 'Show fewer';
            } else {
                hiddenContainer.classList.remove('expanded');
                const count = hiddenContainer.querySelectorAll('.alert-item').length;
                btn.textContent = `Show ${count} more`;
            }
        }
        
        function toggleAlertsSection() {
            const section = document.getElementById('alertsSection');
            section.classList.toggle('collapsed');
        }
        
        function formatAlertDetails(alert) {
            const details = alert.details;
            let parts = [];
            
            // Handle grouped alerts
            if (details.total_occurrences) {
                parts.push(`${details.total_occurrences} total occurrences`);
            } else if (details.occurrences) {
                parts.push(`${details.occurrences} occurrences`);
            }
            if (details.unique_days) {
                parts.push(`${details.unique_days} days`);
            }
            if (details.unique_weeks) {
                parts.push(`${details.unique_weeks} weeks`);
            }
            if (details.avg_glucose) {
                parts.push(`avg: ${details.avg_glucose} ${details.unit}`);
            }
            if (details.recent_tir !== undefined && details.older_tir !== undefined) {
                parts.push(`recent TIR: ${details.recent_tir}%%, previous: ${details.older_tir}%%`);
            }
            
            return parts.join(' • ');
        }
    </script>
</body>
</html>
'''
    
    # Calculate chart bounds
    if is_mmol:
        chart_min = 2
        chart_max = 20
    else:
        chart_min = 40
        chart_max = 350
    
    # Format the HTML
    html_content = html_template % {
        "first_date": first_date,
        "last_date": last_date,
        "days": days,
        "readings": len(rows),
        "unit": unit,
        "tir_in_range": tir_data["in_range"],
        "tir_very_low": tir_data["very_low"],
        "tir_low": tir_data["low"],
        "tir_high": tir_data["high"],
        "tir_very_high": tir_data["very_high"],
        "gmi": gmi,
        "cv": cv,
        "cv_status": "stable" if cv < 36 else "variable",
        "mean": convert_glucose(round(raw_mean, 1)),
        "urgent_low": convert_glucose(t["urgent_low"]),
        "target_low": convert_glucose(t["target_low"]),
        "target_low_minus": convert_glucose(t["target_low"] - 1),
        "target_high": convert_glucose(t["target_high"]),
        "target_high_plus": convert_glucose(t["target_high"] + 1),
        "urgent_high": convert_glucose(t["urgent_high"]),
        "modal_day_json": json.dumps(modal_day_data),
        "daily_stats_json": json.dumps(daily_stats),
        "dow_stats_json": json.dumps(dow_stats),
        "histogram_json": json.dumps(histogram_data),
        "heatmap_json": json.dumps(heatmap_tir),
        "weekly_stats_json": json.dumps(weekly_stats),
        "tir_data_json": json.dumps(tir_data),
        "chart_min": chart_min,
        "chart_max": chart_max,
        "generated_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "all_readings_json": json.dumps(all_readings_data),
        "is_mmol_js": "true" if is_mmol else "false",
        "initial_days": days,
        "alerts_json": json.dumps(alerts)
    }
    
    # Determine output path
    if output_path is None:
        output_path = SKILL_DIR / "nightscout_report.html"
    else:
        output_path = Path(output_path)
    
    # Write the file
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    return {
        "status": "success",
        "report": str(output_path),
        "days_analyzed": days,
        "readings": len(rows),
        "date_range": f"{first_date} to {last_date}"
    }


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

    # Query command - flexible pattern analysis
    query_parser = subparsers.add_parser(
        "query", help="Query data with filters (day of week, time range)"
    )
    query_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to analyze (default: 90)"
    )
    query_parser.add_argument(
        "--day", type=str,
        help="Day of week (e.g., Tuesday, or 0-6 where 0=Monday)"
    )
    query_parser.add_argument(
        "--hour-start", type=int, choices=range(24), metavar="H",
        help="Start hour for time window (0-23)"
    )
    query_parser.add_argument(
        "--hour-end", type=int, choices=range(24), metavar="H",
        help="End hour for time window (0-23)"
    )

    # Patterns command - automatic insight discovery
    patterns_parser = subparsers.add_parser(
        "patterns", help="Find interesting patterns (best/worst times, days, trends)"
    )
    patterns_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to analyze (default: 90)"
    )

    # Alerts command - detect concerning recurring patterns
    alerts_parser = subparsers.add_parser(
        "alerts", help="Show trend alerts for concerning patterns (recurring lows/highs)"
    )
    alerts_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to analyze (default: 90)"
    )
    alerts_parser.add_argument(
        "--min-occurrences", type=int, default=2,
        help="Minimum occurrences to trigger alert (default: 2)"
    )

    # Day command - view readings for a specific date
    day_parser = subparsers.add_parser(
        "day", help="View all readings for a specific date (e.g., today, yesterday, 2026-01-16)"
    )
    day_parser.add_argument(
        "date", type=str,
        help="Date to view: 'today', 'yesterday', '2026-01-16', or 'Jan 16'"
    )
    day_parser.add_argument(
        "--hour-start", type=int, choices=range(24), metavar="H",
        help="Start hour for time window (0-23)"
    )
    day_parser.add_argument(
        "--hour-end", type=int, choices=range(24), metavar="H",
        help="End hour for time window (0-23)"
    )

    # Worst command - find problem days
    worst_parser = subparsers.add_parser(
        "worst", help="Find worst days for glucose control (ranked by peak glucose)"
    )
    worst_parser.add_argument(
        "--days", type=int, default=21,
        help="Number of days to search (default: 21)"
    )
    worst_parser.add_argument(
        "--hour-start", type=int, choices=range(24), metavar="H",
        help="Start hour for time window (0-23)"
    )
    worst_parser.add_argument(
        "--hour-end", type=int, choices=range(24), metavar="H",
        help="End hour for time window (0-23)"
    )
    worst_parser.add_argument(
        "--limit", type=int, default=5,
        help="Number of worst days to show (default: 5)"
    )

    # Chart commands- visual terminal output
    chart_parser = subparsers.add_parser(
        "chart", help="Show visual charts in terminal (heatmap, day chart, or sparkline)"
    )
    chart_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to analyze (default: 90)"
    )
    chart_parser.add_argument(
        "--heatmap", action="store_true",
        help="Show weekly time-in-range heatmap"
    )
    chart_parser.add_argument(
        "--day", type=str,
        help="Show hourly chart for specific day (e.g., Saturday)"
    )
    chart_parser.add_argument(
        "--sparkline", action="store_true",
        help="Show compact sparkline of recent readings"
    )
    chart_parser.add_argument(
        "--week", action="store_true",
        help="Show sparklines for each day (one line per day)"
    )
    chart_parser.add_argument(
        "--hours", type=int, default=24,
        help="Hours of data for sparkline (default: 24)"
    )
    chart_parser.add_argument(
        "--date", type=str,
        help="Specific date for sparkline (e.g., today, yesterday, 2026-01-16)"
    )
    chart_parser.add_argument(
        "--hour-start", type=int, choices=range(24), metavar="H",
        help="Start hour for sparkline time window (0-23)"
    )
    chart_parser.add_argument(
        "--hour-end", type=int, choices=range(24), metavar="H",
        help="End hour for sparkline time window (0-23)"
    )
    chart_parser.add_argument(
        "--color", action="store_true",
        help="Use ANSI colors (for direct terminal use, not inside Copilot)"
    )

    # Report command - generate HTML report (like tally)
    report_parser = subparsers.add_parser(
        "report", help="Generate an interactive HTML report (like tally for diabetes)"
    )
    report_parser.add_argument(
        "--days", type=int, default=90,
        help="Number of days to include in report (default: 90)"
    )
    report_parser.add_argument(
        "--output", "-o", type=str,
        help="Output file path (default: nightscout_report.html in skill directory)"
    )
    report_parser.add_argument(
        "--open", action="store_true",
        help="Open the report in default browser after generating"
    )

    args = parser.parse_args()

    if args.command == "current":
        result = get_current_glucose()
    elif args.command == "analyze":
        result = analyze_cgm(args.days)
    elif args.command == "refresh":
        result = fetch_and_store(args.days)
    elif args.command == "query":
        day = args.day
        if day and day.isdigit():
            day = int(day)
        result = query_patterns(
            days=args.days,
            day_of_week=day,
            hour_start=args.hour_start,
            hour_end=args.hour_end
        )
    elif args.command == "patterns":
        result = find_patterns(args.days)
    elif args.command == "alerts":
        result = detect_trend_alerts(args.days, args.min_occurrences)
    elif args.command == "day":
        result = view_day(
            args.date,
            hour_start=args.hour_start,
            hour_end=args.hour_end
        )
    elif args.command == "worst":
        result = find_worst_days(
            days=args.days,
            hour_start=args.hour_start,
            hour_end=args.hour_end,
            limit=args.limit
        )
    elif args.command == "chart":
        use_color = args.color
        if args.week:
            show_sparkline_week(args.days, use_color=use_color)
        elif args.sparkline or args.date:
            show_sparkline(
                hours=args.hours,
                use_color=use_color,
                date_str=args.date,
                hour_start=args.hour_start,
                hour_end=args.hour_end
            )
        elif args.heatmap:
            show_heatmap(args.days, use_color=use_color)
        elif args.day:
            show_day_chart(args.day, args.days, use_color=use_color)
        else:
            show_heatmap(args.days, use_color=use_color)  # Default to heatmap
        sys.exit(0)
    elif args.command == "report":
        result = generate_html_report(
            days=args.days,
            output_path=args.output
        )
        if "error" not in result:
            print(f"Report generated: {result['report']}")
            print(f"  Period: {result['date_range']}")
            print(f"  Readings: {result['readings']}")
            
            # Open in browser if requested
            if args.open:
                import webbrowser
                webbrowser.open(f"file://{result['report']}")
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
