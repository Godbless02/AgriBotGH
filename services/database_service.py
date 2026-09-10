"""Small PostgreSQL repository for AgriBotGH account management.

The service deliberately owns all SQL for Database Phase 1.  Connections are
opened only for an auth request so a missing database cannot stop the
agricultural application from starting or its deterministic tests from running.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable

import configuration


class DatabaseUnavailable(RuntimeError):
    """Raised when the optional account database cannot be reached."""


class UsernameTaken(RuntimeError):
    """Raised when a normalized username already exists."""


@dataclass(frozen=True)
class User:
    id: str
    username: str
    username_normalized: str
    password_hash: str
    preferred_language: str


NAME_VALIDATION_ERROR = "Please enter a valid name using letters, spaces, hyphens or apostrophes only."


def normalize_username(value: str) -> str:
    """Trim and collapse spaces, then case-fold for uniqueness."""
    return " ".join(value.strip().split()).casefold()


def validate_username(value: object) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, NAME_VALIDATION_ERROR
    display = " ".join(value.strip().split())
    if not 3 <= len(display) <= 30:
        return None, NAME_VALIDATION_ERROR
    if not display[0].isalpha() or not display[-1].isalpha():
        return None, NAME_VALIDATION_ERROR
    for index, character in enumerate(display):
        if character.isalpha() or character == " ":
            continue
        if (character in "-'" and display[index - 1].isalpha()
                and display[index + 1].isalpha()):
            continue
        return None, NAME_VALIDATION_ERROR
    return display, None


class DatabaseService:
    """Parameterized PostgreSQL access for the ``users`` table only."""

    def __init__(self, database_url: str | None = None, connection_factory: Callable | None = None):
        self.database_url = database_url if database_url is not None else configuration.DATABASE_URL
        self.connection_factory = connection_factory

    def _connect(self):
        if not self.database_url:
            raise DatabaseUnavailable("Database is not configured")
        try:
            if self.connection_factory is not None:
                return self.connection_factory(self.database_url)
            import psycopg
            return psycopg.connect(self.database_url)
        except Exception as error:  # Driver and network details are never returned to clients.
            raise DatabaseUnavailable("Database is unavailable") from error

    @staticmethod
    def _user(row) -> User | None:
        if row is None:
            return None
        return User(*row)

    def find_user_by_normalized_username(self, username_normalized: str) -> User | None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "SELECT id::text, username, username_normalized, password_hash, preferred_language "
                    "FROM users WHERE username_normalized = %s",
                    (username_normalized,),
                )
                return self._user(cursor.fetchone())
        except DatabaseUnavailable:
            raise
        except Exception as error:
            raise DatabaseUnavailable("Database is unavailable") from error

    def create_user(self, username: str, username_normalized: str, password_hash: str, preferred_language: str) -> User:
        user_id = str(uuid.uuid4())
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO users (id, username, username_normalized, password_hash, preferred_language) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "RETURNING id::text, username, username_normalized, password_hash, preferred_language",
                    (user_id, username, username_normalized, password_hash, preferred_language),
                )
                row = cursor.fetchone()
                connection.commit()
                return self._user(row)
        except DatabaseUnavailable:
            raise
        except Exception as error:
            if getattr(error, "sqlstate", None) == "23505":
                raise UsernameTaken("Username already exists") from error
            raise DatabaseUnavailable("Database is unavailable") from error

    def update_last_login(self, user_id: str) -> None:
        try:
            with self._connect() as connection, connection.cursor() as cursor:
                cursor.execute("UPDATE users SET last_login_at = NOW() WHERE id = %s", (user_id,))
                connection.commit()
        except DatabaseUnavailable:
            raise
        except Exception as error:
            raise DatabaseUnavailable("Database is unavailable") from error


class InMemoryDatabaseService:
    """Deterministic test repository; never selected outside explicit test mode."""

    def __init__(self):
        self.users: dict[str, User] = {}

    def find_user_by_normalized_username(self, username_normalized: str) -> User | None:
        return self.users.get(username_normalized)

    def create_user(self, username: str, username_normalized: str, password_hash: str, preferred_language: str) -> User:
        if username_normalized in self.users:
            raise UsernameTaken()
        user = User(str(uuid.uuid4()), username, username_normalized, password_hash, preferred_language)
        self.users[username_normalized] = user
        return user

    def update_last_login(self, user_id: str) -> None:
        return None
