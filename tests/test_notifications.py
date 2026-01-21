"""
Tests for notification system.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

import pytest

# Add scripts directory to path
SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import notifications


class TestNotificationConfig:
    """Tests for NotificationConfig class."""
    
    def test_default_config(self):
        """Default configuration should be loaded."""
        with patch.object(Path, "exists", return_value=False):
            config = notifications.NotificationConfig()
            assert config.config["enabled"] is True
            assert "quiet_hours" in config.config
            assert "thresholds" in config.config
            assert "alert_levels" in config.config
    
    def test_load_existing_config(self, tmp_path):
        """Should load configuration from file."""
        config_file = tmp_path / "notifications.json"
        test_config = {"enabled": False, "quiet_hours": {"enabled": True}}
        
        with open(config_file, "w") as f:
            json.dump(test_config, f)
        
        with patch.object(notifications, "CONFIG_FILE", config_file):
            config = notifications.NotificationConfig()
            assert config.config["enabled"] is False
            assert config.config["quiet_hours"]["enabled"] is True
    
    def test_save_config(self, tmp_path):
        """Should save configuration to file."""
        config_dir = tmp_path / ".nightscout-cgm"
        config_file = config_dir / "notifications.json"
        
        with patch.object(notifications, "CONFIG_DIR", config_dir):
            with patch.object(notifications, "CONFIG_FILE", config_file):
                config = notifications.NotificationConfig()
                config.config["enabled"] = False
                config.save()
                
                assert config_file.exists()
                with open(config_file) as f:
                    saved = json.load(f)
                assert saved["enabled"] is False
    
    def test_is_quiet_hours_disabled(self):
        """Quiet hours disabled should return False."""
        config = notifications.NotificationConfig()
        config.config["quiet_hours"]["enabled"] = False
        assert config.is_quiet_hours() is False
    
    def test_is_quiet_hours_within_range(self):
        """Should detect when current time is within quiet hours."""
        config = notifications.NotificationConfig()
        config.config["quiet_hours"]["enabled"] = True
        
        # Test during quiet hours (22:00 - 07:00)
        config.config["quiet_hours"]["start"] = "22:00"
        config.config["quiet_hours"]["end"] = "07:00"
        
        # Mock current time to 23:00
        from datetime import time
        with patch("notifications.datetime") as mock_dt:
            mock_dt.now.return_value.time.return_value = time(23, 0)
            assert config.is_quiet_hours() is True
    
    def test_is_quiet_hours_outside_range(self):
        """Should detect when current time is outside quiet hours."""
        config = notifications.NotificationConfig()
        config.config["quiet_hours"]["enabled"] = True
        config.config["quiet_hours"]["start"] = "22:00"
        config.config["quiet_hours"]["end"] = "07:00"
        
        # Mock current time to 10:00 (outside quiet hours)
        from datetime import time
        with patch("notifications.datetime") as mock_dt:
            mock_dt.now.return_value.time.return_value = time(10, 0)
            assert config.is_quiet_hours() is False


class TestNotificationManager:
    """Tests for NotificationManager class."""
    
    def test_init_without_plyer(self):
        """Should initialize gracefully without plyer."""
        with patch.dict("sys.modules", {"plyer": None}):
            manager = notifications.NotificationManager()
            assert manager._plyer_available is False
    
    def test_send_when_disabled(self):
        """Should not send notifications when disabled."""
        config = notifications.NotificationConfig()
        config.config["enabled"] = False
        
        manager = notifications.NotificationManager(config)
        # Should not raise an error
        manager.send("Test", "Message", "info")
    
    def test_send_during_quiet_hours_info(self):
        """Should not send info notifications during quiet hours."""
        config = notifications.NotificationConfig()
        config.config["enabled"] = True
        config.config["quiet_hours"]["enabled"] = True
        config.config["quiet_hours"]["start"] = "22:00"
        config.config["quiet_hours"]["end"] = "07:00"
        
        manager = notifications.NotificationManager(config)
        
        from datetime import time
        with patch("notifications.datetime") as mock_dt:
            mock_dt.now.return_value.time.return_value = time(23, 0)
            # Should not send
            with patch.object(manager, "_send_terminal") as mock_terminal:
                manager.send("Test", "Message", "info")
                mock_terminal.assert_not_called()
    
    def test_send_during_quiet_hours_urgent(self):
        """Should send urgent notifications even during quiet hours."""
        config = notifications.NotificationConfig()
        config.config["enabled"] = True
        config.config["quiet_hours"]["enabled"] = True
        config.config["quiet_hours"]["start"] = "22:00"
        config.config["quiet_hours"]["end"] = "07:00"
        config.config["alert_levels"]["urgent"]["terminal"] = True
        
        manager = notifications.NotificationManager(config)
        
        from datetime import time
        with patch("notifications.datetime") as mock_dt:
            mock_dt.now.return_value.time.return_value = time(23, 0)
            # Should send urgent even during quiet hours
            with patch.object(manager, "_send_terminal") as mock_terminal:
                manager.send("Test", "Message", "urgent")
                mock_terminal.assert_called_once()
    
    def test_send_terminal(self, capsys):
        """Should send terminal notifications."""
        manager = notifications.NotificationManager()
        manager._send_terminal("Test Title", "Test message", "warning")
        
        captured = capsys.readouterr()
        assert "Test Title" in captured.err
        assert "Test message" in captured.err
        assert "[WARNING]" in captured.err
    
    def test_play_sound(self, capsys):
        """Should play bell sound."""
        manager = notifications.NotificationManager()
        manager._play_sound()
        
        captured = capsys.readouterr()
        assert "\a" in captured.err


class TestPatternDetector:
    """Tests for PatternDetector class."""
    
    def test_check_prolonged_high_no_readings(self):
        """Should return None with no readings."""
        detector = notifications.PatternDetector()
        result = detector.check_prolonged_high([])
        assert result is None
    
    def test_check_prolonged_high_detected(self):
        """Should detect prolonged high glucose."""
        detector = notifications.PatternDetector()
        
        # Create readings with high glucose for 2+ hours
        now = datetime.now(timezone.utc)
        readings = []
        for i in range(25):  # 25 readings = 2 hours at 5-min intervals
            dt = now - timedelta(minutes=i * 5)
            readings.append({
                "sgv": 200,  # High
                "date_ms": int(dt.timestamp() * 1000)
            })
        
        result = detector.check_prolonged_high(readings)
        assert result is not None
        assert result["type"] == "prolonged_high"
        assert result["level"] == "warning"
        assert "2 Hours" in result["title"]
    
    def test_check_prolonged_high_not_detected(self):
        """Should not detect when glucose is normal."""
        detector = notifications.PatternDetector()
        
        now = datetime.now(timezone.utc)
        readings = []
        for i in range(25):
            dt = now - timedelta(minutes=i * 5)
            readings.append({
                "sgv": 120,  # Normal
                "date_ms": int(dt.timestamp() * 1000)
            })
        
        result = detector.check_prolonged_high(readings)
        assert result is None
    
    def test_check_overnight_low_detected(self):
        """Should detect overnight low glucose."""
        detector = notifications.PatternDetector()
        
        # Create reading at 3 AM with low glucose
        now = datetime.now(timezone.utc).replace(hour=3, minute=0)
        readings = [
            {
                "sgv": 60,  # Low
                "date_ms": int(now.timestamp() * 1000)
            }
        ]
        
        result = detector.check_overnight_low(readings)
        assert result is not None
        assert result["type"] == "overnight_low"
        assert "Overnight Low" in result["title"]
    
    def test_check_overnight_low_not_detected(self):
        """Should not detect when no overnight lows."""
        detector = notifications.PatternDetector()
        
        # Normal daytime reading
        now = datetime.now(timezone.utc).replace(hour=14, minute=0)
        readings = [
            {
                "sgv": 120,  # Normal
                "date_ms": int(now.timestamp() * 1000)
            }
        ]
        
        result = detector.check_overnight_low(readings)
        assert result is None
    
    def test_generate_weekly_summary(self):
        """Should generate weekly summary."""
        detector = notifications.PatternDetector()
        
        stats = {
            "time_in_range": {
                "in_range_pct": 75.0,
                "low_pct": 5.0,
                "high_pct": 20.0
            },
            "statistics": {
                "mean": 140
            },
            "gmi_estimated_a1c": 6.5
        }
        
        result = detector.generate_weekly_summary(stats)
        assert result["type"] == "weekly_summary"
        assert result["level"] == "info"
        assert "75.0%" in result["message"]
        assert "140" in result["message"]


class TestConfigFunctions:
    """Tests for module-level configuration functions."""
    
    def test_load_config(self):
        """Should load configuration."""
        config = notifications.load_config()
        assert isinstance(config, notifications.NotificationConfig)
    
    def test_save_config(self, tmp_path):
        """Should save configuration."""
        config_dir = tmp_path / ".nightscout-cgm"
        config_file = config_dir / "notifications.json"
        
        with patch.object(notifications, "CONFIG_DIR", config_dir):
            with patch.object(notifications, "CONFIG_FILE", config_file):
                test_config = {"enabled": False}
                notifications.save_config(test_config)
                
                assert config_file.exists()
    
    def test_get_config_path(self):
        """Should return config file path."""
        path = notifications.get_config_path()
        assert "notifications.json" in path
    
    def test_create_default_config(self, tmp_path):
        """Should create default configuration file."""
        config_dir = tmp_path / ".nightscout-cgm"
        config_file = config_dir / "notifications.json"
        
        with patch.object(notifications, "CONFIG_DIR", config_dir):
            with patch.object(notifications, "CONFIG_FILE", config_file):
                config = notifications.create_default_config()
                
                assert config_file.exists()
                assert config["enabled"] is True
