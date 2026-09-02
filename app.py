from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import AsyncIterator

import httpx
from fastapi import Depends, FastAPI, Query, Request


UPSTREAM_BASE = os.getenv("FX_UPSTREAM_BASE", "https://api.frankfurter.dev").rstrip("/")
SOURCE = "ECB via frankfurter.dev"

RateCacheKey = tuple[str, str, date]
RateCacheValue = tuple[Decimal, date]

_rate_cache: dict[RateCacheKey, RateCacheValue] = {}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with httpx.AsyncClient() as client:
        app.state.http_client = client
        yield


app = FastAPI(title="fx-tool", version="1.0.0", lifespan=lifespan)


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
        return _rate_cache[cache_key]

    response = await client.get(
        f"{UPSTREAM_BASE}/v1/{asked_date.isoformat()}",
        params={"base": source_currency, "symbols": target_currency},
    )
    response.raise_for_status()
    payload = response.json()

    rate = Decimal(str(payload["rates"][target_currency]))
    rate_date = date.fromisoformat(payload["date"])
    value = (rate, rate_date)
    _rate_cache[cache_key] = value
    return value


@app.get("/tools/convert")
async def convert(
    amount: Decimal = Query(gt=0),
    source_currency: str = Query(alias="from", min_length=3, max_length=3),
    target_currency: str = Query(alias="to", min_length=3, max_length=3),
    asked_date: date = Query(alias="date"),
    client: httpx.AsyncClient = Depends(get_http_client),
) -> dict[str, object]:
    source_currency = source_currency.upper()
    target_currency = target_currency.upper()

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
