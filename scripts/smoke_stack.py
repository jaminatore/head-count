"""Read-only public-edge smoke checks; run after deploying to staging."""

import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def status(url, method="GET"):
    data = b'{"session":"00000000-0000-0000-0000-000000000000","token":"invalid"}' if method == "POST" else None
    request = Request(url, data=data, method=method)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with build_opener(NoRedirect).open(request, timeout=5) as response:
            return response.status, response.headers
    except HTTPError as error:
        return error.code, error.headers


def main():
    base = os.environ.get("HEADCOUNT_BASE_URL", "http://localhost:1234").rstrip("/")
    checks = [
        ("/healthz", "GET", {200}),
        ("/readyz", "GET", {200}),
        ("/metrics", "GET", {404}),
        ("/courses", "GET", {401}),
        ("/check-in", "GET", {302, 303, 307}),
        ("/scan", "POST", {401}),
    ]
    failed = False
    for path, method, expected in checks:
        try:
            actual, headers = status(base + path, method)
            ok = actual in expected
            if path == "/check-in" and ok:
                ok = headers.get("Location") == "/login"
            print(f"{'PASS' if ok else 'FAIL'} {method} {path}: {actual}")
            failed |= not ok
        except (URLError, TimeoutError) as error:
            print(f"FAIL {method} {path}: {error}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
