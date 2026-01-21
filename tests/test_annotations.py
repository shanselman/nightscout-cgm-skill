"""
Tests for annotation functionality.
"""
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class TestAnnotationDatabase:
    """Tests for annotation database schema."""
    
    def test_creates_annotations_table(self, cgm_module, tmp_path):
        """Database should have annotations table with correct schema."""
        db_path = tmp_path / "test_db.db"
        with patch.object(cgm_module, "DB_PATH", db_path):
            conn = cgm_module.create_database()
            
            # Check table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='annotations'"
            )
            assert cursor.fetchone() is not None
            
            # Check columns
            cursor = conn.execute("PRAGMA table_info(annotations)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
            assert "id" in columns
            assert "timestamp_ms" in columns
            assert "tag" in columns
            assert "note" in columns
            assert "created_at" in columns
            
            conn.close()
    
    def test_has_indexes(self, cgm_module, tmp_path):
        """Annotations table should have indexes for performance."""
        db_path = tmp_path / "test_db.db"
        with patch.object(cgm_module, "DB_PATH", db_path):
            conn = cgm_module.create_database()
            
            # Check indexes exist
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='annotations'"
            )
            indexes = [row[0] for row in cursor.fetchall()]
            
            assert any('timestamp' in idx for idx in indexes)
            assert any('tag' in idx for idx in indexes)
            
            conn.close()


class TestParseAnnotationTime:
    """Tests for parse_annotation_time function."""
    
    def test_parses_now(self, cgm_module):
        """Should parse 'now' to current timestamp."""
        before = int(datetime.now(timezone.utc).timestamp() * 1000)
        result = cgm_module.parse_annotation_time("now")
        after = int(datetime.now(timezone.utc).timestamp() * 1000)
        
        assert before <= result <= after
    
    def test_parses_relative_hours(self, cgm_module):
        """Should parse relative time like '1h ago'."""
        expected = datetime.now(timezone.utc) - timedelta(hours=1)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("1h ago")
        
        # Allow 1 second variance
        assert abs(result - expected_ms) < 1000
    
    def test_parses_relative_minutes(self, cgm_module):
        """Should parse relative time like '30m ago'."""
        expected = datetime.now(timezone.utc) - timedelta(minutes=30)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("30m ago")
        
        # Allow 1 second variance
        assert abs(result - expected_ms) < 1000
    
    def test_parses_relative_days(self, cgm_module):
        """Should parse relative time like '2d ago'."""
        expected = datetime.now(timezone.utc) - timedelta(days=2)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("2d ago")
        
        # Allow 1 second variance
        assert abs(result - expected_ms) < 1000
    
    def test_parses_time_with_pm(self, cgm_module):
        """Should parse time like '2pm'."""
        now = datetime.now(timezone.utc)
        expected = now.replace(hour=14, minute=0, second=0, microsecond=0)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("2pm")
        
        assert result == expected_ms
    
    def test_parses_time_with_am(self, cgm_module):
        """Should parse time like '8am'."""
        now = datetime.now(timezone.utc)
        expected = now.replace(hour=8, minute=0, second=0, microsecond=0)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("8am")
        
        assert result == expected_ms
    
    def test_parses_24h_time(self, cgm_module):
        """Should parse 24-hour time like '14:30'."""
        now = datetime.now(timezone.utc)
        expected = now.replace(hour=14, minute=30, second=0, microsecond=0)
        expected_ms = int(expected.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time("14:30")
        
        assert result == expected_ms
    
    def test_parses_iso_datetime(self, cgm_module):
        """Should parse ISO datetime string."""
        dt_str = "2026-01-21T14:30:00Z"
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        expected_ms = int(dt.timestamp() * 1000)
        
        result = cgm_module.parse_annotation_time(dt_str)
        
        assert result == expected_ms
    
    def test_raises_on_invalid_format(self, cgm_module):
        """Should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Could not parse time"):
            cgm_module.parse_annotation_time("invalid time string")


class TestAddAnnotation:
    """Tests for add_annotation function."""
    
    def test_adds_annotation(self, cgm_module, temp_db):
        """Should add annotation to database."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            result = cgm_module.add_annotation(
                time_str="now",
                tag="lunch",
                note="pizza"
            )
            
            assert "error" not in result
            assert result["status"] == "success"
            assert result["tag"] == "lunch"
            assert result["note"] == "pizza"
            assert "id" in result
            
            # Verify in database
            conn = sqlite3.connect(temp_db)
            cursor = conn.execute("SELECT * FROM annotations WHERE id = ?", (result["id"],))
            row = cursor.fetchone()
            assert row is not None
            assert row[2] == "lunch"  # tag
            assert row[3] == "pizza"  # note
            conn.close()
    
    def test_adds_annotation_without_note(self, cgm_module, temp_db):
        """Should add annotation without note."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            result = cgm_module.add_annotation(
                time_str="2pm",
                tag="exercise"
            )
            
            assert "error" not in result
            assert result["status"] == "success"
            assert result["tag"] == "exercise"
            assert result["note"] is None
    
    def test_returns_error_on_invalid_time(self, cgm_module, temp_db):
        """Should return error for invalid time string."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            result = cgm_module.add_annotation(
                time_str="invalid",
                tag="lunch"
            )
            
            assert "error" in result


class TestListAnnotations:
    """Tests for list_annotations function."""
    
    def test_lists_all_annotations(self, cgm_module, temp_db):
        """Should list all annotations."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            # Add some annotations
            cgm_module.add_annotation("now", "lunch", "pizza")
            cgm_module.add_annotation("1h ago", "exercise", "running")
            
            result = cgm_module.list_annotations()
            
            assert "error" not in result
            assert result["status"] == "success"
            assert result["count"] == 2
            assert len(result["annotations"]) == 2
    
    def test_filters_by_tag(self, cgm_module, temp_db):
        """Should filter annotations by tag."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            # Add annotations with different tags
            cgm_module.add_annotation("now", "lunch", "pizza")
            cgm_module.add_annotation("1h ago", "exercise", "running")
            cgm_module.add_annotation("2h ago", "lunch", "salad")
            
            result = cgm_module.list_annotations(tag="lunch")
            
            assert result["count"] == 2
            assert all(ann["tag"] == "lunch" for ann in result["annotations"])
    
    def test_filters_by_days(self, cgm_module, temp_db):
        """Should filter annotations by time range."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            # Add recent annotation
            cgm_module.add_annotation("1h ago", "lunch", "recent")
            
            # Mock parse_annotation_time to create an old annotation
            from unittest.mock import MagicMock
            old_time = datetime.now(timezone.utc) - timedelta(days=10)
            old_ms = int(old_time.timestamp() * 1000)
            
            with patch.object(cgm_module, 'parse_annotation_time', return_value=old_ms):
                cgm_module.add_annotation("10d ago", "lunch", "old")
            
            result = cgm_module.list_annotations(days=7)
            
            # Should only return recent annotation
            assert result["count"] == 1
            assert result["annotations"][0]["note"] == "recent"
    
    def test_returns_empty_list_when_no_annotations(self, cgm_module, temp_db):
        """Should return empty list when no annotations exist."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            result = cgm_module.list_annotations()
            
            assert result["status"] == "success"
            assert result["count"] == 0
            assert result["annotations"] == []


class TestDeleteAnnotation:
    """Tests for delete_annotation function."""
    
    def test_deletes_annotation(self, cgm_module, temp_db):
        """Should delete annotation by ID."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            # Add annotation
            add_result = cgm_module.add_annotation("now", "lunch", "pizza")
            annotation_id = add_result["id"]
            
            # Delete it
            result = cgm_module.delete_annotation(annotation_id)
            
            assert "error" not in result
            assert result["status"] == "success"
            assert result["deleted_id"] == annotation_id
            
            # Verify deleted
            conn = sqlite3.connect(temp_db)
            cursor = conn.execute("SELECT * FROM annotations WHERE id = ?", (annotation_id,))
            assert cursor.fetchone() is None
            conn.close()
    
    def test_returns_error_for_nonexistent_annotation(self, cgm_module, temp_db):
        """Should return error when annotation doesn't exist."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            result = cgm_module.delete_annotation(99999)
            
            assert "error" in result


class TestGetAnnotationsForTimerange:
    """Tests for get_annotations_for_timerange function."""
    
    def test_gets_annotations_in_range(self, cgm_module, temp_db):
        """Should get annotations within time range."""
        with patch.object(cgm_module, "DB_PATH", temp_db):
            now = datetime.now(timezone.utc)
            
            # Add annotations at different times
            cgm_module.add_annotation("now", "lunch", "recent")
            cgm_module.add_annotation("2h ago", "exercise", "middle")
            cgm_module.add_annotation("5h ago", "breakfast", "old")
            
            # Query for last 3 hours
            start = now - timedelta(hours=3)
            start_ms = int(start.timestamp() * 1000)
            end_ms = int(now.timestamp() * 1000)
            
            annotations = cgm_module.get_annotations_for_timerange(start_ms, end_ms)
            
            # Should get the two recent ones
            assert len(annotations) == 2
            tags = [ann["tag"] for ann in annotations]
            assert "lunch" in tags
            assert "exercise" in tags
            assert "breakfast" not in tags


class TestQueryPatternsWithTags:
    """Tests for querying patterns with annotation tags."""
    
    def test_filters_by_tag(self, cgm_module, populated_db):
        """Should filter readings by annotation tag."""
        with patch.object(cgm_module, "DB_PATH", populated_db):
            # Add an annotation
            now = datetime.now(timezone.utc)
            time_str = now.strftime("%Y-%m-%d %H:%M")
            cgm_module.add_annotation(time_str, "lunch", "pizza")
            
            # Query with tag filter
            result = cgm_module.query_patterns(days=7, tag="lunch")
            
            # Should get readings within 3 hours after the annotation
            assert "error" not in result
            assert result["readings_matched"] > 0
            assert "tag=lunch" in result["filter"]
    
    def test_returns_error_when_no_annotations_with_tag(self, cgm_module, populated_db):
        """Should return error when no annotations exist with tag."""
        with patch.object(cgm_module, "DB_PATH", populated_db):
            result = cgm_module.query_patterns(days=7, tag="nonexistent")
            
            assert "error" in result
            assert "No annotations found" in result["error"]
