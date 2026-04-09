from __future__ import annotations

import asyncio
import math
from contextlib import suppress
from datetime import timedelta
from pathlib import Path

import aiohttp

from .config import FCM_SERVER_KEY, PUSH_PROVIDER, UPLOADS_DIR
from .db import dict_from_row, get_conn, json_dumps, json_loads, utc_now_iso
from .security import new_token


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def availability_bucket(total: int) -> str:
    if total >= 12:
        return "мест много"
    if total >= 5:
        return "мест достаточно"
    if total >= 1:
        return "мест мало"
    return "мест нет"


def latest_snapshots(conn):
    rows = conn.execute(
        """
        SELECT s.*
        FROM test_snapshots s
        INNER JOIN (
            SELECT camera_id, MAX(captured_at) AS captured_at
            FROM test_snapshots
            GROUP BY camera_id
        ) latest
            ON latest.camera_id = s.camera_id AND latest.captured_at = s.captured_at
        """
    ).fetchall()
    return {row["camera_id"]: dict_from_row(row) for row in rows}


def compute_search(conn, lat: float, lon: float, radius_m: int = 1000) -> dict:
    cameras = conn.execute("SELECT * FROM test_cameras ORDER BY id").fetchall()
    snapshots = latest_snapshots(conn)
    by_class = {"A": 0, "B": 0, "C": 0, "D": 0, "PICKUP": 0}
    sources = []
    total_free = 0
    latest_update = None

    for camera in cameras:
        distance = haversine_distance_m(lat, lon, camera["lat"], camera["lon"])
        if distance > radius_m:
            continue
        snapshot = snapshots.get(camera["id"])
        total = snapshot["total_free"] if snapshot else 0
        if snapshot:
            by_class["A"] += snapshot["free_a"]
            by_class["B"] += snapshot["free_b"]
            by_class["C"] += snapshot["free_c"]
            by_class["D"] += snapshot["free_d"]
            by_class["PICKUP"] += snapshot["free_pickup"]
            latest_update = max(latest_update or snapshot["captured_at"], snapshot["captured_at"])
        total_free += total
        sources.append(
            {
                "camera_id": camera["id"],
                "camera_name": camera["name"],
                "courtyard_name": camera["courtyard_name"],
                "status": camera["status"],
                "distance_m": round(distance),
                "latest_capture_at": snapshot["captured_at"] if snapshot else None,
                "total_free": total,
                "image_url": f"/data/{snapshot['image_path'].replace(chr(92), '/')}" if snapshot and snapshot.get("image_path") else None,
            }
        )

    sources.sort(key=lambda item: item["distance_m"])
    return {
        "total_free": total_free,
        "availability_bucket": availability_bucket(total_free),
        "by_class": by_class,
        "sources": sources,
        "latest_update": latest_update,
        "radius_m": radius_m,
        "cameras_considered": len(sources),
    }


def build_trip_checks(now, eta_minutes: int) -> list[tuple[str, str]]:
    half_minutes = max(1, eta_minutes // 2)
    pre_arrival = max(1, eta_minutes - 5)
    steps = [
        ("half_eta", now + timedelta(minutes=half_minutes)),
        ("pre_arrival", now + timedelta(minutes=pre_arrival)),
        ("fallback_plus_15", now + timedelta(minutes=eta_minutes + 15)),
    ]
    deduped = []
    seen = set()
    for name, due_at in steps:
        key = due_at.isoformat()
        if key in seen:
            continue
        seen.add(key)
        deduped.append((name, key))
    return deduped


async def maybe_send_push(notification: dict, session_row: dict) -> str:
    if not session_row.get("push_enabled") or not session_row.get("device_token"):
        return "pull"
    if PUSH_PROVIDER != "fcm" or not FCM_SERVER_KEY:
        return "pull"

    payload = {
        "to": session_row["device_token"],
        "notification": {"title": notification["title"], "body": notification["body"]},
        "data": json_loads(notification["payload_json"], {}),
    }
    headers = {"Authorization": f"key={FCM_SERVER_KEY}", "Content-Type": "application/json"}
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.post("https://fcm.googleapis.com/fcm/send", json=payload, timeout=15) as response:
                if response.status == 200:
                    return "push"
    except Exception:
        return "pull"
    return "pull"


async def run_due_trip_checks(app, force: bool = False) -> int:
    now_iso = utc_now_iso()
    with get_conn() as conn:
        if force:
            rows = conn.execute(
                """
                SELECT tc.*, ts.public_id, ts.address, ts.lat, ts.lon, ts.eta_minutes, ts.last_known_total,
                       ts.device_token, ts.push_enabled, ts.id AS session_pk
                FROM trip_checks tc
                JOIN trip_sessions ts ON ts.id = tc.session_id
                WHERE tc.status = 'pending' AND ts.status = 'active'
                ORDER BY tc.scheduled_at ASC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT tc.*, ts.public_id, ts.address, ts.lat, ts.lon, ts.eta_minutes, ts.last_known_total,
                       ts.device_token, ts.push_enabled, ts.id AS session_pk
                FROM trip_checks tc
                JOIN trip_sessions ts ON ts.id = tc.session_id
                WHERE tc.status = 'pending' AND tc.scheduled_at <= ? AND ts.status = 'active'
                ORDER BY tc.scheduled_at ASC
                """,
                (now_iso,),
            ).fetchall()

        executed = 0
        for row in rows:
            session_payload = {
                "id": row["session_pk"],
                "public_id": row["public_id"],
                "address": row["address"],
                "lat": row["lat"],
                "lon": row["lon"],
                "eta_minutes": row["eta_minutes"],
                "push_enabled": bool(row["push_enabled"]),
                "device_token": row["device_token"],
                "last_known_total": row["last_known_total"],
            }
            result = compute_search(conn, row["lat"], row["lon"])
            observed_total = result["total_free"]
            previous_total = row["last_known_total"]
            delta = None if previous_total is None else observed_total - previous_total

            if force or previous_total is None or abs(delta or 0) >= 1:
                if previous_total is None:
                    title = "Мониторинг поездки запущен"
                    body = f"Сейчас рядом с адресом доступно {observed_total} мест."
                elif observed_total > previous_total:
                    title = "Мест стало больше"
                    body = f"Количество свободных мест выросло с {previous_total} до {observed_total}."
                elif observed_total < previous_total:
                    title = "Мест стало меньше"
                    body = f"Количество свободных мест снизилось с {previous_total} до {observed_total}."
                else:
                    title = "Статус парковки подтвержден"
                    body = f"Свободных мест по-прежнему {observed_total}."
                payload_json = json_dumps({"trip_session_id": row["public_id"], "total_free": observed_total, "check_type": row["check_type"]})
                channel = await maybe_send_push(
                    {"title": title, "body": body, "payload_json": payload_json},
                    session_payload,
                )
                conn.execute(
                    """
                    INSERT INTO trip_notifications (session_id, title, body, payload_json, delivery_channel, read_at, created_at)
                    VALUES (?, ?, ?, ?, ?, NULL, ?)
                    """,
                    (row["session_pk"], title, body, payload_json, channel, now_iso),
                )

            conn.execute(
                """
                UPDATE trip_checks
                SET executed_at = ?, status = 'completed', observed_total = ?, delta_total = ?
                WHERE id = ?
                """,
                (now_iso, observed_total, delta, row["id"]),
            )
            conn.execute("UPDATE trip_sessions SET last_known_total = ?, updated_at = ? WHERE id = ?", (observed_total, now_iso, row["session_pk"]))
            executed += 1
        return executed


async def scheduler_ctx(app):
    stop_event = asyncio.Event()

    async def worker() -> None:
        while not stop_event.is_set():
            try:
                await run_due_trip_checks(app)
            except Exception as exc:
                app["scheduler_errors"].append({"at": utc_now_iso(), "error": str(exc)})
            await asyncio.sleep(5)

    task = asyncio.create_task(worker())
    app["scheduler_task"] = task
    yield
    stop_event.set()
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


async def save_snapshot(conn, camera_id: int, image_bytes: bytes | None, filename: str | None, payload: dict) -> dict:
    captured_at = payload.get("captured_at") or utc_now_iso()
    free_a = int(payload.get("free_a", 0))
    free_b = int(payload.get("free_b", 0))
    free_c = int(payload.get("free_c", 0))
    free_d = int(payload.get("free_d", 0))
    free_pickup = int(payload.get("free_pickup", 0))
    total = free_a + free_b + free_c + free_d + free_pickup
    status = payload.get("status", "ok")
    image_path = None
    if image_bytes and filename:
        safe_name = f"{camera_id}_{new_token(8)}_{Path(filename).name}"
        target = UPLOADS_DIR / safe_name
        target.write_bytes(image_bytes)
        image_path = str(target.relative_to(UPLOADS_DIR.parent))
    conn.execute(
        """
        INSERT INTO test_snapshots
        (camera_id, image_path, captured_at, status, free_a, free_b, free_c, free_d, free_pickup, total_free, meta_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            camera_id,
            image_path,
            captured_at,
            status,
            free_a,
            free_b,
            free_c,
            free_d,
            free_pickup,
            total,
            json_dumps({"manual": True}),
            utc_now_iso(),
        ),
    )
    conn.execute("UPDATE test_cameras SET status = ?, last_capture_at = ?, updated_at = ? WHERE id = ?", (status, captured_at, utc_now_iso(), camera_id))
    snapshot_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return {"snapshot_id": snapshot_id, "camera_id": camera_id, "captured_at": captured_at, "status": status, "total_free": total}
