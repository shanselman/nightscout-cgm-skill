"""
Tests for profile management functionality.
"""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestProfileCreation:
    """Tests for creating profiles."""
    
    def test_profile_create_success(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile should succeed with valid inputs."""
        # Override profiles config location
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_create("kiddo", "https://nightscout.example.com")
        
        assert result["status"] == "success"
        assert result["profile"] == "kiddo"
        assert "nightscout.example.com" in result["url"]
        assert result["url"].endswith("/api/v1/entries.json")
    
    def test_profile_create_empty_name(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile with empty name should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_create("", "https://nightscout.example.com")
        assert "error" in result
    
    def test_profile_create_invalid_name(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile with invalid characters should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_create("test@profile!", "https://nightscout.example.com")
        assert "error" in result
    
    def test_profile_create_default_name(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile named 'default' should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_create("default", "https://nightscout.example.com")
        assert "error" in result
        assert "reserved" in result["error"].lower()
    
    def test_profile_create_duplicate(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile that already exists should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout1.example.com")
        result = cgm_module.profile_create("kiddo", "https://nightscout2.example.com")
        
        assert "error" in result
        assert "already exists" in result["error"].lower()
    
    def test_profile_create_empty_url(self, cgm_module, tmp_path, monkeypatch):
        """Creating a profile with empty URL should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_create("kiddo", "")
        assert "error" in result


class TestProfileSwitching:
    """Tests for switching profiles."""
    
    def test_profile_switch_success(self, cgm_module, tmp_path, monkeypatch):
        """Switching to an existing profile should succeed."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        # Create a profile first
        cgm_module.profile_create("kiddo", "https://nightscout.example.com")
        
        # Switch to it
        result = cgm_module.profile_switch("kiddo")
        
        assert result["status"] == "success"
        assert result["active_profile"] == "kiddo"
        assert "cgm_data_kiddo.db" in result["database"]
    
    def test_profile_switch_to_default(self, cgm_module, tmp_path, monkeypatch):
        """Switching to default profile should succeed."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_switch("default")
        
        assert result["status"] == "success"
        assert result["active_profile"] == "default"
    
    def test_profile_switch_nonexistent(self, cgm_module, tmp_path, monkeypatch):
        """Switching to a non-existent profile should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_switch("nonexistent")
        
        assert "error" in result
        assert "does not exist" in result["error"].lower()
    
    def test_profile_switch_empty_name(self, cgm_module, tmp_path, monkeypatch):
        """Switching with empty name should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_switch("")
        assert "error" in result


class TestProfileListing:
    """Tests for listing profiles."""
    
    def test_profile_list_default_only(self, cgm_module, tmp_path, monkeypatch):
        """Listing profiles when only default exists."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_list()
        
        assert "active_profile" in result
        assert "profiles" in result
        assert len(result["profiles"]) == 1
        assert result["profiles"][0]["name"] == "default"
        assert result["profiles"][0]["active"] is True
    
    def test_profile_list_multiple(self, cgm_module, tmp_path, monkeypatch):
        """Listing profiles with multiple profiles created."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        # Create profiles
        cgm_module.profile_create("kiddo", "https://nightscout1.example.com")
        cgm_module.profile_create("personal", "https://nightscout2.example.com")
        
        result = cgm_module.profile_list()
        
        assert len(result["profiles"]) == 3  # default + 2 custom
        profile_names = [p["name"] for p in result["profiles"]]
        assert "default" in profile_names
        assert "kiddo" in profile_names
        assert "personal" in profile_names
    
    def test_profile_list_shows_active(self, cgm_module, tmp_path, monkeypatch):
        """Listing profiles should show which one is active."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout.example.com")
        cgm_module.profile_switch("kiddo")
        
        result = cgm_module.profile_list()
        
        assert result["active_profile"] == "kiddo"
        
        for profile in result["profiles"]:
            if profile["name"] == "kiddo":
                assert profile["active"] is True
            else:
                assert profile["active"] is False


class TestProfileDeletion:
    """Tests for deleting profiles."""
    
    def test_profile_delete_success(self, cgm_module, tmp_path, monkeypatch):
        """Deleting an inactive profile should succeed."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout.example.com")
        result = cgm_module.profile_delete("kiddo")
        
        assert result["status"] == "success"
        assert result["profile"] == "kiddo"
    
    def test_profile_delete_active(self, cgm_module, tmp_path, monkeypatch):
        """Deleting the active profile should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout.example.com")
        cgm_module.profile_switch("kiddo")
        result = cgm_module.profile_delete("kiddo")
        
        assert "error" in result
        assert "active" in result["error"].lower()
    
    def test_profile_delete_default(self, cgm_module, tmp_path, monkeypatch):
        """Deleting the default profile should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_delete("default")
        
        assert "error" in result
        assert "default" in result["error"].lower()
    
    def test_profile_delete_nonexistent(self, cgm_module, tmp_path, monkeypatch):
        """Deleting a non-existent profile should fail."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        result = cgm_module.profile_delete("nonexistent")
        
        assert "error" in result
        assert "does not exist" in result["error"].lower()


class TestProfileIsolation:
    """Tests for profile database isolation."""
    
    def test_different_profiles_different_databases(self, cgm_module, tmp_path, monkeypatch):
        """Different profiles should use different database files."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout1.example.com")
        cgm_module.profile_create("personal", "https://nightscout2.example.com")
        
        db1 = cgm_module.get_db_path("kiddo")
        db2 = cgm_module.get_db_path("personal")
        db_default = cgm_module.get_db_path("default")
        
        assert db1 != db2
        assert db1 != db_default
        assert db2 != db_default
        assert "kiddo" in str(db1)
        assert "personal" in str(db2)
    
    def test_profile_url_isolation(self, cgm_module, tmp_path, monkeypatch):
        """Different profiles should use different URLs."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        cgm_module.profile_create("kiddo", "https://nightscout1.example.com")
        cgm_module.profile_create("personal", "https://nightscout2.example.com")
        
        url1 = cgm_module.get_profile_url("kiddo")
        url2 = cgm_module.get_profile_url("personal")
        
        assert url1 != url2
        assert "nightscout1" in url1
        assert "nightscout2" in url2


class TestBackwardCompatibility:
    """Tests for backward compatibility with existing setups."""
    
    def test_default_profile_uses_env_var(self, cgm_module, tmp_path, monkeypatch):
        """Default profile should fall back to NIGHTSCOUT_URL env var."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        monkeypatch.setenv("NIGHTSCOUT_URL", "https://env-nightscout.example.com")
        
        # Clear cached settings
        monkeypatch.setattr(cgm_module, "_cached_settings", None)
        
        url = cgm_module.get_profile_url("default")
        assert url == "https://env-nightscout.example.com"
    
    def test_default_profile_database(self, cgm_module, tmp_path, monkeypatch):
        """Default profile should use cgm_data.db."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        db_path = cgm_module.get_db_path("default")
        assert str(db_path).endswith("cgm_data.db")


class TestProfileCLI:
    """Tests for profile CLI commands."""
    
    def test_profile_create_cli(self, cgm_module, tmp_path, monkeypatch):
        """Test 'profile create' command via CLI."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        with patch.object(sys, "argv", [
            "cgm.py", "profile", "create", "test", "--url", "https://test.example.com"
        ]):
            with patch("builtins.print") as mock_print:
                try:
                    cgm_module.main()
                except SystemExit:
                    pass
                
                # Check that JSON was printed
                assert mock_print.called
                output = mock_print.call_args[0][0]
                result = json.loads(output)
                assert result["status"] == "success"
                assert result["profile"] == "test"
    
    def test_profile_list_cli(self, cgm_module, tmp_path, monkeypatch):
        """Test 'profile list' command via CLI."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        with patch.object(sys, "argv", ["cgm.py", "profile", "list"]):
            with patch("builtins.print") as mock_print:
                try:
                    cgm_module.main()
                except SystemExit:
                    pass
                
                assert mock_print.called
                output = mock_print.call_args[0][0]
                result = json.loads(output)
                assert "profiles" in result
    
    def test_profile_switch_cli(self, cgm_module, tmp_path, monkeypatch):
        """Test 'profile switch' command via CLI."""
        profiles_file = tmp_path / "test_profiles.json"
        monkeypatch.setattr(cgm_module, "PROFILES_CONFIG", profiles_file)
        
        # Create a profile first
        cgm_module.profile_create("test", "https://test.example.com")
        
        with patch.object(sys, "argv", ["cgm.py", "profile", "switch", "test"]):
            with patch("builtins.print") as mock_print:
                try:
                    cgm_module.main()
                except SystemExit:
                    pass
                
                assert mock_print.called
                output = mock_print.call_args[0][0]
                result = json.loads(output)
                assert result["status"] == "success"
                assert result["active_profile"] == "test"
