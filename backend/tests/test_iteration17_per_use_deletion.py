"""
Iteration 17 — Per-use (real-time) deletion of consumed proxies / UAs / data
rows from the saved "Uploaded Things" batches.

User requirement (Roman Urdu/Hindi):
  "ek line use hoe wo sath he delete ho jay phr next use ho wo b delete ho jay"
  → As soon as ONE proxy / UA / data row is consumed in a visit, that single
  line must be removed IMMEDIATELY from the saved batch — not at end-of-job.

Behaviour shift verified here:
  • POST /api/real-user-traffic/jobs forwards engine_user_id +
    upload_proxy_id / upload_ua_id / upload_data_file_id to the engine.
  • run_real_user_traffic_job() now $pulls each consumed proxy / UA from the
    user's `uploaded_resources` collection IMMEDIATELY after pick_next_*().
  • $inc: {consumed_count: +1, item_count: -1} alongside each $pull.
  • Auto-delete kicks in once items[] is empty.
  • End-of-job _consume_uploads is a no-op for items already $pulled live.

Scope:
  Backend-only (RUT engine + uploads collection). We use dummy proxies
  (192.0.2.1:8080:test:test) — actual connectivity NOT required because the
  $pull happens BEFORE the visit's network call.
"""
# ── module: imports ────────────────────────────────────────────────
import io
import os
import time
import uuid
import asyncio
from pathlib import Path

import pytest
import requests
import openpyxl
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set"

load_dotenv("/app/backend/.env")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"


# ── helpers ─────────────────────────────────────────────────────────
def _hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _user_db_name(user_id: str) -> str:
    return f"trackmaster_user_{user_id.replace('-', '_')[:20]}"


async def _read_upload_doc(user_id: str, upload_id: str) -> dict:
    """Read a single uploaded_resources doc straight from Mongo (the public
    GET /api/uploads endpoint strips items[]). Used to verify live $pull."""
    client = AsyncIOMotorClient(MONGO_URL)
    try:
        d = client[_user_db_name(user_id)]
        doc = await d["uploaded_resources"].find_one(
            {"id": upload_id, "user_id": user_id}, {"_id": 0}
        )
        return doc or {}
    finally:
        client.close()


def _wait_job_terminal(user_token: str, job_id: str, timeout: int = 180) -> dict:
    """Poll the job until status is terminal (done/failed/stopped) or until
    timeout. Returns the last job doc seen."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/{job_id}",
            headers=_hdr(user_token),
            timeout=20,
        )
        if r.status_code == 200:
            last = r.json() or {}
            status = (last.get("status") or "").lower()
            if status in ("done", "failed", "stopped", "completed", "cancelled"):
                return last
        time.sleep(2)
    return last


# ── module fixture: admin login + fresh user + features + link ─────
@pytest.fixture(scope="module")
def env():
    """Stand up an isolated TEST_iter17 user with real_user_traffic + links
    feature flags enabled, plus a tracking link to point the RUT job at.
    Cleanup deletes the user + per-user DB at teardown."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})

    # Admin login
    r = s.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"admin login failed {r.status_code} {r.text}"
    admin_token = r.json()["access_token"]

    # Register fresh user
    suffix = uuid.uuid4().hex[:10]
    email = f"TEST_iter17_{suffix}@example.com"
    password = "Pass1234!"
    r = s.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "name": "Iter17 Tester", "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"register failed {r.status_code} {r.text}"
    user_id = r.json()["user"]["id"]

    # Admin enables features + activates account
    feat_payload = {
        "links": True, "clicks": True, "conversions": True, "proxies": True,
        "import_data": True, "import_traffic": True, "real_traffic": True,
        "ua_generator": True, "email_checker": True, "separate_data": True,
        "form_filler": True, "real_user_traffic": True, "settings": True,
        "max_links": 100, "max_clicks": 100000, "max_sub_users": 0,
    }
    r = s.put(
        f"{BASE_URL}/api/admin/users/{user_id}",
        json={"status": "active", "features": feat_payload},
        headers=_hdr(admin_token),
        timeout=20,
    )
    assert r.status_code == 200, f"feature enable failed {r.status_code} {r.text}"

    # Login as user
    r = s.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=20,
    )
    assert r.status_code == 200, f"user login failed {r.status_code} {r.text}"
    user_token = r.json()["access_token"]

    # Create a tracking link
    r = s.post(
        f"{BASE_URL}/api/links",
        json={
            "name": f"TEST_iter17_link_{suffix}",
            "offer_url": "https://example.com/offer-iter17",
            "status": "active",
            "allowed_countries": [],
            "allowed_os": [],
            "block_vpn": False,
            "duplicate_timer_enabled": False,
            "duplicate_timer_seconds": 30,
            "referrer_mode": "normal",
        },
        headers=_hdr(user_token),
        timeout=20,
    )
    assert r.status_code == 200, f"link create failed {r.status_code} {r.text}"
    link = r.json()
    link_id = link["id"]

    yield {
        "admin_token": admin_token,
        "user_token": user_token,
        "user_id": user_id,
        "email": email,
        "link_id": link_id,
        "short_code": link.get("short_code"),
    }

    # Teardown: drop the user + per-user DB
    try:
        s.delete(
            f"{BASE_URL}/api/admin/users/{user_id}",
            headers=_hdr(admin_token), timeout=20,
        )
    except Exception:
        pass

    async def _drop_user_db():
        client = AsyncIOMotorClient(MONGO_URL)
        try:
            await client.drop_database(_user_db_name(user_id))
        finally:
            client.close()
    try:
        asyncio.run(_drop_user_db())
    except Exception:
        pass


# ── helpers to upload + start a small RUT job ──────────────────────
DUMMY_PROXIES_5 = [
    "192.0.2.1:8080:u1:p1",
    "192.0.2.2:8080:u2:p2",
    "192.0.2.3:8080:u3:p3",
    "192.0.2.4:8080:u4:p4",
    "192.0.2.5:8080:u5:p5",
]
DUMMY_UAS_5 = [
    "Mozilla/5.0 (Linux; Android 13; SM-S901B) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S902B) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S903B) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S904B) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Linux; Android 13; SM-S905B) Chrome/120.0.0.0 Safari/537.36",
]


def _upload_proxies(env, lines):
    r = requests.post(
        f"{BASE_URL}/api/uploads/proxies",
        data={
            "name": f"TEST_iter17_proxies_{uuid.uuid4().hex[:6]}",
            "proxies": "\n".join(lines),
            "country_tag": "US",
        },
        headers=_hdr(env["user_token"]),
        timeout=30,
    )
    assert r.status_code == 200, f"upload proxies failed {r.status_code} {r.text}"
    return r.json()


def _upload_uas(env, lines):
    r = requests.post(
        f"{BASE_URL}/api/uploads/user-agents",
        data={
            "name": f"TEST_iter17_uas_{uuid.uuid4().hex[:6]}",
            "user_agents": "\n".join(lines),
            "os_tag": "android",
        },
        headers=_hdr(env["user_token"]),
        timeout=30,
    )
    assert r.status_code == 200, f"upload UAs failed {r.status_code} {r.text}"
    return r.json()


def _upload_data_file(env, rows=5):
    """Build a tiny XLSX in-memory and POST it to /api/uploads/data-file."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["first_name", "last_name", "email"])
    for i in range(rows):
        ws.append([f"First{i}", f"Last{i}", f"user{i}@example.com"])
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)

    r = requests.post(
        f"{BASE_URL}/api/uploads/data-file",
        data={"name": f"TEST_iter17_data_{uuid.uuid4().hex[:6]}"},
        files={"file": ("leads.xlsx", bio.getvalue(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=_hdr(env["user_token"]),
        timeout=30,
    )
    assert r.status_code == 200, f"upload data file failed {r.status_code} {r.text}"
    return r.json()


def _start_job(env, *, total_clicks, upload_proxy_id, upload_ua_id,
               upload_data_file_id=None):
    payload = {
        "link_id": env["link_id"],
        "total_clicks": str(total_clicks),
        "concurrency": "1",
        "duration_minutes": "0",
        "target_mode": "clicks",
        "skip_duplicate_ip": "false",
        "skip_vpn": "false",
        "follow_redirect": "false",
        "no_repeated_proxy": "true",
        "form_fill_enabled": "false",
        "skip_captcha": "true",
        "post_submit_wait": "3",
        "self_heal": "false",
        "upload_proxy_id": upload_proxy_id,
        "upload_ua_id": upload_ua_id,
    }
    if upload_data_file_id:
        payload["upload_data_file_id"] = upload_data_file_id
        payload["form_fill_enabled"] = "true"
        payload["data_source"] = "excel"

    r = requests.post(
        f"{BASE_URL}/api/real-user-traffic/jobs",
        data=payload,
        headers=_hdr(env["user_token"]),
        timeout=60,
    )
    assert r.status_code == 200, f"create job failed {r.status_code} {r.text}"
    return r.json()


# ════════════════════════════════════════════════════════════════════
# TEST 1 — POST /jobs accepts upload_*_id Form params + returns 200
# ════════════════════════════════════════════════════════════════════
class TestJobsEndpointAcceptsUploadIds:
    """POST /api/real-user-traffic/jobs still accepts the new optional Form
    fields and starts a job (200)."""

    def test_jobs_endpoint_accepts_all_three_upload_ids(self, env):
        proxy_doc = _upload_proxies(env, DUMMY_PROXIES_5)
        ua_doc = _upload_uas(env, DUMMY_UAS_5)
        data_doc = _upload_data_file(env, rows=5)

        out = _start_job(
            env, total_clicks=3,
            upload_proxy_id=proxy_doc["id"],
            upload_ua_id=ua_doc["id"],
            upload_data_file_id=data_doc["id"],
        )
        assert "job_id" in out and out["job_id"]
        assert out["proxies"] == 5
        assert out["user_agents"] == 5
        assert out["rows_loaded"] == 5

        # Wait for terminal so this test does not pollute the next ones
        _wait_job_terminal(env["user_token"], out["job_id"], timeout=180)


# ════════════════════════════════════════════════════════════════════
# TEST 2 — Live proxy removal: 5 → 2 after 3-visit job
# ════════════════════════════════════════════════════════════════════
class TestLiveProxyRemoval:

    def test_proxy_batch_shrinks_after_3_visit_job(self, env):
        proxy_doc = _upload_proxies(env, DUMMY_PROXIES_5)
        ua_doc = _upload_uas(env, DUMMY_UAS_5)
        upload_proxy_id = proxy_doc["id"]

        # Sanity — initially 5 items
        before = asyncio.run(_read_upload_doc(env["user_id"], upload_proxy_id))
        assert before.get("type") == "proxies"
        assert len(before.get("items") or []) == 5
        assert int(before.get("item_count") or 0) == 5
        assert int(before.get("consumed_count") or 0) == 0

        out = _start_job(
            env, total_clicks=3,
            upload_proxy_id=upload_proxy_id,
            upload_ua_id=ua_doc["id"],
        )
        job_id = out["job_id"]
        _wait_job_terminal(env["user_token"], job_id, timeout=240)

        # Allow fire-and-forget pulls to flush
        time.sleep(2)

        after = asyncio.run(_read_upload_doc(env["user_id"], upload_proxy_id))
        # 3 visits with no_repeated_proxy=true → 3 distinct picks → 3 pulled
        items_after = after.get("items") or []
        assert len(items_after) == 2, (
            f"Expected 2 proxies left after 3-visit job, got {len(items_after)}: {items_after}"
        )
        assert int(after.get("item_count") or 0) == 2, after
        assert int(after.get("consumed_count") or 0) == 3, after

        # GET /api/uploads list also reflects decremented item_count
        r = requests.get(
            f"{BASE_URL}/api/uploads", params={"type": "proxies"},
            headers=_hdr(env["user_token"]), timeout=20,
        )
        assert r.status_code == 200
        match = next((u for u in r.json() if u["id"] == upload_proxy_id), None)
        assert match is not None
        assert match["item_count"] == 2


# ════════════════════════════════════════════════════════════════════
# TEST 3 — Live UA removal: 5 → 2 after 3-visit job
# ════════════════════════════════════════════════════════════════════
class TestLiveUaRemoval:

    def test_ua_batch_shrinks_after_3_visit_job(self, env):
        proxy_doc = _upload_proxies(env, DUMMY_PROXIES_5)
        ua_doc = _upload_uas(env, DUMMY_UAS_5)
        upload_ua_id = ua_doc["id"]

        before = asyncio.run(_read_upload_doc(env["user_id"], upload_ua_id))
        assert before.get("type") == "user_agents"
        assert len(before.get("items") or []) == 5

        out = _start_job(
            env, total_clicks=3,
            upload_proxy_id=proxy_doc["id"],
            upload_ua_id=upload_ua_id,
        )
        _wait_job_terminal(env["user_token"], out["job_id"], timeout=240)
        time.sleep(2)

        after = asyncio.run(_read_upload_doc(env["user_id"], upload_ua_id))
        items_after = after.get("items") or []
        # UAs round-robin through 5 distinct entries → 3 distinct picks → 2 left
        assert len(items_after) == 2, (
            f"Expected 2 UAs left, got {len(items_after)}: {items_after}"
        )
        assert int(after.get("item_count") or 0) == 2
        assert int(after.get("consumed_count") or 0) == 3


# ════════════════════════════════════════════════════════════════════
# TEST 4 — Edge case: batch fully consumed → upload doc auto-deleted
# ════════════════════════════════════════════════════════════════════
class TestAutoDeleteWhenEmpty:

    def test_proxy_batch_auto_deleted_when_all_items_consumed(self, env):
        # 3 proxies, 3 visits → all consumed → doc must be deleted
        proxy_doc = _upload_proxies(env, DUMMY_PROXIES_5[:3])
        ua_doc = _upload_uas(env, DUMMY_UAS_5)
        upload_proxy_id = proxy_doc["id"]

        out = _start_job(
            env, total_clicks=3,
            upload_proxy_id=upload_proxy_id,
            upload_ua_id=ua_doc["id"],
        )
        _wait_job_terminal(env["user_token"], out["job_id"], timeout=240)
        time.sleep(2)

        after = asyncio.run(_read_upload_doc(env["user_id"], upload_proxy_id))
        assert after == {} or after is None, (
            f"Expected upload doc deleted after full consumption, still have: {after}"
        )

        # Public list endpoint also no longer returns it
        r = requests.get(
            f"{BASE_URL}/api/uploads", params={"type": "proxies"},
            headers=_hdr(env["user_token"]), timeout=20,
        )
        assert r.status_code == 200
        assert not any(u["id"] == upload_proxy_id for u in r.json())


# ════════════════════════════════════════════════════════════════════
# TEST 5 — Unused items remain (only consumed ones removed)
# ════════════════════════════════════════════════════════════════════
class TestUnusedItemsRemain:

    def test_unused_proxies_remain_in_batch(self, env):
        proxy_doc = _upload_proxies(env, DUMMY_PROXIES_5)
        ua_doc = _upload_uas(env, DUMMY_UAS_5)
        upload_proxy_id = proxy_doc["id"]

        out = _start_job(
            env, total_clicks=2,
            upload_proxy_id=upload_proxy_id,
            upload_ua_id=ua_doc["id"],
        )
        _wait_job_terminal(env["user_token"], out["job_id"], timeout=240)
        time.sleep(2)

        after = asyncio.run(_read_upload_doc(env["user_id"], upload_proxy_id))
        items_after = set(after.get("items") or [])
        # Exactly 3 of the original 5 must remain (5 - 2 used = 3)
        assert len(items_after) == 3, (
            f"Expected 3 unused proxies, got {len(items_after)}: {items_after}"
        )
        # All remaining items must be from the original list
        assert items_after.issubset(set(DUMMY_PROXIES_5))
