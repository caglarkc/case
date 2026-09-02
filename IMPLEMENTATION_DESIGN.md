# Part A Implementation Design

This document is the coding contract for Part A. It turns the brief and the
Frankfurter research into concrete implementation decisions. Code changes must
follow this contract unless a tested API behavior proves a decision wrong.

## Scope

Build one FastAPI endpoint:

```http
GET /tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28
```

The service will use Frankfurter v1 ECB rates, calculate the converted amount,
and clearly distinguish the requested date from the date of the published rate.

Out of scope: authentication, database, UI, Docker, CI, deployment and extra
business endpoints.

## Planned files

```text
app.py                 FastAPI app, validation, upstream client and cache
requirements.txt       Runtime and test dependencies
tests/test_app.py       Offline API and failure-path tests
run.sh                 Start the service on $PORT
test.sh                Run the complete offline test suite
README.md               User-facing setup, behavior and error codes
NOTES.md                Decisions, next steps and AI usage
```

The supplied `tool.py` belongs only to Part B and will not be imported or
modified as part of the Part A implementation.

## Git workflow

- Each completed, meaningful stage will have its own commit.
- Commit messages will be concise, in English and use a conventional prefix
  such as `docs:`, `feat:`, `test:` or `fix:`.
- A stage will be checked before commit and pushed immediately after commit.
- Unrelated changes will not be grouped into the same commit.
- A failed or incomplete implementation will not be pushed as a completed
  stage.

## Public API contract

All four query parameters are required.

| Parameter | Rule |
|---|---|
| `amount` | Decimal number, greater than zero, at most 18 total digits and 2 decimal places |
| `from` | Exactly 3 letters, normalized to uppercase |
| `to` | Exactly 3 letters, normalized to uppercase |
| `date` | ISO date (`YYYY-MM-DD`), not before 1999-01-04 and not in the future |

`from` and `to` must be different. The external query name must remain `from`;
the Python identifier may use a FastAPI alias.

Successful response:

```json
{
  "amount": 250,
  "from": "EUR",
  "to": "TRY",
  "rate": 47.1234,
  "result": 11780.85,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

Failure response:

```json
{
  "error": "short_machine_code",
  "message": "A short sentence a person can understand."
}
```

Every failure must have a non-2xx HTTP status. FastAPI's default validation
body will be replaced so malformed requests also follow this shape.

## Upstream contract

Base URL:

```text
FX_UPSTREAM_BASE (default: https://api.frankfurter.dev)
```

Request:

```http
GET {FX_UPSTREAM_BASE}/v1/{asked_date}?base={from}&symbols={to}
```

Only these response values are trusted after validation:

- `base` must equal the requested source currency.
- `date` must be a valid date and must not be later than `asked_date`.
- `rates` must be an object containing the requested target currency.
- The selected rate must be a positive finite number.

An upstream response with a future `date`, mismatched `base`, missing target or
invalid rate is an invalid upstream response. The service must fail instead of
guessing or repairing the data.

No `/latest` fallback will be used for dated requests. No `/currencies` request
will be added to the conversion path: this keeps one upstream operation per
cache miss and avoids making the fake upstream implement an unnecessary route.
Syntactically valid but unsupported currencies will become `rate_not_found`
when Frankfurter returns 404.

## Date behavior

- Weekends and ECB holidays are accepted.
- Frankfurter may return the previous published rate for those dates.
- The original query date becomes `asked_date`.
- Frankfurter's response `date` becomes `rate_date`.
- A returned `rate_date` earlier than `asked_date` is valid and visible.
- A returned `rate_date` later than `asked_date` is rejected.
- Future dates are rejected before an upstream call.
- Dates before the ECB series start, 1999-01-04, are rejected before an
  upstream call.

The current date check will use UTC because Frankfurter stores dates in UTC.

## Calculation and rounding

- Parse and calculate with `Decimal`; do not use binary `float` for money.
- Preserve the upstream rate precision in the `rate` field.
- Calculate `amount * rate` before rounding.
- Round only `result` to 2 decimal places using `ROUND_HALF_UP`.
- Never convert a failed lookup into a zero rate or zero result.

## Cache design

Use an in-process bounded cache for successful rate lookups.

Cache key:

```text
(from_currency, to_currency, asked_date)
```

Cached value:

```text
(rate, rate_date)
```

Rules:

- Repeated sequential requests with the same pair and date make no new
  upstream call, even if their amounts differ.
- Only validated successful upstream responses are cached.
- Errors and timeouts are never cached.
- Historical entries need no TTL because published ECB history is treated as
  immutable for this case.
- The cache will have a fixed maximum size to prevent unbounded memory growth.
- Restarting the process clears the cache; persistence is not required.

## Error mapping

| Condition | HTTP | Error code |
|---|---:|---|
| Missing/malformed query value | 422 | `invalid_request` |
| Non-positive or over-precise amount | 422 | `invalid_amount` |
| Malformed currency code | 422 | `invalid_currency` |
| Same source and target | 422 | `same_currency` |
| Future date | 422 | `future_date` |
| Date before ECB series | 422 | `date_out_of_range` |
| Upstream 404/422 for a valid request | 404 | `rate_not_found` |
| Connection/DNS failure | 502 | `upstream_unavailable` |
| Upstream HTTP 5xx or other unexpected status | 502 | `upstream_error` |
| Non-JSON or invalid JSON schema | 502 | `invalid_upstream_response` |
| Upstream timeout | 504 | `upstream_timeout` |
| Unexpected internal failure | 500 | `internal_error` |

Messages will be short and safe. Raw exception text and upstream response
bodies will not be exposed to the caller.

## HTTP client behavior

- Use one reusable `httpx.AsyncClient`, managed by FastAPI lifespan.
- Configure explicit connect and total/read timeouts.
- Build query parameters through `httpx`, not string concatenation.
- Strip a trailing slash from `FX_UPSTREAM_BASE` before appending `/v1/...`.
- Do not retry by default. A retry could exceed the tool-call deadline and is
  not necessary to satisfy the brief.
- Close the client during application shutdown.

## Coding order

1. Add dependency manifest and application skeleton.
2. Add request validation and uniform error responses.
3. Add the Frankfurter client and strict response validation.
4. Add Decimal calculation and exact response mapping.
5. Add bounded date-aware cache.
6. Implement `run.sh`.
7. Perform a local smoke check against a controlled fake response.
8. Commit and push the working implementation as one meaningful step.

If the smoke check fails, return to the brief, this design and
`FRANKFURTER_API_REPORT.md`; correct the smallest incorrect assumption and run
the check again before committing.

## Test gate for the following step

After the implementation works, tests will be developed and evaluated as a
separate committed step. They must use a fake HTTP transport and pass while
`FX_UPSTREAM_BASE` points to a closed port.

Required groups:

- Successful conversion and precision
- Weekend/holiday date transparency
- Cache hit and cache-key isolation
- Every input validation branch
- 404, 422 and 5xx upstream responses
- Timeout and connection failure
- Non-JSON and structurally invalid JSON
- No false 200 response on any failure
- No real network access

Part B review work starts only after the Part A implementation, offline tests
and Part A documentation are complete.
