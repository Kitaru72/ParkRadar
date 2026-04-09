from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = BASE_DIR / "app"
DATA_DIR = APP_DIR / "data"
STATIC_DIR = APP_DIR / "static"
UPLOADS_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "parkradar.db"

APP_NAME = "ParkRadar"
APP_TAGLINE = "Понимаем парковку до того, как вы приедете"

AUTH_COOKIE_NAME = "parkradar_admin_session"
ADMIN_EMAIL = "admin@parkradar.local"
ADMIN_PASSWORD = "Admin123!"

SECRET_KEY = os.getenv("PARKRADAR_SECRET_KEY", "parkradar-demo-secret")
SESSION_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "24"))
RESET_TOKEN_TTL_HOURS = int(os.getenv("RESET_TOKEN_TTL_HOURS", "2"))
AUTH_DEBUG_RETURN_RESET_TOKEN = os.getenv("AUTH_DEBUG_RETURN_RESET_TOKEN", "true").lower() == "true"
AUTH_COOKIE_SECURE = os.getenv("AUTH_COOKIE_SECURE", "false").lower() == "true"

PUSH_PROVIDER = os.getenv("PUSH_PROVIDER", "").lower()
FCM_SERVER_KEY = os.getenv("FCM_SERVER_KEY", "")

DDOS_MAX_REQUESTS_PER_MINUTE = int(os.getenv("DDOS_MAX_REQUESTS_PER_MINUTE", "120"))
AUTH_MAX_REQUESTS_PER_MINUTE = int(os.getenv("AUTH_MAX_REQUESTS_PER_MINUTE", "20"))

CAPTCHA_ENABLED = False

DEMO_LOCATIONS = {
    "екатеринбург, улица малышева 51": {
        "address": "Екатеринбург, улица Малышева, 51",
        "lat": 56.835642,
        "lon": 60.614763,
    },
    "малышева 51 екатеринбург": {
        "address": "Екатеринбург, улица Малышева, 51",
        "lat": 56.835642,
        "lon": 60.614763,
    },
    "гринвич екатеринбург": {
        "address": "Екатеринбург, улица 8 Марта, 46",
        "lat": 56.829936,
        "lon": 60.598203,
    },
    "екатеринбург сити центр": {
        "address": "Екатеринбург, проспект Ленина, 36",
        "lat": 56.838851,
        "lon": 60.614972,
    },
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
