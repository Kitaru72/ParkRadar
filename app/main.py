from __future__ import annotations

import json
import os
import sys
from datetime import timedelta
from pathlib import Path

from aiohttp import web

if __package__ in {None, ""}:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.config import (
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        APP_NAME,
        AUTH_COOKIE_NAME,
        AUTH_COOKIE_SECURE,
        AUTH_DEBUG_RETURN_RESET_TOKEN,
        AUTH_MAX_REQUESTS_PER_MINUTE,
        CAPTCHA_ENABLED,
        DDOS_MAX_REQUESTS_PER_MINUTE,
        SESSION_TTL_HOURS,
        STATIC_DIR,
        UPLOADS_DIR,
        ensure_dirs,
    )
    from app.db import dict_from_row, get_conn, init_db, parse_dt, utc_now, utc_now_iso
    from app.geo import geocode_query
    from app.seed import seed_demo_data
    from app.security import hash_password, new_token, sign_value, unsign_value, verify_password
    from app.services import availability_bucket, build_trip_checks, compute_search, latest_snapshots, run_due_trip_checks, save_snapshot, scheduler_ctx
else:
    from .config import (
        ADMIN_EMAIL,
        ADMIN_PASSWORD,
        APP_NAME,
        AUTH_COOKIE_NAME,
        AUTH_COOKIE_SECURE,
        AUTH_DEBUG_RETURN_RESET_TOKEN,
        AUTH_MAX_REQUESTS_PER_MINUTE,
        CAPTCHA_ENABLED,
        DDOS_MAX_REQUESTS_PER_MINUTE,
        SESSION_TTL_HOURS,
        STATIC_DIR,
        UPLOADS_DIR,
        ensure_dirs,
    )
    from .db import dict_from_row, get_conn, init_db, parse_dt, utc_now, utc_now_iso
    from .geo import geocode_query
    from .seed import seed_demo_data
    from .security import hash_password, new_token, sign_value, unsign_value, verify_password
    from .services import availability_bucket, build_trip_checks, compute_search, latest_snapshots, run_due_trip_checks, save_snapshot, scheduler_ctx


def json_response(payload: dict, status: int = 200) -> web.Response:
    return web.Response(text=json.dumps(payload, ensure_ascii=False, indent=2), status=status, content_type="application/json")


def client_ip(request: web.Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    peer = request.transport.get_extra_info("peername")
    return peer[0] if peer else "unknown"


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    response = await handler(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    response.headers["Cache-Control"] = "no-store"
    return response


@web.middleware
async def rate_limit_middleware(request: web.Request, handler):
    ip = client_ip(request)
    bucket = request.app["rate_limits"].setdefault(ip, [])
    now = utc_now().timestamp()
    bucket[:] = [item for item in bucket if now - item < 60]
    limit = AUTH_MAX_REQUESTS_PER_MINUTE if request.path.startswith("/auth/") else DDOS_MAX_REQUESTS_PER_MINUTE
    if len(bucket) >= limit:
        return json_response({"ok": False, "error": "Слишком много запросов. Попробуйте позже."}, status=429)
    bucket.append(now)
    return await handler(request)


async def load_admin_user(request: web.Request):
    raw_cookie = request.cookies.get(AUTH_COOKIE_NAME)
    if not raw_cookie:
        return None
    session_token = unsign_value(raw_cookie)
    if not session_token:
        return None
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.*, u.email, u.is_active
            FROM admin_sessions s
            JOIN admin_users u ON u.id = s.user_id
            WHERE s.session_token = ?
            """,
            (session_token,),
        ).fetchone()
        if not row:
            return None
        expires_at = parse_dt(row["expires_at"])
        if not expires_at or expires_at <= utc_now():
            conn.execute("DELETE FROM admin_sessions WHERE id = ?", (row["id"],))
            return None
        conn.execute("UPDATE admin_sessions SET last_seen_at = ? WHERE id = ?", (utc_now_iso(), row["id"]))
        return dict_from_row(row)


async def require_admin(request: web.Request):
    admin = await load_admin_user(request)
    if not admin:
        raise web.HTTPUnauthorized(text=json.dumps({"ok": False, "error": "Требуется вход администратора"}, ensure_ascii=False), content_type="application/json")
    return admin


def create_admin_session(response: web.Response, user_id: int, ip_address: str) -> None:
    session_token = new_token()
    now = utc_now()
    expires_at = now + timedelta(hours=SESSION_TTL_HOURS)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO admin_sessions (user_id, session_token, ip_address, created_at, expires_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (user_id, session_token, ip_address, now.isoformat(), expires_at.isoformat(), now.isoformat()),
        )
    response.set_cookie(
        AUTH_COOKIE_NAME,
        sign_value(session_token),
        httponly=True,
        secure=AUTH_COOKIE_SECURE,
        samesite="Lax",
        max_age=SESSION_TTL_HOURS * 3600,
        path="/",
    )


def clear_admin_session(request: web.Request, response: web.Response) -> None:
    raw_cookie = request.cookies.get(AUTH_COOKIE_NAME)
    if raw_cookie:
        session_token = unsign_value(raw_cookie)
        if session_token:
            with get_conn() as conn:
                conn.execute("DELETE FROM admin_sessions WHERE session_token = ?", (session_token,))
    response.del_cookie(AUTH_COOKIE_NAME, path="/")


async def handle_index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_admin(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "admin.html")


async def handle_manifest(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "manifest.webmanifest")


async def handle_sw(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "sw.js")


async def handle_health(request: web.Request) -> web.Response:
    return json_response({"ok": True, "service": APP_NAME, "status": "healthy", "scheduler_errors": len(request.app["scheduler_errors"])})


async def handle_geo_resolve(request: web.Request) -> web.Response:
    payload = await request.json()
    query = payload.get("query", "")
    try:
        result = await geocode_query(query)
        return json_response({"ok": True, "data": result})
    except ValueError as exc:
        return json_response({"ok": False, "error": str(exc)}, status=400)


async def handle_parking_search(request: web.Request) -> web.Response:
    query = request.query.get("q", "").strip()
    radius_m = int(request.query.get("radius_m", "1000"))
    if not query:
        return json_response({"ok": False, "error": "Укажите адрес или ссылку из карт"}, status=400)
    try:
        resolved = await geocode_query(query)
    except ValueError as exc:
        return json_response({"ok": False, "error": str(exc)}, status=400)

    with get_conn() as conn:
        result = compute_search(conn, resolved["lat"], resolved["lon"], radius_m=radius_m)
        conn.execute(
            """
            INSERT INTO user_requests (query_text, resolved_address, lat, lon, radius_m, result_total, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (query, resolved["resolved_address"], resolved["lat"], resolved["lon"], radius_m, result["total_free"], utc_now_iso()),
        )
    return json_response({"ok": True, "data": {"location": resolved, "search": result}})


async def handle_list_test_cameras(_: web.Request) -> web.Response:
    with get_conn() as conn:
        cameras = [dict_from_row(row) for row in conn.execute("SELECT * FROM test_cameras ORDER BY id").fetchall()]
    return json_response({"ok": True, "data": cameras})


async def handle_single_screenshot(request: web.Request) -> web.Response:
    admin = await require_admin(request)
    payload = {}
    image_bytes = None
    filename = None
    if request.content_type.startswith("multipart/"):
        data = await request.post()
        payload = dict(data)
        maybe_file = data.get("file")
        if maybe_file and hasattr(maybe_file, "file"):
            image_bytes = maybe_file.file.read()
            filename = maybe_file.filename
    else:
        payload = await request.json()

    if not payload.get("camera_id"):
        return json_response({"ok": False, "error": "camera_id обязателен"}, status=400)

    with get_conn() as conn:
        camera = conn.execute("SELECT * FROM test_cameras WHERE id = ?", (int(payload["camera_id"]),)).fetchone()
        if not camera:
            return json_response({"ok": False, "error": "Камера не найдена"}, status=404)
        snapshot = await save_snapshot(conn, int(payload["camera_id"]), image_bytes, filename, payload)
    return json_response({"ok": True, "data": snapshot, "meta": {"admin": admin["email"]}}, status=201)


async def handle_batch_screenshots(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await request.json()
    saved = []
    with get_conn() as conn:
        for item in payload.get("items", []):
            saved.append(await save_snapshot(conn, int(item["camera_id"]), None, None, item))
    return json_response({"ok": True, "data": saved}, status=201)


async def handle_admin_cameras(request: web.Request) -> web.Response:
    await require_admin(request)
    with get_conn() as conn:
        cameras = [dict_from_row(row) for row in conn.execute("SELECT * FROM test_cameras ORDER BY id").fetchall()]
    return json_response({"ok": True, "data": cameras})


async def handle_admin_create_camera(request: web.Request) -> web.Response:
    await require_admin(request)
    payload = await request.json()
    required = ["name", "courtyard_name", "lat", "lon"]
    if any(not payload.get(field) for field in required):
        return json_response({"ok": False, "error": "name, courtyard_name, lat и lon обязательны"}, status=400)
    now = utc_now_iso()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO test_cameras (name, courtyard_name, source_url, lat, lon, status, notes, last_capture_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                payload["name"],
                payload["courtyard_name"],
                payload.get("source_url"),
                float(payload["lat"]),
                float(payload["lon"]),
                payload.get("status", "unknown"),
                payload.get("notes"),
                now,
                now,
            ),
        )
        camera_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return json_response({"ok": True, "data": {"camera_id": camera_id}}, status=201)


async def handle_admin_camera_status(request: web.Request) -> web.Response:
    await require_admin(request)
    camera_id = int(request.match_info["camera_id"])
    payload = await request.json()
    status = payload.get("status")
    if status not in {"ok", "camera_unreachable", "unknown"}:
        return json_response({"ok": False, "error": "Некорректный статус"}, status=400)
    with get_conn() as conn:
        conn.execute("UPDATE test_cameras SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now_iso(), camera_id))
    return json_response({"ok": True, "data": {"camera_id": camera_id, "status": status}})


async def handle_admin_stats_requests(request: web.Request) -> web.Response:
    await require_admin(request)
    with get_conn() as conn:
        totals = conn.execute("SELECT COUNT(*) AS count FROM user_requests").fetchone()["count"]
        top_queries = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT query_text, COUNT(*) AS count FROM user_requests GROUP BY query_text ORDER BY count DESC, query_text ASC LIMIT 5"
            ).fetchall()
        ]
    return json_response({"ok": True, "data": {"total_requests": totals, "top_queries": top_queries}})


async def handle_admin_stats_availability(request: web.Request) -> web.Response:
    await require_admin(request)
    with get_conn() as conn:
        snapshots = latest_snapshots(conn)
        bucket_counts = {"мест много": 0, "мест достаточно": 0, "мест мало": 0, "мест нет": 0}
        for snapshot in snapshots.values():
            bucket_counts[availability_bucket(snapshot["total_free"])] += 1
    return json_response({"ok": True, "data": bucket_counts})


async def handle_runner_check_due(request: web.Request) -> web.Response:
    await require_admin(request)
    executed = await run_due_trip_checks(request.app, force=True)
    return json_response({"ok": True, "data": {"executed": executed}})


async def handle_captcha_config(_: web.Request) -> web.Response:
    return json_response({"ok": True, "data": {"enabled": CAPTCHA_ENABLED, "provider": None}})


async def handle_bootstrap_admin(_: web.Request) -> web.Response:
    with get_conn() as conn:
        row = conn.execute("SELECT id, email FROM admin_users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
    return json_response({"ok": True, "data": {"email": row["email"], "password": ADMIN_PASSWORD if row else None}})


async def handle_auth_login(request: web.Request) -> web.Response:
    payload = await request.json()
    email = payload.get("email", "").strip().lower()
    password = payload.get("password", "")
    if not email or not password:
        return json_response({"ok": False, "error": "Укажите email и пароль"}, status=400)

    with get_conn() as conn:
        user = conn.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
        if not user:
            return json_response({"ok": False, "error": "Неверный логин или пароль"}, status=401)
        locked_until = parse_dt(user["locked_until"])
        if locked_until and locked_until > utc_now():
            return json_response({"ok": False, "error": "Учетная запись временно заблокирована"}, status=423)
        if not verify_password(password, user["password_hash"]):
            failed_attempts = user["failed_attempts"] + 1
            lock_until = utc_now() + timedelta(minutes=10) if failed_attempts >= 5 else None
            conn.execute(
                "UPDATE admin_users SET failed_attempts = ?, locked_until = ?, updated_at = ? WHERE id = ?",
                (failed_attempts, lock_until.isoformat() if lock_until else None, utc_now_iso(), user["id"]),
            )
            return json_response({"ok": False, "error": "Неверный логин или пароль"}, status=401)
        conn.execute("UPDATE admin_users SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE id = ?", (utc_now_iso(), user["id"]))

    response = json_response({"ok": True, "data": {"email": email}})
    create_admin_session(response, user["id"], client_ip(request))
    return response


async def handle_auth_logout(request: web.Request) -> web.Response:
    response = json_response({"ok": True})
    clear_admin_session(request, response)
    return response


async def handle_auth_me(request: web.Request) -> web.Response:
    admin = await load_admin_user(request)
    if not admin:
        return json_response({"ok": False, "error": "Нет активной сессии"}, status=401)
    return json_response({"ok": True, "data": {"email": admin["email"]}})


async def handle_auth_forgot_password(request: web.Request) -> web.Response:
    payload = await request.json()
    email = payload.get("email", "").strip().lower()
    if not email:
        return json_response({"ok": False, "error": "Укажите email"}, status=400)
    token = None
    with get_conn() as conn:
        user = conn.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
        if user:
            token = new_token(24)
            expires_at = utc_now() + timedelta(hours=2)
            conn.execute(
                "INSERT INTO password_reset_tokens (user_id, token, expires_at, used_at, created_at) VALUES (?, ?, ?, NULL, ?)",
                (user["id"], token, expires_at.isoformat(), utc_now_iso()),
            )
    data = {"message": "Если пользователь существует, ссылка на сброс создана."}
    if token and AUTH_DEBUG_RETURN_RESET_TOKEN:
        data["reset_token"] = token
    return json_response({"ok": True, "data": data})


async def handle_auth_reset_password(request: web.Request) -> web.Response:
    payload = await request.json()
    token = payload.get("token", "")
    new_password = payload.get("new_password", "")
    if not token or not new_password:
        return json_response({"ok": False, "error": "Нужны token и new_password"}, status=400)
    with get_conn() as conn:
        reset_row = conn.execute("SELECT * FROM password_reset_tokens WHERE token = ?", (token,)).fetchone()
        if not reset_row or reset_row["used_at"] or parse_dt(reset_row["expires_at"]) <= utc_now():
            return json_response({"ok": False, "error": "Токен недействителен"}, status=400)
        conn.execute("UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE id = ?", (hash_password(new_password), utc_now_iso(), reset_row["user_id"]))
        conn.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (utc_now_iso(), reset_row["id"]))
    return json_response({"ok": True})


async def handle_create_trip_session(request: web.Request) -> web.Response:
    payload = await request.json()
    query = payload.get("query", "")
    eta_minutes = int(payload.get("eta_minutes", 20))
    device_token = payload.get("device_token")
    push_enabled = bool(payload.get("push_enabled", False))
    if eta_minutes < 1:
        return json_response({"ok": False, "error": "ETA должен быть положительным"}, status=400)
    try:
        resolved = await geocode_query(query)
    except ValueError as exc:
        return json_response({"ok": False, "error": str(exc)}, status=400)

    now = utc_now()
    public_id = f"trip_{new_token(10)}"
    target_arrival = now + timedelta(minutes=eta_minutes)
    with get_conn() as conn:
        result = compute_search(conn, resolved["lat"], resolved["lon"])
        conn.execute(
            """
            INSERT INTO trip_sessions
            (public_id, address, lat, lon, eta_minutes, status, started_at, target_arrival_at, last_known_total, device_token, push_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                public_id,
                resolved["resolved_address"],
                resolved["lat"],
                resolved["lon"],
                eta_minutes,
                now.isoformat(),
                target_arrival.isoformat(),
                result["total_free"],
                device_token,
                1 if push_enabled else 0,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        session_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        for check_type, scheduled_at in build_trip_checks(now, eta_minutes):
            conn.execute(
                "INSERT INTO trip_checks (session_id, check_type, scheduled_at, executed_at, status, observed_total, delta_total, created_at) VALUES (?, ?, ?, NULL, 'pending', NULL, NULL, ?)",
                (session_id, check_type, scheduled_at, now.isoformat()),
            )
        conn.execute(
            """
            INSERT INTO trip_notifications (session_id, title, body, payload_json, delivery_channel, read_at, created_at)
            VALUES (?, ?, ?, ?, 'pull', NULL, ?)
            """,
            (
                session_id,
                "Мониторинг поездки активирован",
                f"Стартовое количество свободных мест рядом с адресом: {result['total_free']}.",
                json.dumps({"trip_session_id": public_id, "total_free": result["total_free"]}, ensure_ascii=False),
                now.isoformat(),
            ),
        )
    return json_response({"ok": True, "data": {"trip_session_id": public_id, "address": resolved["resolved_address"], "eta_minutes": eta_minutes, "initial_total_free": result["total_free"]}}, status=201)


async def handle_get_trip_session(request: web.Request) -> web.Response:
    trip_id = request.match_info["trip_session_id"]
    with get_conn() as conn:
        session_row = conn.execute("SELECT * FROM trip_sessions WHERE public_id = ?", (trip_id,)).fetchone()
        if not session_row:
            return json_response({"ok": False, "error": "Сессия не найдена"}, status=404)
        checks = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT check_type, scheduled_at, executed_at, status, observed_total, delta_total FROM trip_checks WHERE session_id = ? ORDER BY scheduled_at",
                (session_row["id"],),
            ).fetchall()
        ]
    return json_response({"ok": True, "data": {"session": dict_from_row(session_row), "checks": checks}})


async def handle_cancel_trip_session(request: web.Request) -> web.Response:
    trip_id = request.match_info["trip_session_id"]
    with get_conn() as conn:
        updated = conn.execute("UPDATE trip_sessions SET status = 'cancelled', updated_at = ? WHERE public_id = ? AND status = 'active'", (utc_now_iso(), trip_id)).rowcount
    if not updated:
        return json_response({"ok": False, "error": "Активная сессия не найдена"}, status=404)
    return json_response({"ok": True})


async def handle_pull_notifications(request: web.Request) -> web.Response:
    trip_id = request.query.get("trip_session_id", "")
    if not trip_id:
        return json_response({"ok": False, "error": "trip_session_id обязателен"}, status=400)
    with get_conn() as conn:
        session_row = conn.execute("SELECT id FROM trip_sessions WHERE public_id = ?", (trip_id,)).fetchone()
        if not session_row:
            return json_response({"ok": False, "error": "Сессия не найдена"}, status=404)
        notifications = [
            dict_from_row(row)
            for row in conn.execute(
                "SELECT id, title, body, payload_json, delivery_channel, read_at, created_at FROM trip_notifications WHERE session_id = ? ORDER BY created_at DESC",
                (session_row["id"],),
            ).fetchall()
        ]
    return json_response({"ok": True, "data": notifications})


async def handle_mark_notifications_read(request: web.Request) -> web.Response:
    payload = await request.json()
    ids = payload.get("notification_ids", [])
    if not ids:
        return json_response({"ok": False, "error": "Нужен список notification_ids"}, status=400)
    with get_conn() as conn:
        conn.executemany("UPDATE trip_notifications SET read_at = ? WHERE id = ?", [(utc_now_iso(), int(item)) for item in ids])
    return json_response({"ok": True})


def setup_routes(app: web.Application) -> None:
    app.add_routes(
        [
            web.get("/", handle_index),
            web.get("/admin", handle_admin),
            web.get("/manifest.webmanifest", handle_manifest),
            web.get("/sw.js", handle_sw),
            web.get("/health", handle_health),
            web.post("/geo/resolve", handle_geo_resolve),
            web.get("/parking/search", handle_parking_search),
            web.get("/test/cameras", handle_list_test_cameras),
            web.post("/test/screenshots", handle_single_screenshot),
            web.post("/test/batch-screenshots", handle_batch_screenshots),
            web.get("/admin/cameras", handle_admin_cameras),
            web.post("/admin/cameras", handle_admin_create_camera),
            web.post("/admin/cameras/{camera_id}/status", handle_admin_camera_status),
            web.get("/admin/stats/requests", handle_admin_stats_requests),
            web.get("/admin/stats/availability", handle_admin_stats_availability),
            web.post("/trip-monitoring/runner/check-due", handle_runner_check_due),
            web.get("/auth/captcha-config", handle_captcha_config),
            web.post("/auth/bootstrap-admin", handle_bootstrap_admin),
            web.post("/auth/login", handle_auth_login),
            web.post("/auth/logout", handle_auth_logout),
            web.get("/auth/me", handle_auth_me),
            web.post("/auth/forgot-password", handle_auth_forgot_password),
            web.post("/auth/reset-password", handle_auth_reset_password),
            web.post("/trip-monitoring/sessions", handle_create_trip_session),
            web.get("/trip-monitoring/sessions/{trip_session_id}", handle_get_trip_session),
            web.post("/trip-monitoring/sessions/{trip_session_id}/cancel", handle_cancel_trip_session),
            web.get("/trip-monitoring/notifications/pull", handle_pull_notifications),
            web.post("/trip-monitoring/notifications/read", handle_mark_notifications_read),
        ]
    )
    app.router.add_static("/static/", path=STATIC_DIR, name="static")
    app.router.add_static("/data/", path=UPLOADS_DIR.parent, name="data")


def create_app() -> web.Application:
    ensure_dirs()
    init_db()
    seed_demo_data()
    app = web.Application(middlewares=[rate_limit_middleware, security_headers_middleware], client_max_size=20 * 1024 * 1024)
    app["rate_limits"] = {}
    app["scheduler_errors"] = []
    app.cleanup_ctx.append(scheduler_ctx)
    setup_routes(app)
    return app


app = create_app()


if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
