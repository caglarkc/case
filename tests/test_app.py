from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

import app as application

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def clear_cache() -> Iterator[None]:
    application._rate_cache.clear()
    yield
    application._rate_cache.clear()


@contextmanager
def api_client(handler: Handler) -> Iterator[TestClient]:
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    application.app.dependency_overrides[application.get_http_client] = lambda: upstream_client
    try:
        with TestClient(application.app, raise_server_exceptions=False) as client:
            yield client
    finally:
        application.app.dependency_overrides.clear()
        asyncio.run(upstream_client.aclose())


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "amount": 1.0,
        "base": "EUR",
        "date": "2026-08-28",
        "rates": {"TRY": 47.1234},
    }
    payload.update(overrides)
    return payload


VALID_PARAMS = {"amount": "250", "from": "EUR", "to": "TRY", "date": "2026-08-28"}


def assert_error(response: httpx.Response, status: int, code: str) -> None:
    assert response.status_code == status
    assert set(response.json()) == {"error", "message"}
    assert response.json()["error"] == code
    assert isinstance(response.json()["message"], str)


def test_converts_with_the_upstream_rate() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/2026-08-28"
        assert request.url.params["base"] == "EUR"
        assert request.url.params["symbols"] == "TRY"
        return httpx.Response(200, json=valid_payload())

    with api_client(upstream) as client:
        response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "from": "eur", "to": "try"},
        )

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


def test_preserves_large_decimal_values_in_the_json_number_tokens() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload(rates={"TRY": 1}))

    with api_client(upstream) as client:
        response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "amount": "9999999999999999.99"},
        )

    payload = json.loads(response.text, parse_float=Decimal, parse_int=Decimal)
    assert response.status_code == 200
    assert payload["amount"] == Decimal("9999999999999999.99")
    assert payload["result"] == Decimal("9999999999999999.99")


def test_documents_the_complete_public_response_contract() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("OpenAPI inspection must not reach the upstream")

    with api_client(upstream) as client:
        operation = client.get("/openapi.json").json()["paths"]["/tools/convert"]["get"]

    assert set(operation["responses"]) == {"200", "404", "422", "500", "502", "504"}
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ConversionResponse"
    }
    parameter_names = {parameter["name"] for parameter in operation["parameters"]}
    assert parameter_names == {"amount", "from", "to", "date"}
    for status in {"404", "422", "500", "502", "504"}:
        assert operation["responses"][status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse"
        }


def test_uses_the_actual_rate_date_for_a_weekend() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload(date="2026-08-28"))

    with api_client(upstream) as client:
        response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "date": "2026-08-30"},
        )

    assert response.status_code == 200
    assert response.json()["asked_date"] == "2026-08-30"
    assert response.json()["rate_date"] == "2026-08-28"


def test_calculates_before_rounding_the_result() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload(rates={"TRY": 1.005}))

    with api_client(upstream) as client:
        response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "amount": "1"},
        )

    assert response.status_code == 200
    assert response.json()["rate"] == 1.005
    assert response.json()["result"] == 1.01


def test_reuses_a_cached_rate_for_a_different_amount() -> None:
    upstream_calls = 0

    def upstream(_: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(200, json=valid_payload())

    with api_client(upstream) as client:
        first_response = client.get("/tools/convert", params=VALID_PARAMS)
        second_response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "amount": "10"},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["result"] == 471.23
    assert upstream_calls == 1


def test_cache_keeps_dates_and_pairs_separate() -> None:
    requested_urls: list[str] = []

    def upstream(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        target = request.url.params["symbols"]
        requested_date = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(
            200,
            json=valid_payload(date=requested_date, rates={target: 2}),
        )

    with api_client(upstream) as client:
        client.get("/tools/convert", params=VALID_PARAMS)
        client.get("/tools/convert", params={**VALID_PARAMS, "date": "2026-08-27"})
        client.get("/tools/convert", params={**VALID_PARAMS, "to": "USD"})

    assert len(requested_urls) == 3


@pytest.mark.parametrize(
    "amount",
    [None, "0", "-1", "1.1234567890", "not-a-number", "NaN", "Infinity", "1e999"],
)
def test_rejects_invalid_amounts_without_calling_upstream(amount: str | None) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach the upstream")

    params = dict(VALID_PARAMS)
    if amount is None:
        params.pop("amount")
    else:
        params["amount"] = amount

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=params)

    assert_error(response, 422, "invalid_amount")


@pytest.mark.parametrize(
    "field,value",
    [("from", "EU"), ("to", "TR1"), ("from", ""), ("from", " EUR ")],
)
def test_rejects_malformed_currencies(field: str, value: str) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach the upstream")

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params={**VALID_PARAMS, field: value})

    assert_error(response, 422, "invalid_currency")


def test_rejects_the_same_currency() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach the upstream")

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params={**VALID_PARAMS, "to": "eur"})

    assert_error(response, 422, "same_currency")


@pytest.mark.parametrize(
    ("requested_date", "code"),
    [("2099-01-01", "future_date"), ("1999-01-03", "date_out_of_range")],
)
def test_rejects_dates_outside_the_supported_range(requested_date: str, code: str) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach the upstream")

    with api_client(upstream) as client:
        response = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "date": requested_date},
        )

    assert_error(response, 422, code)


def test_rejects_a_malformed_or_missing_date() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Invalid input must not reach the upstream")

    with api_client(upstream) as client:
        malformed = client.get(
            "/tools/convert",
            params={**VALID_PARAMS, "date": "28-08-2026"},
        )
        missing_params = dict(VALID_PARAMS)
        missing_params.pop("date")
        missing = client.get("/tools/convert", params=missing_params)

    assert_error(malformed, 422, "invalid_request")
    assert_error(missing, 422, "invalid_request")


@pytest.mark.parametrize("upstream_status", [404, 422])
def test_maps_missing_upstream_rates(upstream_status: int) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, json={"message": "not found"})

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 404, "rate_not_found")


@pytest.mark.parametrize("upstream_status", [400, 429, 500, 503])
def test_maps_unexpected_upstream_statuses(upstream_status: int) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(upstream_status, text="upstream details")

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "upstream_error")
    assert "upstream details" not in response.text


def test_maps_an_upstream_timeout() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout detail", request=request)

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 504, "upstream_timeout")
    assert "secret" not in response.text


def test_maps_an_upstream_connection_failure() -> None:
    def upstream(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("secret connection detail", request=request)

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "upstream_unavailable")
    assert "secret" not in response.text


def test_rejects_a_non_json_response() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", headers={"content-type": "text/html"})

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "invalid_upstream_response")


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"base": "USD", "date": "2026-08-28", "rates": {"TRY": 47}},
        valid_payload(rates={}),
        valid_payload(rates={"TRY": 0}),
        valid_payload(rates={"TRY": "NaN"}),
        valid_payload(date="not-a-date"),
        valid_payload(date="2026-08-29"),
    ],
)
def test_rejects_invalid_upstream_data(payload: object) -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with api_client(upstream) as client:
        response = client.get("/tools/convert", params=VALID_PARAMS)

    assert_error(response, 502, "invalid_upstream_response")


def test_does_not_cache_failures() -> None:
    upstream_calls = 0

    def upstream(_: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        return httpx.Response(500)

    with api_client(upstream) as client:
        first_response = client.get("/tools/convert", params=VALID_PARAMS)
        second_response = client.get("/tools/convert", params=VALID_PARAMS)

    assert first_response.status_code == 502
    assert second_response.status_code == 502
    assert upstream_calls == 2


def test_evicts_the_oldest_rate_when_the_cache_is_full(monkeypatch: pytest.MonkeyPatch) -> None:
    upstream_calls = 0

    def upstream(request: httpx.Request) -> httpx.Response:
        nonlocal upstream_calls
        upstream_calls += 1
        target = request.url.params["symbols"]
        return httpx.Response(200, json=valid_payload(rates={target: 2}))

    monkeypatch.setattr(application, "CACHE_MAX_SIZE", 2)
    with api_client(upstream) as client:
        client.get("/tools/convert", params=VALID_PARAMS)
        client.get("/tools/convert", params={**VALID_PARAMS, "to": "USD"})
        client.get("/tools/convert", params={**VALID_PARAMS, "to": "GBP"})
        client.get("/tools/convert", params=VALID_PARAMS)

    assert len(application._rate_cache) == 2
    assert upstream_calls == 4


def test_formats_unknown_routes_and_methods_as_standard_errors() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        pytest.fail("Routing errors must not reach the upstream")

    with api_client(upstream) as client:
        missing = client.get("/missing")
        wrong_method = client.post("/tools/convert")

    assert_error(missing, 404, "not_found")
    assert_error(wrong_method, 405, "method_not_allowed")


def test_formats_an_unexpected_internal_failure() -> None:
    def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=valid_payload())

    def fail_dependency() -> httpx.AsyncClient:
        raise RuntimeError("secret internal detail")

    application.app.dependency_overrides[application.get_http_client] = fail_dependency
    try:
        with TestClient(application.app, raise_server_exceptions=False) as client:
            response = client.get("/tools/convert", params=VALID_PARAMS)
    finally:
        application.app.dependency_overrides.clear()

    assert_error(response, 500, "internal_error")
    assert "secret" not in response.text
