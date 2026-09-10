import os
import secrets
import unittest
from unittest.mock import patch

from werkzeug.security import check_password_hash, generate_password_hash

import app
import configuration
from services.database_service import (
    DatabaseUnavailable,
    User,
    UsernameTaken,
    normalize_username,
    validate_username,
)


class FakeDatabaseService:
    def __init__(self):
        self.users = {}
        self.last_login_ids = []
        self.fail = False

    def create_user(self, username, normalized, password_hash, preferred_language):
        if self.fail:
            raise DatabaseUnavailable()
        if normalized in self.users:
            raise UsernameTaken()
        user = User(str(len(self.users) + 1), username, normalized, password_hash, preferred_language)
        self.users[normalized] = user
        return user

    def find_user_by_normalized_username(self, normalized):
        if self.fail:
            raise DatabaseUnavailable()
        return self.users.get(normalized)

    def update_last_login(self, user_id):
        if self.fail:
            raise DatabaseUnavailable()
        self.last_login_ids.append(user_id)


class AuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.database = FakeDatabaseService()
        self.db_patch = patch.object(app, "DATABASE_SERVICE", self.database)
        self.db_patch.start()
        self.original_auth_available = app.AUTH_SECRET_CONFIGURED
        self.original_secret = app.app.config["SECRET_KEY"]
        self.original_cookie_secure = app.app.config["SESSION_COOKIE_SECURE"]
        self.test_secret = secrets.token_urlsafe(48)
        app.AUTH_SECRET_CONFIGURED = True
        app.app.config.update(
            TESTING=True,
            SECRET_KEY=self.test_secret,
            SESSION_COOKIE_SECURE=False,
        )
        self.client = app.app.test_client()

    def tearDown(self):
        app.AUTH_SECRET_CONFIGURED = self.original_auth_available
        app.app.config.update(
            SECRET_KEY=self.original_secret,
            SESSION_COOKIE_SECURE=self.original_cookie_secure,
        )
        self.db_patch.stop()

    def register(self, **overrides):
        password_value = "safe-password-123"
        payload = {"username": "Kofi Farmer", "preferred_language": "en"}
        payload["password"] = password_value
        payload["confirm_password"] = password_value
        payload.update(overrides)
        return self.client.post("/api/auth/register", json=payload)

    def test_username_normalization_and_policy(self):
        self.assertEqual(normalize_username("  GODBLESS   Farmer "), "godbless farmer")
        self.assertIsNotNone(validate_username("Kofi-01")[1])
        self.assertIsNotNone(validate_username("no!")[1])

    def test_registration_hashes_password_and_returns_safe_metadata(self):
        response = self.register()
        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertTrue(payload["authenticated"])
        self.assertNotIn("password", str(payload).casefold())
        user = self.database.users["kofi farmer"]
        password_value = "safe-password-123"
        self.assertNotEqual(user.password_hash, password_value)
        self.assertTrue(check_password_hash(user.password_hash, password_value))

    def test_duplicate_usernames_normalize_case_and_whitespace(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register(username="KOFI FARMER").status_code, 409)
        response = self.register(username="  Kofi   Farmer  ")
        self.assertEqual(response.status_code, 409)
        self.assertIn("already taken", response.get_json()["error"])

    def test_registration_validation(self):
        mismatch = "different"
        too_short = "short"
        self.assertEqual(self.register(confirm_password=mismatch).status_code, 400)
        self.assertEqual(self.register(password=too_short, confirm_password=too_short).status_code, 400)
        self.assertEqual(self.register(username="bad!name").status_code, 400)
        self.assertEqual(self.register(preferred_language="fr").status_code, 400)

    def test_numeric_registration_name_does_not_create_user(self):
        for name in ("Kofi123", "12345"):
            with self.subTest(name=name):
                response = self.register(username=name)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json()["error"],
                    "Please enter a valid name using letters, spaces, hyphens or apostrophes only.")
                self.assertEqual(self.database.users, {})
                self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_legacy_username_can_still_log_in(self):
        self.database.create_user("Ama__Kofi-2", "ama__kofi-2",
                                  generate_password_hash("safe-password-123"), "en")
        response = self.client.post("/api/auth/login", json={
            "username": "  AMA__KOFI-2  ", "password": "safe-password-123",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["username"], "Ama__Kofi-2")

    def test_login_success_creates_session_and_me_returns_safe_user(self):
        self.register(username="Ama", preferred_language="tw")
        self.client.post("/api/auth/logout")
        password_value = "safe-password-123"
        response = self.client.post("/api/auth/login", json=dict(username="AMA", password=password_value))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["user"]["preferred_language"], "tw")
        self.assertEqual(self.database.last_login_ids, ["1"])
        me = self.client.get("/api/auth/me")
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.get_json()["user"]["username"], "Ama")
        self.assertNotIn("password_hash", me.get_json()["user"])

    def test_invalid_login_is_generic_for_unknown_and_wrong_password(self):
        self.register()
        self.client.post("/api/auth/logout")
        missing_password = "anything"
        wrong_password = "wrong"
        for payload in (dict(username="missing", password=missing_password), dict(username="Kofi Farmer", password=wrong_password)):
            response = self.client.post("/api/auth/login", json=payload)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.get_json()["error"], "Invalid username or password.")

    def test_me_unauthenticated_and_logout_clears_session(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        self.register()
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_database_unavailable_is_safe(self):
        self.database.fail = True
        response = self.register()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["error"], "User account service is temporarily unavailable.")

    def test_session_secret_resolution_is_strictly_test_or_environment_only(self):
        with patch.object(configuration, "TEST_MODE_REQUESTED", True), patch.object(
            configuration, "FLASK_SECRET_KEY", ""
        ):
            resolved_test_secret = app.configured_session_secret()
            self.assertIsInstance(resolved_test_secret, str)
            self.assertIsNotNone(resolved_test_secret)
            self.assertTrue(bool(resolved_test_secret))
            app.AUTH_SECRET_CONFIGURED = True
            app.app.config["SECRET_KEY"] = resolved_test_secret
            self.assertEqual(self.register(username="Test Mode User").status_code, 201)
            self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        with patch.object(configuration, "TEST_MODE_REQUESTED", False), patch.object(
            configuration, "FLASK_SECRET_KEY", ""
        ):
            missing_secret = app.configured_session_secret()
            self.assertIsNone(missing_secret)
            self.assertFalse(bool(missing_secret))
        configured_secret = secrets.token_urlsafe(48)
        with patch.object(configuration, "TEST_MODE_REQUESTED", False), patch.object(
            configuration, "FLASK_SECRET_KEY", configured_secret
        ):
            self.assertEqual(app.configured_session_secret(), configured_secret)

    def test_missing_secret_keeps_health_up_and_all_auth_unavailable(self):
        app.AUTH_SECRET_CONFIGURED = False
        app.app.config["SECRET_KEY"] = None
        client = app.app.test_client()
        client.set_cookie("session", secrets.token_urlsafe(48))

        self.assertEqual(client.get("/api/health").status_code, 200)
        self.assertEqual(self.register().status_code, 503)
        self.assertEqual(client.post("/api/auth/login", json={
            "username": "Kofi Farmer", "password": "safe-password-123"
        }).status_code, 503)
        self.assertEqual(client.get("/api/auth/me").status_code, 503)
        self.assertEqual(client.post("/api/auth/logout").status_code, 503)
        self.assertEqual(
            client.get("/api/auth/me").get_json()["error"],
            "User account service is temporarily unavailable.",
        )

    def test_configured_non_test_secret_supports_normal_session_auth(self):
        app.AUTH_SECRET_CONFIGURED = True
        app.app.config["SECRET_KEY"] = secrets.token_urlsafe(48)
        client = app.app.test_client()
        response = client.post("/api/auth/register", json={
            "username": "Configured User",
            "password": "safe-password-123",
            "confirm_password": "safe-password-123",
            "preferred_language": "en",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)

    def test_cookie_security_is_explicit_and_keeps_required_flags(self):
        self.assertFalse(app.app.config["SESSION_COOKIE_SECURE"])
        self.assertTrue(app.app.config["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(app.app.config["SESSION_COOKIE_SAMESITE"], "Lax")
        with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "true"}):
            self.assertTrue(configuration.environment_boolean("SESSION_COOKIE_SECURE"))
        with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "false"}):
            self.assertFalse(configuration.environment_boolean("SESSION_COOKIE_SECURE", True))
        with patch.dict(os.environ, {"SESSION_COOKIE_SECURE": "invalid"}):
            self.assertFalse(configuration.environment_boolean("SESSION_COOKIE_SECURE"))
