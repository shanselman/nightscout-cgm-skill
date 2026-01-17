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

def get_nightscout_settings():
    """Fetch settings from Nightscout server (cached)."""
    global _cached_settings
    if _cached_settings is not None:
        return _cached_settings
    
    try:
        resp = requests.get(f"{API_ROOT}/status.json", timeout=10)
        resp.raise_for_status()
        _cached_settings = resp.json().get("settings", {})
    except Exception:
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
    if not DB_PATH.exists():
        return {"error": "No database found. Run 'refresh' command first."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
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


def show_sparkline(hours=24, use_color=True):
    """
    Display a sparkline of recent glucose readings.
    Shows one character per reading (typically every 5 minutes).
    """
    if not DB_PATH.exists():
        print("No database found. Run 'refresh' command first.")
        return
    
    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_ms = int(cutoff.timestamp() * 1000)
    
    rows = conn.execute(
        "SELECT sgv, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
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
    
    # Get time range
    try:
        first_dt = datetime.fromisoformat(rows[0][1].replace("Z", "+00:00"))
        last_dt = datetime.fromisoformat(rows[-1][1].replace("Z", "+00:00"))
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
        print(f"\n{BOLD}Glucose Sparkline ({hours}h){RESET}")
        print(f"  {first_dt.strftime('%H:%M')} {spark_str} {last_dt.strftime('%H:%M')}")
        print(f"\n  {GREEN}█{RESET} In Range ({convert_glucose(t['target_low'])}-{convert_glucose(t['target_high'])} {get_unit_label()})  {YELLOW}█{RESET} Low/High  {RED}█{RESET} Urgent")
    else:
        # ASCII mode - no colors
        spark_str = make_sparkline(values)
        print(f"\nGlucose Sparkline ({hours}h)")
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


def show_heatmap(days=90, use_color=True):
    """Display a terminal heatmap of time-in-range by day and hour."""
    if not DB_PATH.exists():
        print("No database found. Run 'refresh' command first.")
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
    if not DB_PATH.exists():
        print("No database found. Run 'refresh' command first.")
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
    if not DB_PATH.exists():
        return {"error": "No database found. Run 'refresh' command first."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found. Run 'refresh' command first."}

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
    if not DB_PATH.exists():
        return {"error": "No database found. Run 'refresh' command first."}

    conn = sqlite3.connect(DB_PATH)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    cutoff_ms = int(cutoff.timestamp() * 1000)

    rows = conn.execute(
        "SELECT sgv, date_ms, date_string FROM readings WHERE date_ms >= ? AND sgv > 0 ORDER BY date_ms",
        (cutoff_ms,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"error": "No data found. Run 'refresh' command first."}

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

    # Chart commands - visual terminal output
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
        "--hours", type=int, default=24,
        help="Hours of data for sparkline (default: 24)"
    )
    chart_parser.add_argument(
        "--color", action="store_true",
        help="Use ANSI colors (for direct terminal use, not inside Copilot)"
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
    elif args.command == "chart":
        use_color = args.color
        if args.sparkline:
            show_sparkline(args.hours, use_color=use_color)
        elif args.heatmap:
            show_heatmap(args.days, use_color=use_color)
        elif args.day:
            show_day_chart(args.day, args.days, use_color=use_color)
        else:
            show_heatmap(args.days, use_color=use_color)  # Default to heatmap
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
