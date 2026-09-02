from __future__ import annotations

import asyncio
import json
import os
import re
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, WithJsonSchema
from starlette.exceptions import HTTPException as StarletteHTTPException

UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")
SOURCE = "ECB via frankfurter.dev"
ECB_SERIES_START = date(1999, 1, 4)
CACHE_MAX_SIZE = 1024
MAX_AMOUNT_DIGITS = 18
MAX_RATE_DIGITS = 18
MAX_RATE_DECIMAL_PLACES = 12
HTTP_TIMEOUT = httpx.Timeout(3.0, connect=1.0)
CURRENCY_PATTERN = re.compile(r"^[A-Z]{3}$")

RateCacheKey = tuple[str, str, date]
RateCacheValue = tuple[Decimal, date]

_rate_cache: OrderedDict[RateCacheKey, RateCacheValue] = OrderedDict()
_inflight_rate_requests: dict[RateCacheKey, asyncio.Task[RateCacheValue]] = {}

DecimalNumber = Annotated[
    Decimal,
    WithJsonSchema({"type": "number"}, mode="serialization"),
]


class ConversionQuery(BaseModel):
    amount: Decimal
    source_currency: str
    target_currency: str
    asked_date: date


class ConversionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    amount: DecimalNumber
    source_currency: str = Field(alias="from")
    target_currency: str = Field(alias="to")
    rate: DecimalNumber
    result: DecimalNumber
    rate_date: date
    asked_date: date
    source: str


class ErrorResponse(BaseModel):
    error: str
    message: str


class DecimalJSONResponse(Response):
    """Render finite Decimals as JSON numbers without a binary-float hop."""

    media_type = "application/json"

    def render(self, content: Any) -> bytes:
        def encode(value: Any) -> str:
            if isinstance(value, Decimal):
                if not value.is_finite():
                    raise ValueError("JSON numbers must be finite")
                return format(value, "f")
            if isinstance(value, date):
                return json.dumps(value.isoformat())
            if isinstance(value, dict):
                return "{" + ",".join(
                    f"{json.dumps(str(key))}:{encode(item)}" for key, item in value.items()
                ) + "}"
            if isinstance(value, (list, tuple)):
                return "[" + ",".join(encode(item) for item in value) + "]"
            return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

        return encode(content).encode("utf-8")


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


def reject_non_finite_json_number(value: str) -> None:
    raise ValueError(f"Invalid JSON number: {value}")


def parse_rate(payload: object, source_currency: str, target_currency: str) -> RateCacheValue:
    if not isinstance(payload, dict) or payload.get("base") != source_currency:
        raise ValueError("unexpected base currency")

    rates = payload.get("rates")
    if not isinstance(rates, dict) or target_currency not in rates:
        raise ValueError("target rate is missing")

    raw_rate = rates[target_currency]
    if isinstance(raw_rate, bool) or not isinstance(raw_rate, (int, Decimal)):
        raise ValueError("rate must be a JSON number")

    rate = raw_rate if isinstance(raw_rate, Decimal) else Decimal(raw_rate)
    if not rate.is_finite() or rate <= 0:
        raise ValueError("rate must be positive and finite")

    rate_tuple = rate.as_tuple()
    digits = list(rate_tuple.digits)
    exponent = rate_tuple.exponent
    while len(digits) > 1 and exponent < 0 and digits[-1] == 0:
        digits.pop()
        exponent += 1

    significant_digits = len(digits)
    decimal_places = max(-exponent, 0)
    integer_digits = max(significant_digits + exponent, 0)
    if (
        significant_digits > MAX_RATE_DIGITS
        or decimal_places > MAX_RATE_DECIMAL_PLACES
        or integer_digits > MAX_RATE_DIGITS
    ):
        raise ValueError("rate exceeds the safe numeric range")

    raw_date = payload.get("date")
    if not isinstance(raw_date, str):
        raise ValueError("rate date must be an ISO date string")
    rate_date = date.fromisoformat(raw_date)
    return rate, rate_date


async def fetch_and_cache_rate(
    source_currency: str,
    target_currency: str,
    asked_date: date,
    client: httpx.AsyncClient,
) -> RateCacheValue:
    cache_key = (source_currency, target_currency, asked_date)
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
        payload = json.loads(
            response.content,
            parse_float=Decimal,
            parse_constant=reject_non_finite_json_number,
        )
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            502,
            "invalid_upstream_response",
            "The exchange-rate provider returned an invalid response.",
        ) from exc

    try:
        rate, rate_date = parse_rate(payload, source_currency, target_currency)
        if rate_date < ECB_SERIES_START or rate_date > asked_date:
            raise ValueError("rate date is outside the requested range")
    except (TypeError, ValueError, DecimalException) as exc:
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

    task = _inflight_rate_requests.get(cache_key)
    if task is None:
        task = asyncio.create_task(
            fetch_and_cache_rate(
                source_currency,
                target_currency,
                asked_date,
                client,
            )
        )
        _inflight_rate_requests[cache_key] = task

        def remove_completed_task(completed_task: asyncio.Task[RateCacheValue]) -> None:
            if _inflight_rate_requests.get(cache_key) is completed_task:
                _inflight_rate_requests.pop(cache_key, None)
            if not completed_task.cancelled():
                completed_task.exception()

        task.add_done_callback(remove_completed_task)

    return await asyncio.shield(task)


@app.get(
    "/tools/convert",
    response_model=ConversionResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Rate not found"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        500: {"model": ErrorResponse, "description": "Internal error"},
        502: {"model": ErrorResponse, "description": "Upstream error"},
        504: {"model": ErrorResponse, "description": "Upstream timeout"},
    },
)
async def convert(
    amount: Annotated[Decimal, Query(gt=0, max_digits=18, decimal_places=2)],
    source_currency: Annotated[str, Query(alias="from")],
    target_currency: Annotated[str, Query(alias="to")],
    asked_date: Annotated[date, Query(alias="date")],
    client: Annotated[httpx.AsyncClient, Depends(get_http_client)],
) -> Response:
    source_currency = source_currency.upper()
    target_currency = target_currency.upper()

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

    query = ConversionQuery(
        amount=amount,
        source_currency=source_currency,
        target_currency=target_currency,
        asked_date=asked_date,
    )

    today_utc = datetime.now(timezone.utc).date()
    if query.asked_date > today_utc:
        raise ServiceError(422, "future_date", "The requested date cannot be in the future.")
    if query.asked_date < ECB_SERIES_START:
        raise ServiceError(
            422,
            "date_out_of_range",
            "The requested date is before the ECB exchange-rate series began.",
        )

    rate, rate_date = await fetch_rate(
        query.source_currency,
        query.target_currency,
        query.asked_date,
        client,
    )
    try:
        with localcontext() as decimal_context:
            decimal_context.prec = MAX_AMOUNT_DIGITS + MAX_RATE_DIGITS + 4
            result = (query.amount * rate).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
    except DecimalException as exc:
        raise ServiceError(
            502,
            "invalid_upstream_response",
            "The exchange-rate provider returned an invalid response.",
        ) from exc

    response = ConversionResponse(
        amount=query.amount,
        source_currency=query.source_currency,
        target_currency=query.target_currency,
        rate=rate,
        result=result,
        rate_date=rate_date,
        asked_date=query.asked_date,
        source=SOURCE,
    )
    return DecimalJSONResponse(response.model_dump(by_alias=True))
