from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

import app as application


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    application._rate_cache.clear()
    yield
    application._rate_cache.clear()


def build_client(handler: httpx.MockTransport) -> tuple[TestClient, httpx.AsyncClient]:
    upstream_client = httpx.AsyncClient(transport=handler)
    application.app.dependency_overrides[application.get_http_client] = lambda: upstream_client
    return TestClient(application.app), upstream_client


def close_client(upstream_client: httpx.AsyncClient) -> None:
    application.app.dependency_overrides.clear()
    asyncio.run(upstream_client.aclose())


def test_converts_with_the_upstream_rate() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/2026-08-28"
        assert request.url.params["base"] == "EUR"
        assert request.url.params["symbols"] == "TRY"
        return httpx.Response(
            200,
            json={
                "amount": 1.0,
                "base": "EUR",
                "date": "2026-08-28",
                "rates": {"TRY": 47.1234},
            },
        )

    client, upstream_client = build_client(httpx.MockTransport(upstream))
    try:
        response = client.get(
            "/tools/convert",
            params={"amount": "250", "from": "eur", "to": "try", "date": "2026-08-28"},
        )
    finally:
        close_client(upstream_client)

    assert response.status_code == 200
    assert response.json() == {
        "amount": 250,
        "from": "EUR",
        "to": "TRY",
        "rate": 47.1234,
        "result": 11780.85,
        "rate_date": "2026-08-28",
        "asked_date": "2026-08-28",
        "source": "ECB via frankfurter.dev",
    }


def test_reuses_a_cached_rate() -> None:
    upstream_calls = 0

    def upstream(_: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(
            200,
            json={"base": "EUR", "date": "2026-08-28", "rates": {"TRY": 47.1234}},
        )

    client, upstream_client = build_client(httpx.MockTransport(upstream))
    params = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}
    try:
        first_response = client.get("/tools/convert", params=params)
        second_response = client.get("/tools/convert", params={**params, "amount": "10"})
    finally:
        close_client(upstream_client)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert upstream_calls == 1
