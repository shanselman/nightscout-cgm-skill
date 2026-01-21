"""
Tests for daemon functionality.
"""
import os
import sys
import time
import json
import signal
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call


class TestDaemonConfig:
    """Tests for daemon configuration management."""
    
    def test_read_default_config(self, cgm_module, monkeypatch):
        """Should return default config if file doesn't exist."""
        fake_config_path = Path("/tmp/nonexistent_config.json")
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", fake_config_path)
        
        config = cgm_module.read_daemon_config()
        
        assert config["interval_minutes"] == 5
        assert config["days_to_fetch"] == 90
    
    def test_write_and_read_config(self, cgm_module, tmp_path, monkeypatch):
        """Should write and read config correctly."""
        config_file = tmp_path / "daemon_config.json"
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", config_file)
        
        test_config = {
            "interval_minutes": 10,
            "days_to_fetch": 30
        }
        
        cgm_module.write_daemon_config(test_config)
        read_config = cgm_module.read_daemon_config()
        
        assert read_config["interval_minutes"] == 10
        assert read_config["days_to_fetch"] == 30
    
    def test_read_config_with_missing_keys(self, cgm_module, tmp_path, monkeypatch):
        """Should add default values for missing keys."""
        config_file = tmp_path / "daemon_config.json"
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", config_file)
        
        # Write partial config
        with open(config_file, 'w') as f:
            json.dump({"interval_minutes": 15}, f)
        
        config = cgm_module.read_daemon_config()
        
        assert config["interval_minutes"] == 15
        assert config["days_to_fetch"] == 90  # Default value


class TestDaemonStatus:
    """Tests for daemon status checking."""
    
    def test_is_daemon_running_no_pid_file(self, cgm_module, tmp_path, monkeypatch):
        """Should return False if PID file doesn't exist."""
        pid_file = tmp_path / "nonexistent.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        assert cgm_module.is_daemon_running() is False
    
    def test_is_daemon_running_with_valid_pid(self, cgm_module, tmp_path, monkeypatch):
        """Should return True if PID file exists and process is running."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        # Write current process PID (which is definitely running)
        current_pid = os.getpid()
        with open(pid_file, 'w') as f:
            f.write(str(current_pid))
        
        assert cgm_module.is_daemon_running() is True
    
    def test_is_daemon_running_with_stale_pid(self, cgm_module, tmp_path, monkeypatch):
        """Should clean up stale PID file and return False."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        # Write a PID that definitely doesn't exist
        with open(pid_file, 'w') as f:
            f.write("999999")
        
        assert cgm_module.is_daemon_running() is False
        assert not pid_file.exists()  # Should clean up stale file
    
    def test_get_daemon_status_stopped(self, cgm_module, tmp_path, monkeypatch):
        """Should return stopped status when daemon is not running."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        status = cgm_module.get_daemon_status()
        
        assert status["status"] == "stopped"
        assert "not running" in status["message"]
    
    def test_get_daemon_status_running(self, cgm_module, tmp_path, monkeypatch):
        """Should return running status with details."""
        pid_file = tmp_path / "daemon.pid"
        config_file = tmp_path / "daemon_config.json"
        log_file = tmp_path / "daemon.log"
        
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", config_file)
        monkeypatch.setattr(cgm_module, "DAEMON_LOG_FILE", log_file)
        
        # Setup running daemon
        current_pid = os.getpid()
        with open(pid_file, 'w') as f:
            f.write(str(current_pid))
        
        with open(config_file, 'w') as f:
            json.dump({"interval_minutes": 10, "days_to_fetch": 30}, f)
        
        with open(log_file, 'w') as f:
            f.write("[2026-01-21 10:30:00] Started daemon\n")
        
        status = cgm_module.get_daemon_status()
        
        assert status["status"] == "running"
        assert status["pid"] == current_pid
        assert status["interval_minutes"] == 10
        assert status["days_to_fetch"] == 30
        assert status["last_sync"] == "2026-01-21 10:30:00"


class TestDaemonLogging:
    """Tests for daemon logging."""
    
    def test_log_daemon(self, cgm_module, tmp_path, monkeypatch):
        """Should write log messages with timestamp."""
        log_file = tmp_path / "daemon.log"
        monkeypatch.setattr(cgm_module, "DAEMON_LOG_FILE", log_file)
        
        cgm_module.log_daemon("Test message")
        
        assert log_file.exists()
        content = log_file.read_text()
        assert "Test message" in content
        assert "[" in content  # Has timestamp
    
    def test_log_daemon_appends(self, cgm_module, tmp_path, monkeypatch):
        """Should append to existing log file."""
        log_file = tmp_path / "daemon.log"
        monkeypatch.setattr(cgm_module, "DAEMON_LOG_FILE", log_file)
        
        cgm_module.log_daemon("First message")
        cgm_module.log_daemon("Second message")
        
        content = log_file.read_text()
        assert "First message" in content
        assert "Second message" in content


class TestDaemonStart:
    """Tests for starting daemon."""
    
    def test_start_daemon_already_running(self, cgm_module, tmp_path, monkeypatch):
        """Should return error if daemon is already running."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        # Make it think daemon is running
        with open(pid_file, 'w') as f:
            f.write(str(os.getpid()))
        
        result = cgm_module.start_daemon()
        
        assert result["status"] == "error"
        assert "already running" in result["message"]
    
    def test_start_daemon_creates_config(self, cgm_module, tmp_path, monkeypatch):
        """Should create config file with provided settings."""
        pid_file = tmp_path / "daemon.pid"
        config_file = tmp_path / "daemon_config.json"
        
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", config_file)
        
        # Mock os.fork to avoid actually forking
        with patch.object(os, "fork") as mock_fork:
            mock_fork.return_value = 1234  # Parent process
            
            result = cgm_module.start_daemon(interval_minutes=15, days=60)
        
        assert result["status"] == "success"
        assert result["interval_minutes"] == 15
        assert result["days_to_fetch"] == 60
        
        # Check config file was created
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert config["interval_minutes"] == 15
        assert config["days_to_fetch"] == 60


class TestDaemonStop:
    """Tests for stopping daemon."""
    
    def test_stop_daemon_not_running(self, cgm_module, tmp_path, monkeypatch):
        """Should return error if daemon is not running."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        result = cgm_module.stop_daemon()
        
        assert result["status"] == "error"
        assert "not running" in result["message"]
    
    def test_stop_daemon_success(self, cgm_module, tmp_path, monkeypatch):
        """Should stop daemon and clean up PID file."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        # Create a dummy PID file with current process
        # We can't actually kill ourselves, so we'll mock os.kill
        test_pid = 12345
        with open(pid_file, 'w') as f:
            f.write(str(test_pid))
        
        with patch.object(os, "kill") as mock_kill:
            result = cgm_module.stop_daemon()
        
        assert result["status"] == "success"
        assert str(test_pid) in result["message"]
        # Should be called twice: once with signal 0 (check if exists), once with SIGTERM
        assert mock_kill.call_count == 2
        mock_kill.assert_any_call(test_pid, signal.SIGTERM)


class TestDaemonCLI:
    """Tests for daemon CLI commands."""
    
    def test_daemon_start_command(self, cgm_module, tmp_path, monkeypatch):
        """'daemon start' command should work."""
        pid_file = tmp_path / "daemon.pid"
        config_file = tmp_path / "daemon_config.json"
        
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        monkeypatch.setattr(cgm_module, "DAEMON_CONFIG_FILE", config_file)
        
        with patch.object(os, "fork", return_value=1234):
            with patch.object(sys, "argv", ["cgm.py", "daemon", "start", "--interval", "10"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
        
        # Check config was created
        assert config_file.exists()
        config = json.loads(config_file.read_text())
        assert config["interval_minutes"] == 10
    
    def test_daemon_stop_command(self, cgm_module, tmp_path, monkeypatch):
        """'daemon stop' command should work."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        # Create PID file
        with open(pid_file, 'w') as f:
            f.write("12345")
        
        with patch.object(os, "kill"):
            with patch.object(sys, "argv", ["cgm.py", "daemon", "stop"]):
                with patch("builtins.print"):
                    try:
                        cgm_module.main()
                    except SystemExit:
                        pass
    
    def test_daemon_status_command(self, cgm_module, tmp_path, monkeypatch):
        """'daemon status' command should work."""
        pid_file = tmp_path / "daemon.pid"
        monkeypatch.setattr(cgm_module, "DAEMON_PID_FILE", pid_file)
        
        with patch.object(sys, "argv", ["cgm.py", "daemon", "status"]):
            with patch("builtins.print"):
                try:
                    cgm_module.main()
                except SystemExit:
                    pass
