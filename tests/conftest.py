"""
Pytest configuration and shared fixtures for CGM tests.
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add scripts directory to path so we can import cgm
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture
def mock_env(monkeypatch):
    """Set up required environment variables."""
    monkeypatch.setenv("NIGHTSCOUT_URL", "https://test-nightscout.example.com/api/v1/entries.json")


@pytest.fixture
def mock_nightscout_settings():
    """Mock Nightscout settings response."""
    return {
        "settings": {
            "units": "mg/dl",
            "thresholds": {
                "bgLow": 55,
                "bgTargetBottom": 70,
                "bgTargetTop": 180,
                "bgHigh": 250
            }
        }
    }


@pytest.fixture
def mock_nightscout_settings_mmol():
    """Mock Nightscout settings for mmol/L users."""
    return {
        "settings": {
            "units": "mmol",
            "thresholds": {
                "bgLow": 55,
                "bgTargetBottom": 70,
                "bgTargetTop": 180,
                "bgHigh": 250
            }
        }
    }


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_cgm_data.db"
    conn = sqlite3.connect(db_path)
    conn.execute('''CREATE TABLE IF NOT EXISTS readings (
        id TEXT PRIMARY KEY,
        sgv INTEGER,
        date_ms INTEGER,
        date_string TEXT,
        trend INTEGER,
        direction TEXT,
        device TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS annotations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp_ms INTEGER NOT NULL,
        tag TEXT NOT NULL,
        note TEXT,
        created_at INTEGER NOT NULL
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_annotations_timestamp ON annotations(timestamp_ms)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_annotations_tag ON annotations(tag)')
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def populated_db(temp_db):
    """Create a database with sample glucose readings."""
    conn = sqlite3.connect(temp_db)
    
    # Generate 7 days of realistic glucose data (every 5 minutes)
    now = datetime.now(timezone.utc)
    readings = []
    
    # Simulate different patterns for different days
    for day_offset in range(7):
        day_start = now - timedelta(days=day_offset)
        
        for hour in range(24):
            for minute in range(0, 60, 5):
                dt = day_start.replace(hour=hour, minute=minute, second=0, microsecond=0)
                date_ms = int(dt.timestamp() * 1000)
                date_string = dt.isoformat().replace("+00:00", "Z")
                
                # Generate realistic glucose patterns
                base = 120
                
                # Higher after meals (breakfast ~7-9, lunch ~12-14, dinner ~18-20)
                if 7 <= hour <= 9:
                    base = 150 + (hour - 7) * 20  # Rising after breakfast
                elif 12 <= hour <= 14:
                    base = 160 + (hour - 12) * 15  # Rising after lunch
                elif 18 <= hour <= 20:
                    base = 145 + (hour - 18) * 10  # Rising after dinner
                elif 2 <= hour <= 5:
                    base = 95  # Lower overnight
                
                # Add some variation
                import random
                random.seed(date_ms)  # Reproducible randomness
                variation = random.randint(-20, 20)
                sgv = max(40, min(400, base + variation))
                
                # Determine trend based on next expected value
                if variation > 10:
                    direction = "FortyFiveUp"
                    trend = 4
                elif variation < -10:
                    direction = "FortyFiveDown"
                    trend = 6
                else:
                    direction = "Flat"
                    trend = 5
                
                readings.append((
                    f"entry_{date_ms}",
                    sgv,
                    date_ms,
                    date_string,
                    trend,
                    direction,
                    "test_device"
                ))
    
    conn.executemany(
        "INSERT OR REPLACE INTO readings (id, sgv, date_ms, date_string, trend, direction, device) VALUES (?, ?, ?, ?, ?, ?, ?)",
        readings
    )
    conn.commit()
    conn.close()
    
    return temp_db


@pytest.fixture
def sample_glucose_values():
    """Sample glucose values for testing statistics functions."""
    return [
        # Mix of values across all ranges
        45,   # very low
        52,   # very low
        60,   # low
        68,   # low
        72,   # in range (low end)
        95,   # in range
        110,  # in range
        120,  # in range
        140,  # in range
        165,  # in range
        175,  # in range (high end)
        185,  # high
        200,  # high
        220,  # high
        240,  # high
        260,  # very high
        290,  # very high
        320,  # very high
    ]


@pytest.fixture
def sample_readings_with_timestamps():
    """Sample readings with timestamps for time-based analysis."""
    now = datetime.now(timezone.utc)
    readings = []
    
    # Create readings over several days at different hours
    for day in range(3):
        for hour in [6, 9, 12, 15, 18, 21]:
            dt = (now - timedelta(days=day)).replace(hour=hour, minute=0)
            
            # Different values for different times
            if hour == 6:
                sgv = 100  # Fasting
            elif hour == 9:
                sgv = 160  # Post-breakfast
            elif hour == 12:
                sgv = 110  # Pre-lunch
            elif hour == 15:
                sgv = 180  # Post-lunch
            elif hour == 18:
                sgv = 105  # Pre-dinner
            else:
                sgv = 150  # Post-dinner
            
            readings.append({
                "sgv": sgv,
                "date_ms": int(dt.timestamp() * 1000),
                "date_string": dt.isoformat().replace("+00:00", "Z"),
                "direction": "Flat"
            })
    
    return readings


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for API calls."""
    with patch("requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def cgm_module(mock_env, monkeypatch, temp_db):
    """
    Import cgm module with mocked environment.
    This fixture handles the module's initialization safely.
    """
    # We need to patch before importing because cgm.py runs code at import time
    monkeypatch.setenv("NIGHTSCOUT_URL", "https://test.example.com/api/v1/entries.json")
    
    # Clear any cached module
    if "cgm" in sys.modules:
        del sys.modules["cgm"]
    
    # Patch the DB path before import
    with patch.dict("os.environ", {"NIGHTSCOUT_URL": "https://test.example.com/api/v1/entries.json"}):
        import cgm
        # Override DB_PATH for tests
        monkeypatch.setattr(cgm, "DB_PATH", temp_db)
        monkeypatch.setattr(cgm, "_cached_settings", None)
        yield cgm


# Helper functions for tests
def create_test_reading(sgv, hours_ago=0, direction="Flat"):
    """Create a test reading dict."""
    dt = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return {
        "_id": f"test_{int(dt.timestamp())}",
        "sgv": sgv,
        "date": int(dt.timestamp() * 1000),
        "dateString": dt.isoformat().replace("+00:00", "Z"),
        "trend": 5,
        "direction": direction,
        "device": "test",
        "type": "sgv"
    }


# ============================================================================
# Real Nightscout API Response Fixtures
# ============================================================================

@pytest.fixture
def real_nightscout_entries():
    """
    Load real Nightscout API response captured from a live system.
    This ensures our parser handles the actual API format correctly.
    """
    fixture_path = FIXTURES_DIR / "nightscout_24h_real.json"
    if not fixture_path.exists():
        pytest.skip("Real Nightscout fixture not available")
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def real_data_db(cgm_module, temp_db, real_nightscout_entries):
    """
    Create a test database populated with real Nightscout data.
    """
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    
    # Create table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id TEXT PRIMARY KEY,
            sgv INTEGER,
            date_ms INTEGER,
            date_string TEXT,
            trend INTEGER,
            direction TEXT,
            device TEXT
        )
    """)
    
    # Insert real data
    for entry in real_nightscout_entries:
        if entry.get("type") == "sgv" and entry.get("sgv"):
            cursor.execute("""
                INSERT OR REPLACE INTO readings 
                (id, sgv, date_ms, date_string, trend, direction, device)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                entry.get("_id"),
                entry.get("sgv"),
                entry.get("date"),
                entry.get("dateString"),
                entry.get("trend"),
                entry.get("direction"),
                entry.get("device")
            ))
    
    conn.commit()
    conn.close()
    
    return temp_db
