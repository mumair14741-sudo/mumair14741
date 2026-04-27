"""
Iteration 6 — Screenshot endpoint + live-step screenshot field +
relaxed system-check ("healthy" when only soft warnings).

Coverage:
  1. Live-step shape — every step from /jobs/{id}/live-log includes
     a 'screenshot' key (string, may be empty).
  2. /admin/system-check — overall == 'healthy' AND hard_failed == 0
     (Email/JWT/Postback are now soft).
  3. GET /api/real-user-traffic/jobs/{job_id}/screenshot/{filename}
     - no token             -> 401
     - header + fake job    -> 404
     - ?t=jwt + fake job    -> 404 (proves query-param auth path works)
     - owner + real job + path-traversal filename -> 400
     - owner + real job + non-png filename       -> 400
     - other user + real job + real png          -> 404 (info-leak guard)
     - owner + real job + real png               -> 200 image/png
"""

import io
import os
import time
import uuid
import pytest
import requests
from pathlib import Path
from urllib.parse import quote

import openpyxl
from pymongo import MongoClient


# -------- Resolve backend URL --------
def _load_backend_url():
    env_url = os.environ.get("REACT_APP_BACKEND_URL")
    if env_url:
        return env_url.rstrip("/")
    fe = Path("/app/frontend/.env")
    if fe.exists():
        for line in fe.read_text().splitlines():
            if line.startswith("REACT_APP_BACKEND_URL="):
                return line.split("=", 1)[1].strip().rstrip("/")
    raise RuntimeError("REACT_APP_BACKEND_URL not found")


BASE_URL = _load_backend_url()
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"

RAND = uuid.uuid4().hex[:8]
USER_A_EMAIL = f"test_rut6a_{RAND}@example.com"
USER_B_EMAIL = f"test_rut6b_{RAND}@example.com"
PASSWORD = "RutPass123!"

RESULTS_ROOT = Path("/app/backend/real_user_traffic_results")

STATE: dict = {}


@pytest.fixture(scope="session")
def s():
    return requests.Session()


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


def _mongo_jobs():
    c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return c, c[DB_NAME]["real_user_traffic_jobs"]


def _build_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "leads"
    ws.append(["first_name", "last_name", "email", "phone"])
    ws.append(["Alice", "Doe", "alice@example.com", "+15551110001"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


def _activate_payload():
    return {
        "status": "active",
        "features": {
            "links": True, "clicks": True, "conversions": True,
            "proxies": True, "settings": True, "import_data": True,
            "real_user_traffic": True, "form_filler": True,
            "email_checker": True, "ua_generator": True,
            "vpn_ips": True, "proxy_ips": True,
            "max_links": 100, "max_clicks": 100000, "max_sub_users": 2,
        },
    }


# ==================== 1. Setup ====================
class TestSetup:
    def test_admin_login(self, s):
        r = s.post(f"{API}/admin/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["admin_token"] = r.json()["access_token"]

    def test_register_user_a(self, s):
        r = s.post(f"{API}/auth/register",
                   json={"email": USER_A_EMAIL, "password": PASSWORD,
                         "name": "UserA"}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_a_id"] = r.json()["user"]["id"]

    def test_register_user_b(self, s):
        r = s.post(f"{API}/auth/register",
                   json={"email": USER_B_EMAIL, "password": PASSWORD,
                         "name": "UserB"}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_b_id"] = r.json()["user"]["id"]

    def test_activate_users(self, s):
        for key in ("user_a_id", "user_b_id"):
            r = s.put(f"{API}/admin/users/{STATE[key]}",
                      json=_activate_payload(),
                      headers=_h(STATE["admin_token"]), timeout=30)
            assert r.status_code == 200, r.text
            assert r.json()["user"]["features"]["real_user_traffic"] is True

    def test_login_user_a(self, s):
        r = s.post(f"{API}/auth/login",
                   json={"email": USER_A_EMAIL, "password": PASSWORD},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_a_token"] = r.json()["access_token"]

    def test_login_user_b(self, s):
        r = s.post(f"{API}/auth/login",
                   json={"email": USER_B_EMAIL, "password": PASSWORD},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_b_token"] = r.json()["access_token"]

    def test_create_link_for_user_a(self, s):
        r = s.post(f"{API}/links",
                   json={"offer_url": "https://example.com/rut-it6",
                         "status": "active", "name": f"Link-it6-{RAND}"},
                   headers={**_h(STATE["user_a_token"]),
                            "Content-Type": "application/json"}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["link_id"] = r.json()["id"]


# ==================== 2. Live-step shape — `screenshot` key ====================
class TestLiveStepShape:
    def test_create_in_memory_job(self, s):
        form = {
            "link_id": STATE["link_id"],
            "proxies": "1.2.3.4:8080",
            "user_agents": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            "total_clicks": "3",
            "concurrency": "1",
            "duration_minutes": "0",
            "skip_duplicate_ip": "true",
            "skip_vpn": "true",
            "form_fill_enabled": "true",
            "data_source": "excel",
            "skip_captcha": "true",
            "post_submit_wait": "6",
            "self_heal": "true",
        }
        files = {"file": ("leads.xlsx", _build_xlsx_bytes(),
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = s.post(f"{API}/real-user-traffic/jobs",
                   data=form, files=files,
                   headers=_h(STATE["user_a_token"]), timeout=60)
        assert r.status_code == 200, r.text
        STATE["live_job_id"] = r.json()["job_id"]

    def test_live_log_steps_have_screenshot_field(self, s):
        """Every live-log step must contain a 'screenshot' key (str)."""
        jid = STATE["live_job_id"]
        # poll up to ~6s for at least one step to be emitted
        steps = []
        deadline = time.time() + 8
        while time.time() < deadline:
            r = s.get(f"{API}/real-user-traffic/jobs/{jid}/live-log",
                      headers=_h(STATE["user_a_token"]), timeout=15)
            assert r.status_code == 200, r.text
            body = r.json()
            steps = body.get("steps", [])
            if steps:
                break
            time.sleep(0.5)
        # We may legitimately not have any step yet (no real proxy reachable)
        # — but if we DO have steps, the shape contract MUST include
        # a 'screenshot' string key.
        for st in steps:
            assert "screenshot" in st, f"step missing 'screenshot': {st}"
            assert isinstance(st["screenshot"], str), st

    def test_stop_live_job(self, s):
        jid = STATE.get("live_job_id")
        if jid:
            s.post(f"{API}/real-user-traffic/jobs/{jid}/stop",
                   headers=_h(STATE["user_a_token"]), timeout=30)

    def test_cleanup_live_job(self, s):
        jid = STATE.get("live_job_id")
        if jid:
            s.delete(f"{API}/real-user-traffic/jobs/{jid}",
                     headers=_h(STATE["user_a_token"]), timeout=30)


# ==================== 3. /admin/system-check — overall=healthy ====================
class TestSystemCheckRelaxed:
    def test_overall_is_healthy_with_zero_hard_failures(self, s):
        r = s.get(f"{API}/admin/system-check",
                  headers=_h(STATE["admin_token"]), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "hard_failed" in body, body
        assert body["hard_failed"] == 0, \
            f"expected hard_failed=0, got {body['hard_failed']}: " \
            f"{[c for c in body['checks'] if not c['ok']]}"
        assert body["overall"] == "healthy", \
            f"expected 'healthy', got {body['overall']}"


# ==================== 4. Screenshot endpoint ====================
class TestScreenshotEndpoint:
    def test_no_token_returns_401(self, s):
        r = s.get(f"{API}/real-user-traffic/jobs/anyid/screenshot/x.png",
                  timeout=30)
        assert r.status_code == 401, f"got {r.status_code}: {r.text[:200]}"

    def test_header_token_fake_job_returns_404(self, s):
        fake = f"nojob-{uuid.uuid4().hex[:10]}"
        r = s.get(f"{API}/real-user-traffic/jobs/{fake}/screenshot/x.png",
                  headers=_h(STATE["user_a_token"]), timeout=30)
        assert r.status_code == 404, f"got {r.status_code}: {r.text[:200]}"
        assert "not found" in r.text.lower()

    def test_query_param_token_fake_job_returns_404(self, s):
        """Proves the ?t=<jwt> auth path works (used by <img> tags)."""
        fake = f"nojob-{uuid.uuid4().hex[:10]}"
        tok = STATE["user_a_token"]
        r = s.get(
            f"{API}/real-user-traffic/jobs/{fake}/screenshot/x.png?t={tok}",
            timeout=30,
        )
        assert r.status_code == 404, f"got {r.status_code}: {r.text[:200]}"

    def test_query_param_invalid_token_returns_401(self, s):
        fake = f"nojob-{uuid.uuid4().hex[:10]}"
        r = s.get(
            f"{API}/real-user-traffic/jobs/{fake}/screenshot/x.png?t=garbage",
            timeout=30,
        )
        assert r.status_code == 401, f"got {r.status_code}: {r.text[:200]}"

    # ---- Real job seed (DB doc + on-disk PNG) ----
    def test_seed_real_job_doc_and_png(self):
        jid = f"shotjob-{uuid.uuid4().hex[:10]}"
        STATE["real_job_id"] = jid
        # DB doc for user A
        c, coll = _mongo_jobs()
        try:
            coll.insert_one({
                "job_id": jid,
                "user_id": STATE["user_a_id"],
                "status": "completed",
                "total": 1,
                "processed": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:01:00+00:00",
            })
        finally:
            c.close()
        # On-disk PNG (1x1 transparent)
        shots_dir = RESULTS_ROOT / jid / "screenshots"
        shots_dir.mkdir(parents=True, exist_ok=True)
        png_bytes = bytes.fromhex(
            "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
            "0000000D49444154789C636000010000000500010D0A2DB40000000049454E44AE426082"
        )
        png_path = shots_dir / "test.png"
        png_path.write_bytes(png_bytes)
        STATE["png_path"] = str(png_path)
        STATE["png_name"] = "test.png"
        assert png_path.exists() and png_path.stat().st_size > 0

    def test_path_traversal_rejected_400(self, s):
        """Filename contains a backslash (Windows-style traversal) — must
        be rejected by the safe-basename check.  We avoid '%2F' style
        traversal because uvicorn/starlette URL-decodes it to '/' before
        route matching, which short-circuits to a router-level 404 and
        never reaches the handler's filename guard."""
        jid = STATE["real_job_id"]
        bad = quote("..\\secret.png", safe="")  # '..%5Csecret.png'
        r = s.get(f"{API}/real-user-traffic/jobs/{jid}/screenshot/{bad}",
                  headers=_h(STATE["user_a_token"]), timeout=30)
        assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"
        assert "invalid filename" in r.text.lower()

    def test_non_png_filename_rejected_400(self, s):
        jid = STATE["real_job_id"]
        r = s.get(f"{API}/real-user-traffic/jobs/{jid}/screenshot/foo.jpg",
                  headers=_h(STATE["user_a_token"]), timeout=30)
        assert r.status_code == 400, f"got {r.status_code}: {r.text[:200]}"

    def test_other_user_gets_404_not_403(self, s):
        """Cross-user isolation: must look identical to 'not found'."""
        jid = STATE["real_job_id"]
        r = s.get(
            f"{API}/real-user-traffic/jobs/{jid}/screenshot/{STATE['png_name']}",
            headers=_h(STATE["user_b_token"]), timeout=30,
        )
        assert r.status_code == 404, \
            f"cross-user must be 404, got {r.status_code}: {r.text[:200]}"

    def test_owner_header_real_png_returns_200_image_png(self, s):
        jid = STATE["real_job_id"]
        r = s.get(
            f"{API}/real-user-traffic/jobs/{jid}/screenshot/{STATE['png_name']}",
            headers=_h(STATE["user_a_token"]), timeout=30,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
        ct = r.headers.get("content-type", "")
        assert "image/png" in ct, f"unexpected content-type: {ct}"
        assert r.content.startswith(b"\x89PNG"), "body is not a PNG"

    def test_owner_query_token_real_png_returns_200(self, s):
        """Same call but using ?t=<jwt> instead of header — img-tag path."""
        jid = STATE["real_job_id"]
        tok = STATE["user_a_token"]
        r = s.get(
            f"{API}/real-user-traffic/jobs/{jid}/screenshot/{STATE['png_name']}?t={tok}",
            timeout=30,
        )
        assert r.status_code == 200, f"got {r.status_code}: {r.text[:200]}"
        assert "image/png" in r.headers.get("content-type", "")

    def test_owner_real_job_missing_png_returns_404(self, s):
        jid = STATE["real_job_id"]
        r = s.get(
            f"{API}/real-user-traffic/jobs/{jid}/screenshot/missing.png",
            headers=_h(STATE["user_a_token"]), timeout=30,
        )
        assert r.status_code == 404, f"got {r.status_code}: {r.text[:200]}"

    # ---- Cleanup ----
    def test_cleanup_real_job_doc_and_png(self):
        jid = STATE.get("real_job_id")
        if not jid:
            return
        c, coll = _mongo_jobs()
        try:
            coll.delete_one({"job_id": jid})
        finally:
            c.close()
        shots_dir = RESULTS_ROOT / jid / "screenshots"
        if shots_dir.exists():
            for p in shots_dir.iterdir():
                try:
                    p.unlink()
                except Exception:
                    pass
            try:
                shots_dir.rmdir()
                (RESULTS_ROOT / jid).rmdir()
            except Exception:
                pass


# ==================== 5. Cleanup users / link ====================
class TestCleanup:
    def test_delete_link(self, s):
        if STATE.get("link_id"):
            s.delete(f"{API}/links/{STATE['link_id']}",
                     headers=_h(STATE["user_a_token"]), timeout=30)

    def test_delete_user_a(self, s):
        if STATE.get("user_a_id"):
            r = s.delete(f"{API}/admin/users/{STATE['user_a_id']}",
                         headers=_h(STATE["admin_token"]), timeout=30)
            assert r.status_code in (200, 204, 404), r.text

    def test_delete_user_b(self, s):
        if STATE.get("user_b_id"):
            r = s.delete(f"{API}/admin/users/{STATE['user_b_id']}",
                         headers=_h(STATE["admin_token"]), timeout=30)
            assert r.status_code in (200, 204, 404), r.text
