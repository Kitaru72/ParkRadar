from __future__ import annotations

import json
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


BASE = "http://127.0.0.1:8000"
jar = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def call(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with opener.open(req) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    print("health", call("/health"))
    print("login", call("/auth/login", "POST", {"email": "admin@parkradar.local", "password": "Admin123!"}))
    search = call("/parking/search?q=" + urllib.parse.quote("Екатеринбург, улица Малышева 51") + "&radius_m=1000")
    print("search", search["data"]["search"]["total_free"])
    trip = call("/trip-monitoring/sessions", "POST", {"query": "Екатеринбург, улица Малышева 51", "eta_minutes": 20})
    trip_id = trip["data"]["trip_session_id"]
    print("trip", trip_id)
    print("notes_before", len(call("/trip-monitoring/notifications/pull?trip_session_id=" + urllib.parse.quote(trip_id))["data"]))
    call(
        "/test/batch-screenshots",
        "POST",
        {"items": [{"camera_id": 1, "free_a": 0, "free_b": 1, "free_c": 1, "free_d": 0, "free_pickup": 0, "status": "ok"}]},
    )
    print("runner", call("/trip-monitoring/runner/check-due", "POST", {}))
    print("notes_after", len(call("/trip-monitoring/notifications/pull?trip_session_id=" + urllib.parse.quote(trip_id))["data"]))


if __name__ == "__main__":
    main()
