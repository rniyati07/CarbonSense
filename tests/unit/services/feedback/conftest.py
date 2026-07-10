from __future__ import annotations

import uuid
from typing import Any

import pytest


class MockCursor:
    def __init__(self, conn: MockConnection) -> None:
        self.conn = conn
        self.rows: list[tuple] = []
        self.query_responses: dict[str, list[list[tuple]]] = {}

    def execute(self, sql: str, params: tuple | dict | None = None) -> None:
        self.conn.executed_queries.append((sql, params))
        # Check if sql matches any key in query_responses
        for pattern, response in self.query_responses.items():
            if pattern in sql:
                if response:
                    # Pop the next result set (a list of tuples)
                    self.rows = list(response.pop(0))
                else:
                    self.rows = []
                break

    def fetchone(self) -> tuple | None:
        if self.rows:
            return self.rows.pop(0)
        return None

    def fetchall(self) -> list[tuple]:
        res = list(self.rows)
        self.rows = []
        return res

    def scalar(self) -> any:
        if self.rows:
            val = self.rows.pop(0)
            if isinstance(val, tuple):
                return val[0]
            return val
        return None


class MockConnection:
    def __init__(self) -> None:
        self.executed_queries: list[tuple[str, any]] = []
        self.cursor_obj = MockCursor(self)
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def cursor(self) -> MockCursor:
        return self.cursor_obj

    def execute(self, sql: str, params: tuple | dict | None = None) -> MockCursor:
        self.cursor_obj.execute(sql, params)
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class MockSQLAlchemyResult:
    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows

    def fetchone(self) -> tuple | None:
        return self.rows.pop(0) if self.rows else None

    def fetchall(self) -> list[tuple]:
        res, self.rows = list(self.rows), []
        return res

    def scalar(self) -> any:
        if not self.rows:
            return None
        val = self.rows.pop(0)
        return val[0] if isinstance(val, tuple) else val


class MockSQLAlchemyConnection:
    """Mimics the shape of a SQLAlchemy Connection: has .execute(), no .cursor().

    Added during the pre-ENG-4 integration audit: the previous MockConnection
    (below) has both .execute() and .cursor(), so `is_sqlalchemy = hasattr(conn,
    "execute") and not hasattr(conn, "cursor")` was always False in tests --
    the SQLAlchemy code path (and the missing-commit bug that lived in it) was
    never actually exercised. This mock has only .execute(), so is_sqlalchemy
    evaluates True and that branch runs for real in tests that use it.
    """

    def __init__(self) -> None:
        self.executed_queries: list[tuple[str, Any]] = []
        self.query_responses: dict[str, list[list[tuple]]] = {}
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, clause: Any, params: dict | None = None) -> MockSQLAlchemyResult:
        sql = str(clause)
        self.executed_queries.append((sql, params))
        for pattern, response in self.query_responses.items():
            if pattern in sql:
                rows = list(response.pop(0)) if response else []
                return MockSQLAlchemyResult(rows)
        return MockSQLAlchemyResult([])

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class MockEventPublisher:
    def __init__(self) -> None:
        self.published_events: list[tuple[str, any]] = []

    def publish(self, topic: str, event: any) -> None:
        self.published_events.append((topic, event))


@pytest.fixture()
def tenant_id() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture()
def building_id() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture()
def finding_id() -> uuid.UUID:
    return uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture()
def mock_connection() -> MockConnection:
    return MockConnection()


@pytest.fixture()
def mock_sqlalchemy_connection() -> MockSQLAlchemyConnection:
    return MockSQLAlchemyConnection()


@pytest.fixture()
def mock_event_publisher() -> MockEventPublisher:
    return MockEventPublisher()
