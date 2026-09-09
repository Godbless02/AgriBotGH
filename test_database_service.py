import unittest

from services.database_service import DatabaseService, normalize_username, validate_username


class RecordingCursor:
    def __init__(self): self.calls = []
    def execute(self, query, params): self.calls.append((query, params))
    def fetchone(self): return None
    def __enter__(self): return self
    def __exit__(self, *args): return False


class RecordingConnection:
    def __init__(self): self.recording_cursor = RecordingCursor()
    def cursor(self): return self.recording_cursor
    def commit(self): pass
    def __enter__(self): return self
    def __exit__(self, *args): return False


class DatabaseServiceTests(unittest.TestCase):
    def test_normalization_preserves_meaningful_username_characters(self):
        self.assertEqual(normalize_username("  Ama__Kofi-2  "), "ama__kofi-2")
        self.assertEqual(validate_username("Ama__Kofi-2")[1], None)

    def test_repository_uses_parameterized_queries(self):
        connection = RecordingConnection()
        service = DatabaseService("postgresql://example", connection_factory=lambda _: connection)
        service.find_user_by_normalized_username("' OR 1=1 --")
        query, params = connection.recording_cursor.calls[0]
        self.assertIn("%s", query)
        self.assertNotIn("OR 1=1", query)
        self.assertEqual(params, ("' OR 1=1 --",))
