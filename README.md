# FX conversion tool

A small FastAPI service that converts an amount using daily European Central
Bank reference rates supplied by the Frankfurter v1 API.

## Run

Requires Python 3.11 or newer.

On Ubuntu/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

On Windows PowerShell, create and populate the virtual environment with:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then run `./run.sh` from Git Bash or WSL. Both project scripts locate the
repository and prefer its `.venv` automatically; activating the environment is
optional. If `.venv` is absent, they fall back to an available `python3` or
`python` command.

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

The unit/contract tests replace Frankfurter with a fake HTTP transport. A final
process acceptance test starts a fake provider on loopback and launches the
service through `run.sh`; no external network is used. The suite also passes
when the parent `FX_UPSTREAM_BASE` points to a closed port.

The final expected-versus-created results are recorded in
[`ACCEPTANCE_REPORT.md`](ACCEPTANCE_REPORT.md).

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
again. Simultaneous misses for the same key also share one upstream request.
Errors are not cached, and the cache is cleared on restart.

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
using `ROUND_HALF_UP`. Decimal values are emitted as JSON numbers without first
being converted to binary `float`, so accepted values do not silently lose
digits at the HTTP boundary.

Upstream responses are accepted only when their base, target, rate and date
match the requested operation. A rate must be a JSON number (not a numeric
string or boolean), positive and finite, with at most 18 significant/integer
digits and 12 decimal places. Values outside that defensive calculation range
produce `invalid_upstream_response` rather than an uncontrolled arithmetic
failure.
