from __future__ import annotations

import os
import re
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")
SOURCE = "ECB via frankfurter.dev"
ECB_SERIES_START = date(1999, 1, 4)
CACHE_MAX_SIZE = 1024
HTTP_TIMEOUT = httpx.Timeout(3.0, connect=1.0)
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

RateCacheKey = tuple[str, str, date]
RateCacheValue = tuple[Decimal, date]

_rate_cache: OrderedDict[RateCacheKey, RateCacheValue] = OrderedDict()


class ServiceError(Exception):
    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        app.state.http_client = client
        yield


app = FastAPI(title="fx-tool", version="1.0.0", lifespan=lifespan)


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.error, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    fields = {str(error["loc"][-1]) for error in exc.errors() if error.get("loc")}
    if "amount" in fields:
        error = "invalid_amount"
        message = "Amount is required, must be positive, and may have at most two decimal places."
    elif fields.intersection({"from", "to"}):
        error = "invalid_currency"
        message = "Currency codes are required and must contain exactly three letters."
    else:
        error = "invalid_request"
        message = "The request contains a missing or invalid value."

    return JSONResponse(status_code=422, content={"error": error, "message": message})


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    if exc.status_code == 404:
        error, message = "not_found", "The requested resource was not found."
    elif exc.status_code == 405:
        error, message = "method_not_allowed", "That HTTP method is not allowed."
    else:
        error, message = "http_error", "The request could not be completed."
    return JSONResponse(status_code=exc.status_code, content={"error": error, "message": message})


@app.exception_handler(Exception)
async def unexpected_error_handler(_: Request, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "message": "An unexpected internal error occurred."},
    )


def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client


async def fetch_rate(
    source_currency: str,
    target_currency: str,
    asked_date: date,
    client: httpx.AsyncClient,
) -> RateCacheValue:
    cache_key = (source_currency, target_currency, asked_date)
    if cache_key in _rate_cache:
        _rate_cache.move_to_end(cache_key)
        return _rate_cache[cache_key]

    try:
        response = await client.get(
            f"{UPSTREAM_BASE}/v1/{asked_date.isoformat()}",
            params={"base": source_currency, "symbols": target_currency},
        )
    except httpx.TimeoutException as exc:
        raise ServiceError(504, "upstream_timeout", "The exchange-rate provider timed out.") from exc
    except httpx.RequestError as exc:
        raise ServiceError(
            502,
            "upstream_unavailable",
            "The exchange-rate provider could not be reached.",
        ) from exc

    if response.status_code in {404, 422}:
        raise ServiceError(404, "rate_not_found", "No rate was found for that pair and date.")
    if response.status_code < 200 or response.status_code >= 300:
        raise ServiceError(502, "upstream_error", "The exchange-rate provider returned an error.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ServiceError(
            502,
            "invalid_upstream_response",
            "The exchange-rate provider returned an invalid response.",
        ) from exc

    try:
        if not isinstance(payload, dict) or payload.get("base") != source_currency:
            raise ValueError("unexpected base currency")
        rates = payload.get("rates")
        if not isinstance(rates, dict) or target_currency not in rates:
            raise ValueError("target rate is missing")

        rate = Decimal(str(rates[target_currency]))
        rate_date = date.fromisoformat(payload["date"])
        if not rate.is_finite() or rate <= 0:
            raise ValueError("rate must be positive and finite")
        if rate_date < ECB_SERIES_START or rate_date > asked_date:
            raise ValueError("rate date is outside the requested range")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ServiceError(
            502,
            "invalid_upstream_response",
            "The exchange-rate provider returned an invalid response.",
        ) from exc

    value = (rate, rate_date)
    _rate_cache[cache_key] = value
    _rate_cache.move_to_end(cache_key)
    if len(_rate_cache) > CACHE_MAX_SIZE:
        _rate_cache.popitem(last=False)
    return value


@app.get("/tools/convert")
async def convert(
    amount: Annotated[Decimal, Query(gt=0, max_digits=18, decimal_places=2)],
    source_currency: Annotated[str, Query(alias="from")],
    target_currency: Annotated[str, Query(alias="to")],
    asked_date: Annotated[date, Query(alias="date")],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> dict[str, object]:
    source_currency = source_currency.strip().upper()
    target_currency = target_currency.strip().upper()

    if not CURRENCY_PATTERN.fullmatch(source_currency) or not CURRENCY_PATTERN.fullmatch(
        target_currency
    ):
        raise ServiceError(
            422,
            "invalid_currency",
            "Currency codes must contain exactly three letters.",
        )
    if source_currency == target_currency:
        raise ServiceError(422, "same_currency", "Source and target currencies must differ.")

    today_utc = datetime.now(timezone.utc).date()
    if asked_date > today_utc:
        raise ServiceError(422, "future_date", "The requested date cannot be in the future.")
    if asked_date < ECB_SERIES_START:
        raise ServiceError(
            422,
            "date_out_of_range",
            "The requested date is before the ECB exchange-rate series began.",
        )

    rate, rate_date = await fetch_rate(
        source_currency,
        target_currency,
        asked_date,
        client,
    )
    result = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "amount": float(amount),
        "from": source_currency,
        "to": target_currency,
        "rate": float(rate),
        "result": float(result),
        "rate_date": rate_date,
        "asked_date": asked_date,
        "source": SOURCE,
    }
