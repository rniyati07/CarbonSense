from __future__ import annotations

import pytest
import uuid


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
def mock_event_publisher() -> MockEventPublisher:
    return MockEventPublisher()
