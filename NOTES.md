# Notes

## Decisions

I used Python and FastAPI with Frankfurter v1 because the assignment requires
ECB data and v1 directly provides the expected `date`, `base` and nested
`rates` fields.

For weekends and ECB holidays, the service accepts Frankfurter's previous
published rate. It copies the upstream `date` into `rate_date` and keeps the
caller's date in `asked_date`, so the customer can see that they differ. It
never falls back to `/latest` for a historical request.

Amounts and calculations use `Decimal`. The rate is not rounded before
multiplication; only the final result is rounded to two decimal places. A
bounded in-memory cache stores successful lookups by currency pair and asked
date. Failures are not cached.

I reject future dates, dates before 1999-01-04, malformed input and identical
currency pairs before calling the upstream. Network, timeout, HTTP and response
schema failures are returned as explicit non-2xx errors. A wrong number is
never replaced with a zero or guessed rate.

## With another day

I would add request coalescing so simultaneous identical cache misses share one
upstream call, structured operational logs and metrics, and contract tests
against a locally hosted Frankfurter instance. For multiple workers, I would
replace the per-process cache with a small shared cache while preserving the
same strict validation rules.

## AI tools

I used Codex/GPT for planning, Frankfurter documentation research, initial
implementation and test-case generation. I checked its work against the
official API documentation, made live probes for unclear date/error behavior,
ran the service against the real API, and executed all automated tests with a
closed upstream address.

## One thing the AI got wrong

The first implementation returned `Decimal` values as JSON strings under the
initial dependency versions. The success test caught the mismatch with the
required numeric response. I kept `Decimal` for calculation, converted values
only at the JSON boundary, pinned compatible dependency ranges, and reran the
offline and live checks.
