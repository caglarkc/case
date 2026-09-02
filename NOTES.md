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
date. Simultaneous identical cache misses share one upstream request. Failures
are not cached.

JSON numbers from the upstream are parsed directly as `Decimal`, and successful
responses render Decimal values as number tokens without a binary-float
conversion. Numeric strings, booleans and values outside the documented safe
range are treated as invalid upstream data.

I reject future dates, dates before 1999-01-04, malformed input and identical
currency pairs before calling the upstream. Network, timeout, HTTP and response
schema failures are returned as explicit non-2xx errors. A wrong number is
never replaced with a zero or guessed rate.

## With another day

I would add structured operational logs and metrics, plus a contract test
against a locally hosted Frankfurter build. For multiple workers, I would
replace the per-process cache and in-flight request map with a small shared
cache while preserving the same strict validation rules.

## AI tools

I used Codex/GPT for planning, Frankfurter documentation research, initial
implementation and test-case generation. I checked its work against the
official API documentation, made live probes for unclear date/error behavior,
ran the service against the real API, and executed all automated tests with a
closed upstream address.

## One thing the AI got wrong

The first revision looked complete because its 40 tests passed on the original
setup, but an independent Ubuntu run showed that `test.sh` depended on a
Windows-available `python` command. Additional boundary probes also showed that
the AI converted Decimal values to `float`, changing
`9999999999999999.99` into `1e+16`, and accepted numeric strings as upstream
rates. I replaced the environment assumption with `.venv`-aware scripts,
removed the float hop, tightened upstream validation and added regression tests
for each failure.
