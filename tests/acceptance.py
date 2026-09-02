from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

PROJECT_DIR = Path(__file__).resolve().parents[1]
ASKED_DATE = "2024-08-31"
RATE_DATE = "2024-08-30"
RATE = 1.2345


class FakeFrankfurterHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, Any]] = []
    requests_lock = threading.Lock()

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        with self.requests_lock:
            self.requests.append({"path": parsed.path, "query": query})

        target = query.get("symbols", [""])[0]
        if target == "ZZZ":
            self.send_json(404, {"message": "not found"})
            return

        source = query.get("base", [""])[0]
        self.send_json(
            200,
            {
                "amount": 1,
                "base": source,
                "date": RATE_DATE,
                "rates": {target: RATE},
            },
        )

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _: str, *args: object) -> None:
        del args


def reserve_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_ready(client: httpx.Client, process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output, _ = process.communicate()
            raise RuntimeError(f"Application exited during startup:\n{output}")
        try:
            if client.get("/openapi.json").status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(0.05)
    raise TimeoutError("Application did not become ready within 10 seconds")


def main() -> None:
    FakeFrankfurterHandler.requests.clear()
    fake_server = ThreadingHTTPServer(("127.0.0.1", 0), FakeFrankfurterHandler)
    fake_port = int(fake_server.server_address[1])
    fake_thread = threading.Thread(target=fake_server.serve_forever, daemon=True)
    fake_thread.start()

    app_port = reserve_port()
    environment = os.environ.copy()
    environment.update(
        {
            "FX_UPSTREAM_BASE": f"http://127.0.0.1:{fake_port}",
            "PORT": str(app_port),
            "PYTHONUNBUFFERED": "1",
        }
    )
    process = subprocess.Popen(
        [str(PROJECT_DIR / "run.sh")],
        cwd=tempfile.gettempdir(),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    checks: list[tuple[str, str, str]] = []

    def check(name: str, expected: object, actual: object, matches: Callable[[], bool]) -> None:
        checks.append((name, repr(expected), repr(actual)))
        if not matches():
            raise AssertionError(f"{name}: expected {expected!r}, created {actual!r}")

    process_output = ""
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{app_port}", timeout=2) as client:
            wait_until_ready(client, process)

            openapi = client.get("/openapi.json")
            check(
                "Configured PORT serves the app",
                {"status": 200, "title": "fx-tool"},
                {"status": openapi.status_code, "title": openapi.json()["info"]["title"]},
                lambda: openapi.status_code == 200
                and openapi.json()["info"]["title"] == "fx-tool",
            )

            params = {"amount": "10", "from": "EUR", "to": "TRY", "date": ASKED_DATE}
            success = client.get("/tools/convert", params=params)
            expected_success = {
                "amount": 10,
                "from": "EUR",
                "to": "TRY",
                "rate": RATE,
                "result": 12.35,
                "rate_date": RATE_DATE,
                "asked_date": ASKED_DATE,
                "source": "ECB via frankfurter.dev",
            }
            check(
                "Conversion and rate provenance",
                expected_success,
                success.json(),
                lambda: success.status_code == 200 and success.json() == expected_success,
            )

            repeated = client.get("/tools/convert", params={**params, "amount": "20"})
            try_requests = [
                request
                for request in FakeFrankfurterHandler.requests
                if request["query"].get("symbols") == ["TRY"]
            ]
            check(
                "Repeated lookup uses cache",
                {"result": 24.69, "upstream_calls": 1},
                {"result": repeated.json()["result"], "upstream_calls": len(try_requests)},
                lambda: repeated.status_code == 200
                and repeated.json()["result"] == 24.69
                and len(try_requests) == 1,
            )

            calls_before_invalid_input = len(FakeFrankfurterHandler.requests)
            invalid_input = client.get("/tools/convert", params={**params, "amount": "0"})
            check(
                "Invalid input fails before upstream",
                {"status": 422, "error": "invalid_amount", "new_calls": 0},
                {
                    "status": invalid_input.status_code,
                    "error": invalid_input.json()["error"],
                    "new_calls": len(FakeFrankfurterHandler.requests) - calls_before_invalid_input,
                },
                lambda: invalid_input.status_code == 422
                and invalid_input.json()["error"] == "invalid_amount"
                and len(FakeFrankfurterHandler.requests) == calls_before_invalid_input,
            )

            missing_rate = client.get("/tools/convert", params={**params, "to": "ZZZ"})
            check(
                "Upstream not-found remains a failure",
                {"status": 404, "error": "rate_not_found"},
                {"status": missing_rate.status_code, "error": missing_rate.json()["error"]},
                lambda: missing_rate.status_code == 404
                and missing_rate.json()["error"] == "rate_not_found",
            )

            received_paths = [request["path"] for request in FakeFrankfurterHandler.requests]
            check(
                "Configured fake upstream is used",
                f"/v1/{ASKED_DATE}",
                received_paths,
                lambda: received_paths and all(path == f"/v1/{ASKED_DATE}" for path in received_paths),
            )
            check(
                "No latest fallback",
                "No path containing latest",
                received_paths,
                lambda: all("latest" not in path for path in received_paths),
            )
    finally:
        process.terminate()
        try:
            process_output, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process_output, _ = process.communicate(timeout=5)
        fake_server.shutdown()
        fake_server.server_close()
        fake_thread.join(timeout=5)

    print("\nProcess acceptance: expected vs created")
    print("| Check | Expected | Created |")
    print("|---|---|---|")
    for name, expected, actual in checks:
        print(f"| {name} | `{expected}` | `{actual}` |")
    print(f"{len(checks)} process acceptance checks passed.")

    if process.returncode not in {0, -15}:
        raise RuntimeError(f"Application stopped unexpectedly ({process.returncode}):\n{process_output}")


if __name__ == "__main__":
    main()
