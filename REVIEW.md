# Production review of `tool.py`

The service is not safe to release in its current form. Its main risks are not
style or maintainability issues: normal requests can silently produce a rate
for the wrong currency or date, and failures are represented as successful
financial results.

## 1. P0 — The public request contract is not implemented

The required query parameters are `from` and `date`, but the endpoint accepts
`from_` and `on` (lines 48–49). FastAPI will not automatically treat those as
aliases. A request copied from the brief can therefore ignore the requested
source currency and date, use the EUR and latest-rate defaults, and still return
HTTP 200. The response also omits the required `asked_date` field.

**Customer impact:** A customer asking for a historical USD conversion can
receive a current EUR conversion. Because the response looks successful, an
agent may confidently present the wrong amount.

**Verification:** Send the exact example URL from the brief through a fake
upstream and assert the upstream path, `base` parameter and complete response
schema. The current implementation requests `latest` with `base=EUR`.

**Revision:** Define explicit FastAPI aliases for `from` and `date`, make the
contract unambiguous with request/response models, and read the upstream host
from `FX_UPSTREAM_BASE` rather than the hardcoded URL on line 18.

## 2. P0 — Rate provenance and cache semantics corrupt historical answers

The cache key contains only the currency pair (line 28), while a rate depends
on the requested date. A cached rate is returned with the new request date
invented as its provenance (line 30). On a cache miss, the implementation also
ignores the upstream `date` and reports the requested date instead (line 44).
The `/latest` fallback on lines 36–40 can attach today's rate to an older,
future or otherwise unsupported date.

**Customer impact:** Two identical-looking successful responses may contain a
rate from a different day than `rate_date` claims. This is a silent financial
data-integrity failure and directly violates the service's core trust boundary.

**Verification:** Configure the fake upstream with different rates and response
dates for two requested dates, then call them sequentially for the same pair.
Also request a weekend and a future date. Assert both the rate and provenance,
not only the HTTP status.

**Revision:** Cache `(rate, rate_date)` by `(base, target, asked_date)`. Use the
historical endpoint once, copy `rate_date` only from its validated `date` field,
and remove the `/latest` fallback. An earlier published rate is acceptable only
when the date difference remains visible.

## 3. P0 — Failures are converted into successful zero-valued quotes

The broad exception handler on lines 71–81 returns the normal success schema
with `rate=0`, `result=0` and HTTP 200 for every failure. This includes network
errors, invalid currencies, server errors, parsing errors and programmer bugs.
The raw exception is printed while the caller receives no indication that the
conversion failed.

**Customer impact:** An upstream outage can be presented as a real zero-value
conversion. Downstream agents, billing flows or customer decisions cannot
distinguish an outage from valid financial data.

**Verification:** Make the fake upstream time out, return 500, return non-JSON,
and return a JSON object without the requested rate. Every current response is
either a false 200 or can be incorrectly recovered through `/latest`.

**Revision:** Fail closed with non-2xx responses and the required
`{"error":"code","message":"..."}` shape. Map input, not-found, timeout,
connectivity, upstream-status and schema failures separately. Do not expose raw
exception or upstream-body details and never cache failures.

## 4. P1 — Input and arithmetic rules allow inaccurate results

The endpoint uses binary `float`, accepts zero and negative amounts, does not
limit decimal precision, and does not reject identical currencies. It rounds
the rate to two decimal places before multiplication (lines 60–61), discarding
published precision before calculating the customer's result.

**Customer impact:** Valid requests can return materially inaccurate amounts,
while nonsensical requests can reach the upstream and appear successful.

**Verification:** Test a rate such as `1.005`, large amounts, zero, negative and
ten-decimal-place amounts, plus identical source and target currencies. Compare
the result with a Decimal calculation that rounds only once at the boundary.

**Revision:** Validate the domain before making an HTTP call. Use `Decimal` for
the amount, rate and multiplication, preserve rate precision, and round only
the final amount with an explicitly documented rounding policy.

## 5. P1 — The upstream client has no production failure boundaries

The client has no explicit timeout, status handling or response-schema
validation. It is created at import time and never closed. A slow provider can
hold requests indefinitely; a 500 JSON body may trigger the unrelated
`/latest` fallback; structurally incorrect 200 responses are trusted until a
late exception occurs.

**Customer impact:** Provider degradation can consume service capacity, produce
unpredictable latency and amplify the false-success behavior above.

**Verification:** Simulate connect/read timeouts, redirects, 4xx/5xx responses,
malformed JSON, a mismatched base, a missing target, a non-positive rate and a
response date later than the requested date. Verify bounded latency and exact
error mapping.

**Revision:** Manage one reusable `AsyncClient` through FastAPI lifespan, set
explicit connect/read limits, inspect status before parsing, and validate the
entire upstream payload before calculation or caching.

## Release decision

This should be treated as a no-ship until all three P0 findings are resolved and
covered by offline contract tests. They are coupled data-integrity failures:
fixing only the transport or arithmetic layer would still leave a path to a
plausible but incorrect customer-facing number.

## Things that look suspicious but are fine

- Sharing one `AsyncClient` is desirable for connection pooling; the problem is
  its missing lifecycle and timeout configuration, not the sharing itself.
- An in-process cache is proportionate for this brief; its key and provenance
  are defective, but a database or distributed cache is not required.
- `from_` is a valid Python workaround for the reserved word `from`; it becomes
  a defect only because the public query alias is missing.
- Passing a non-EUR `base` to Frankfurter v1 is supported.
- The extra `/health` endpoint is harmless, although it does not verify
  upstream readiness and is not scored by the brief.
