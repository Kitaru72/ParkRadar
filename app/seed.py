from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ADMIN_EMAIL, ADMIN_PASSWORD, DATA_DIR, UPLOADS_DIR
from .db import get_conn, utc_now_iso
from .security import hash_password


def _create_placeholder_image(path: Path, title: str, subtitle: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (1280, 720), color=(20, 27, 45))
    draw = ImageDraw.Draw(image)
    try:
        font_title = ImageFont.truetype("arial.ttf", 54)
        font_body = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font_title = ImageFont.load_default()
        font_body = ImageFont.load_default()
    draw.rounded_rectangle((60, 80, 1220, 640), radius=32, fill=(33, 44, 74))
    draw.text((100, 140), title, fill=(255, 255, 255), font=font_title)
    draw.text((100, 240), subtitle, fill=(200, 218, 255), font=font_body)
    draw.text((100, 320), "Demo screenshot for ParkRadar test-mode ingestion", fill=(138, 167, 224), font=font_body)
    image.save(path)


def seed_demo_data() -> None:
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        admin = conn.execute("SELECT id FROM admin_users WHERE email = ?", (ADMIN_EMAIL,)).fetchone()
        now = utc_now_iso()
        if not admin:
            conn.execute(
                """
                INSERT INTO admin_users (email, password_hash, is_active, failed_attempts, locked_until, created_at, updated_at)
                VALUES (?, ?, 1, 0, NULL, ?, ?)
                """,
                (ADMIN_EMAIL, hash_password(ADMIN_PASSWORD), now, now),
            )

        camera_count = conn.execute("SELECT COUNT(*) AS count FROM test_cameras").fetchone()["count"]
        if camera_count:
            return

        cameras = [
            ("Камера 1", "Двор Малышева", "https://example.com/camera/1", 56.835952, 60.615512, "ok", "Въезд со стороны улицы"),
            ("Камера 2", "Двор Малышева", "https://example.com/camera/2", 56.836302, 60.613902, "ok", "Гостевая парковка"),
            ("Камера 3", "Двор Малышева", "https://example.com/camera/3", 56.834952, 60.614182, "ok", "Зона возле детской площадки"),
            ("Камера 4", "Двор Малышева", "https://example.com/camera/4", 56.835202, 60.616832, "camera_unreachable", "Камера временно недоступна"),
        ]
        for name, courtyard, url, lat, lon, status, notes in cameras:
            conn.execute(
                """
                INSERT INTO test_cameras (name, courtyard_name, source_url, lat, lon, status, notes, last_capture_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (name, courtyard, url, lat, lon, status, notes, now, now, now),
            )

        stored = conn.execute("SELECT id FROM test_cameras ORDER BY id").fetchall()
        snapshots = [
            (stored[0]["id"], "camera1.png", 2, 4, 3, 1, 0, "ok"),
            (stored[1]["id"], "camera2.png", 1, 2, 2, 1, 1, "ok"),
            (stored[2]["id"], "camera3.png", 0, 1, 2, 0, 1, "ok"),
            (stored[3]["id"], "camera4.png", 0, 0, 0, 0, 0, "camera_unreachable"),
        ]
        for index, (camera_id, filename, free_a, free_b, free_c, free_d, free_pickup, status) in enumerate(snapshots, start=1):
            image_path = UPLOADS_DIR / filename
            _create_placeholder_image(image_path, f"Публичная камера #{index}", f"Тестовый скриншот: {filename}")
            total = free_a + free_b + free_c + free_d + free_pickup
            conn.execute(
                """
                INSERT INTO test_snapshots
                (camera_id, image_path, captured_at, status, free_a, free_b, free_c, free_d, free_pickup, total_free, meta_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    camera_id,
                    str(image_path.relative_to(DATA_DIR)),
                    now,
                    status,
                    free_a,
                    free_b,
                    free_c,
                    free_d,
                    free_pickup,
                    total,
                    '{"seed": true}',
                    now,
                ),
            )
            conn.execute("UPDATE test_cameras SET last_capture_at = ?, updated_at = ? WHERE id = ?", (now, now, camera_id))
