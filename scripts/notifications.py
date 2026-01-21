#!/usr/bin/env python3
"""
Notification system for Nightscout CGM alerts.
Supports cross-platform desktop notifications and terminal alerts.
"""
import json
import os
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Dict, List, Optional


# Configuration file location
CONFIG_DIR = Path.home() / ".nightscout-cgm"
CONFIG_FILE = CONFIG_DIR / "notifications.json"

# Default configuration
DEFAULT_CONFIG = {
    "enabled": True,
    "quiet_hours": {
        "enabled": False,
        "start": "22:00",
        "end": "07:00"
    },
    "thresholds": {
        "prolonged_high_hours": 2,
        "prolonged_high_threshold": 180,
        "overnight_low_threshold": 70,
        "overnight_hours_start": 22,
        "overnight_hours_end": 6
    },
    "alert_levels": {
        "info": {
            "desktop": True,
            "terminal": True,
            "sound": False
        },
        "warning": {
            "desktop": True,
            "terminal": True,
            "sound": True
        },
        "urgent": {
            "desktop": True,
            "terminal": True,
            "sound": True
        }
    },
    "weekly_summary": {
        "enabled": True,
        "day_of_week": "Sunday",
        "hour": 9
    }
}


class NotificationConfig:
    """Manage notification configuration."""
    
    def __init__(self):
        self.config = self._load_config()
    
    def _load_config(self) -> dict:
        """Load configuration from file or create default."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    config = json.load(f)
                # Merge with defaults to ensure all keys exist
                return self._merge_config(DEFAULT_CONFIG.copy(), config)
            except (json.JSONDecodeError, IOError):
                return DEFAULT_CONFIG.copy()
        return DEFAULT_CONFIG.copy()
    
    def _merge_config(self, default: dict, user: dict) -> dict:
        """Recursively merge user config with defaults."""
        for key, value in user.items():
            if key in default and isinstance(default[key], dict) and isinstance(value, dict):
                default[key] = self._merge_config(default[key], value)
            else:
                default[key] = value
        return default
    
    def save(self):
        """Save configuration to file."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self.config, f, indent=2)
    
    def is_quiet_hours(self) -> bool:
        """Check if current time is within quiet hours."""
        if not self.config["quiet_hours"]["enabled"]:
            return False
        
        now = datetime.now().time()
        start = time.fromisoformat(self.config["quiet_hours"]["start"])
        end = time.fromisoformat(self.config["quiet_hours"]["end"])
        
        if start <= end:
            return start <= now <= end
        else:
            # Quiet hours span midnight
            return now >= start or now <= end
    
    def get(self, key: str, default=None):
        """Get configuration value."""
        return self.config.get(key, default)


class NotificationManager:
    """Manage sending notifications across platforms."""
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
        self._plyer_available = False
        self._init_plyer()
    
    def _init_plyer(self):
        """Initialize plyer for desktop notifications."""
        try:
            from plyer import notification as plyer_notification
            self._plyer_notification = plyer_notification
            self._plyer_available = True
        except ImportError:
            self._plyer_available = False
    
    def send(self, title: str, message: str, level: str = "info"):
        """
        Send a notification.
        
        Args:
            title: Notification title
            message: Notification message
            level: Alert level (info, warning, urgent)
        """
        if not self.config.config["enabled"]:
            return
        
        if self.config.is_quiet_hours() and level == "info":
            return
        
        alert_config = self.config.config["alert_levels"].get(level, {})
        
        # Send desktop notification
        if alert_config.get("desktop", False):
            self._send_desktop(title, message, level)
        
        # Send terminal notification
        if alert_config.get("terminal", False):
            self._send_terminal(title, message, level)
        
        # Play sound (bell)
        if alert_config.get("sound", False):
            self._play_sound()
    
    def _send_desktop(self, title: str, message: str, level: str):
        """Send desktop notification."""
        if not self._plyer_available:
            return
        
        try:
            # Map level to timeout
            timeout_map = {
                "info": 5,
                "warning": 10,
                "urgent": 15
            }
            timeout = timeout_map.get(level, 5)
            
            self._plyer_notification.notify(
                title=title,
                message=message,
                app_name="Nightscout CGM",
                timeout=timeout
            )
        except Exception:
            # Silently fail if notification doesn't work
            pass
    
    def _send_terminal(self, title: str, message: str, level: str):
        """Send terminal notification with colors."""
        # Color codes
        colors = {
            "info": "\033[94m",      # Blue
            "warning": "\033[93m",   # Yellow
            "urgent": "\033[91m",    # Red
            "reset": "\033[0m",
            "bold": "\033[1m"
        }
        
        color = colors.get(level, colors["info"])
        
        # Format message
        separator = "=" * 60
        output = f"\n{separator}\n"
        output += f"{colors['bold']}{color}[{level.upper()}]{colors['reset']} "
        output += f"{colors['bold']}{title}{colors['reset']}\n"
        output += f"{message}\n"
        output += f"{separator}\n"
        
        print(output, file=sys.stderr)
    
    def _play_sound(self):
        """Play system bell."""
        print("\a", end="", file=sys.stderr)


class PatternDetector:
    """Detect concerning patterns in CGM data."""
    
    def __init__(self, config: Optional[NotificationConfig] = None):
        self.config = config or NotificationConfig()
    
    def check_prolonged_high(self, readings: List[dict]) -> Optional[Dict]:
        """
        Check for prolonged high glucose.
        
        Args:
            readings: List of readings (newest first) with 'sgv' and 'date_ms'
        
        Returns:
            Alert dict if pattern detected, None otherwise
        """
        if not readings:
            return None
        
        threshold = self.config.config["thresholds"]["prolonged_high_threshold"]
        hours = self.config.config["thresholds"]["prolonged_high_hours"]
        
        # Convert hours to milliseconds
        hours_ms = hours * 60 * 60 * 1000
        
        # Check if all recent readings are high
        now = readings[0]["date_ms"]
        high_count = 0
        total_count = 0
        
        for reading in readings:
            age_ms = now - reading["date_ms"]
            if age_ms > hours_ms:
                break
            
            total_count += 1
            if reading["sgv"] > threshold:
                high_count += 1
        
        # Need at least 80% of readings to be high
        if total_count > 0 and (high_count / total_count) >= 0.8:
            avg_glucose = sum(r["sgv"] for r in readings[:total_count]) / total_count
            return {
                "type": "prolonged_high",
                "level": "warning",
                "title": f"High Glucose for {hours} Hours",
                "message": f"Your glucose has been above {threshold} mg/dL for approximately {hours} hours. Average: {avg_glucose:.0f} mg/dL",
                "data": {
                    "hours": hours,
                    "threshold": threshold,
                    "average": avg_glucose,
                    "readings_count": total_count
                }
            }
        
        return None
    
    def check_overnight_low(self, readings: List[dict]) -> Optional[Dict]:
        """
        Check for unusual overnight lows.
        
        Args:
            readings: List of readings with 'sgv', 'date_ms'
        
        Returns:
            Alert dict if pattern detected, None otherwise
        """
        if not readings:
            return None
        
        from datetime import datetime, timezone
        
        threshold = self.config.config["thresholds"]["overnight_low_threshold"]
        start_hour = self.config.config["thresholds"]["overnight_hours_start"]
        end_hour = self.config.config["thresholds"]["overnight_hours_end"]
        
        # Filter readings to overnight period (last night)
        overnight_readings = []
        for reading in readings:
            dt = datetime.fromtimestamp(reading["date_ms"] / 1000, tz=timezone.utc)
            hour = dt.hour
            
            # Check if in overnight window
            if start_hour <= end_hour:
                is_overnight = start_hour <= hour < end_hour
            else:
                is_overnight = hour >= start_hour or hour < end_hour
            
            if is_overnight and reading["sgv"] < threshold:
                overnight_readings.append(reading)
        
        # If we found low readings overnight
        if overnight_readings:
            min_reading = min(r["sgv"] for r in overnight_readings)
            count = len(overnight_readings)
            
            return {
                "type": "overnight_low",
                "level": "warning" if min_reading >= 55 else "urgent",
                "title": "Overnight Low Detected",
                "message": f"Detected {count} low reading(s) overnight. Minimum: {min_reading} mg/dL",
                "data": {
                    "min_glucose": min_reading,
                    "count": count,
                    "threshold": threshold
                }
            }
        
        return None
    
    def generate_weekly_summary(self, stats: dict) -> Dict:
        """
        Generate a weekly summary notification.
        
        Args:
            stats: Statistics dict from analyze_cgm
        
        Returns:
            Alert dict with summary
        """
        tir = stats.get("time_in_range", {})
        in_range_pct = tir.get("in_range_pct", 0)
        avg_glucose = stats.get("statistics", {}).get("mean", 0)
        gmi = stats.get("gmi_estimated_a1c", 0)
        
        # Determine level based on performance
        if in_range_pct >= 70:
            level = "info"
            emoji = "🎉"
        elif in_range_pct >= 50:
            level = "info"
            emoji = "📊"
        else:
            level = "warning"
            emoji = "⚠️"
        
        message = f"{emoji} Weekly CGM Summary\n\n"
        message += f"Time in Range: {in_range_pct:.1f}%\n"
        message += f"Average Glucose: {avg_glucose:.0f} mg/dL\n"
        message += f"Estimated A1C (GMI): {gmi:.1f}%\n"
        message += f"\nLow: {tir.get('low_pct', 0):.1f}% | "
        message += f"High: {tir.get('high_pct', 0):.1f}%"
        
        return {
            "type": "weekly_summary",
            "level": level,
            "title": "Weekly CGM Summary",
            "message": message,
            "data": stats
        }


def load_config() -> NotificationConfig:
    """Load notification configuration."""
    return NotificationConfig()


def save_config(config: dict):
    """Save notification configuration."""
    cfg = NotificationConfig()
    cfg.config = config
    cfg.save()


def get_config_path() -> str:
    """Get the path to the configuration file."""
    return str(CONFIG_FILE)


def create_default_config():
    """Create default configuration file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config = NotificationConfig()
    config.save()
    return config.config
