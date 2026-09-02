# FX conversion tool

A small FastAPI service that converts an amount using daily European Central
Bank reference rates supplied by the Frankfurter v1 API.

## Run

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./run.sh
```

The service listens on port `8080` by default.

```bash
curl "http://localhost:8080/tools/convert?amount=250&from=EUR&to=TRY&date=2026-08-28"
```

Example response:

```json
{
  "amount": 250.0,
  "from": "EUR",
  "to": "TRY",
  "rate": 56.1718,
  "result": 14042.95,
  "rate_date": "2026-08-28",
  "asked_date": "2026-08-28",
  "source": "ECB via frankfurter.dev"
}
```

## Test

```bash
./test.sh
```

The tests replace Frankfurter with a fake HTTP transport and make no network
requests. They also pass when `FX_UPSTREAM_BASE` points to a closed port.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `FX_UPSTREAM_BASE` | `https://api.frankfurter.dev` | Frankfurter or fake upstream base URL |
| `PORT` | `8080` | HTTP listen port |

The application appends `/v1/{date}` to the configured upstream base URL. The
real host is never used when `FX_UPSTREAM_BASE` is set.

## Request rules

- `amount`, `from`, `to` and `date` are required.
- `amount` must be positive, with at most 18 total digits and 2 decimal places.
- Currency codes must contain exactly three letters and are normalized to
  uppercase.
- Source and target currencies must differ.
- `date` must use `YYYY-MM-DD`, cannot be in the future and cannot be before
  the ECB series start on 1999-01-04.

## Date and rate behavior

Frankfurter can return the most recent published rate on weekends and ECB
holidays. The service accepts that rate but never hides the date difference:

- `asked_date` is the date requested by the caller.
- `rate_date` is copied from Frankfurter's response.

The service never calls `/latest` as a fallback for a dated request. An invalid
or unavailable rate produces an error rather than a zero or invented result.

Successful rate lookups are cached in memory by source currency, target
currency and requested date. Repeating a lookup does not call Frankfurter
again. Errors are not cached, and the cache is cleared on restart.

## Error responses

Every failure uses a non-2xx status and the same body shape:

```json
{
  "error": "invalid_amount",
  "message": "Amount is required, must be positive, and may have at most two decimal places."
}
```

| HTTP | Error code | Meaning |
|---:|---|---|
| 422 | `invalid_request` | A required value is missing or malformed |
| 422 | `invalid_amount` | Amount is missing, non-positive, non-finite, too large or too precise |
| 422 | `invalid_currency` | A currency code is missing or malformed |
| 422 | `same_currency` | Source and target currencies are the same |
| 422 | `future_date` | Requested date is in the future |
| 422 | `date_out_of_range` | Requested date predates the ECB series |
| 404 | `rate_not_found` | Frankfurter has no rate for the valid pair/date request |
| 502 | `upstream_unavailable` | Frankfurter cannot be reached |
| 502 | `upstream_error` | Frankfurter returns an unexpected HTTP error |
| 502 | `invalid_upstream_response` | Frankfurter returns non-JSON or invalid data |
| 504 | `upstream_timeout` | Frankfurter exceeds the request timeout |
| 500 | `internal_error` | An unexpected internal failure occurs |

Unknown routes and unsupported HTTP methods use `not_found` and
`method_not_allowed` respectively.

## Implementation notes

Money calculations use `Decimal`. The upstream rate is preserved at its
published precision; only the final result is rounded to two decimal places
using `ROUND_HALF_UP`. Upstream responses are accepted only when their base,
target, rate and date match the requested operation.
