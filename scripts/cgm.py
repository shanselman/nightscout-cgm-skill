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

SKILL_DIR= Path(__file__).parent.parent
DB_PATH = SKILL_DIR / "cgm_data.db"


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
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    
    rows = conn.execute(
        "SELECT sgv, date_ms, date_string, direction FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()
    
    if not rows:
        return {"error": "No data found for the specified period."}
    
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
            --low: #f59e0b;
            --high: #f59e0b;
            --very-low: #ef4444;
            --very-high: #ef4444;
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
            <p class="subtitle">%(first_date)s to %(last_date)s (%(days)s days) • %(readings)s readings</p>
        </header>
        
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
        
        // Data from Python
        const modalDayData = %(modal_day_json)s;
        const dailyStats = %(daily_stats_json)s;
        const dowStats = %(dow_stats_json)s;
        const histogramData = %(histogram_json)s;
        const heatmapTir = %(heatmap_json)s;
        const weeklyStats = %(weekly_stats_json)s;
        const tirData = %(tir_data_json)s;
        const thresholds = {
            urgentLow: %(urgent_low)s,
            targetLow: %(target_low)s,
            targetHigh: %(target_high)s,
            urgentHigh: %(urgent_high)s
        };
        const unit = '%(unit)s';
        
        // Colors
        const colors = {
            veryLow: '#ef4444',
            low: '#f59e0b',
            inRange: '#10b981',
            high: '#f59e0b',
            veryHigh: '#ef4444',
            accent: '#e94560',
            info: '#3b82f6'
        };
        
        // Time in Range Pie Chart
        new Chart(document.getElementById('tirPieChart'), {
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
        
        new Chart(document.getElementById('modalDayChart'), {
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
        new Chart(document.getElementById('dailyTrendChart'), {
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
        new Chart(document.getElementById('dowChart'), {
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
        new Chart(document.getElementById('histogramChart'), {
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
        
        // Heatmap
        const dayNames = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
        const heatmapGrid = document.getElementById('heatmapGrid');
        
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
                
                if (tir === null) {
                    cell.style.background = 'rgba(255,255,255,0.05)';
                    cell.title = `${dayNames[d]} ${h}:00 - No data`;
                } else {
                    // Color scale: red (0%%) -> yellow (50%%) -> green (100%%)
                    let color;
                    if (tir >= 80) {
                        color = `rgba(16, 185, 129, ${0.3 + (tir - 80) / 100})`; // Green
                    } else if (tir >= 60) {
                        color = `rgba(245, 158, 11, ${0.5 + (tir - 60) / 100})`; // Yellow/Orange
                    } else {
                        color = `rgba(239, 68, 68, ${0.4 + (60 - tir) / 150})`; // Red
                    }
                    cell.style.background = color;
                    cell.title = `${dayNames[d]} ${h}:00 - ${tir.toFixed(0)}%% TIR`;
                }
                
                heatmapGrid.appendChild(cell);
            }
        }
        
        // Weekly Chart
        new Chart(document.getElementById('weeklyChart'), {
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
        "generated_date": datetime.now().strftime("%Y-%m-%d %H:%M")
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
