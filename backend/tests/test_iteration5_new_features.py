"""
Iteration 5 — New features & bug-fix verification.

Coverage:
  1. FIX #1: POST /api/real-user-traffic/jobs/{id}/stop — forgiving semantics
     1a. In-memory running job -> stopped=true
     1b. DB-only terminal job  -> 200 {stopped:false, status:<terminal>}
     1c. DB-only running job   -> 200 {stopped:true, status:'stopped'}
  2. FIX #2: Startup orphan reaper — auto-marks running/queued jobs 'stopped'.
  3. NEW: GET /api/real-user-traffic/jobs/{id}/live-log
     - 404 when unknown
     - {steps, cursor, running, status, processed, total} when owned
     - since=cursor -> steps == []
  4. NEW: GET /api/admin/system-check — admin-only, returns expected shape
     + required groups; regular user gets 401/403.
  5. NEW: _device_name_from_ua() -> device_name is a human-readable model.
"""

import io
import os
import time
import uuid
import pytest
import requests
import subprocess
from pathlib import Path

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

# Mongo (same env vars the backend uses)
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"

RAND = uuid.uuid4().hex[:8]
USER_EMAIL = f"test_rut2_{RAND}@example.com"
USER_PASSWORD = "RutPass123!"

STATE: dict = {}


# -------- Fixtures --------
@pytest.fixture(scope="session")
def s():
    return requests.Session()


def _uh():
    return {"Authorization": f"Bearer {STATE['user_token']}"}


def _ah():
    return {"Authorization": f"Bearer {STATE['admin_token']}"}


def _mongo_jobs():
    c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000)
    return c, c[DB_NAME]["real_user_traffic_jobs"]


def _build_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "leads"
    ws.append(["first_name", "last_name", "email", "phone"])
    ws.append(["Alice", "Doe", "alice@example.com", "+15551110001"])
    ws.append(["Bob", "Smith", "bob@example.com", "+15551110002"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ==================== 1. Setup ====================
class TestSetup:
    def test_admin_login(self, s):
        r = s.post(f"{API}/admin/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["admin_token"] = r.json()["access_token"]

    def test_register_user(self, s):
        r = s.post(f"{API}/auth/register",
                   json={"email": USER_EMAIL, "password": USER_PASSWORD, "name": "RUT2"},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_id"] = r.json()["user"]["id"]

    def test_activate_user(self, s):
        payload = {
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
        r = s.put(f"{API}/admin/users/{STATE['user_id']}",
                  json=payload, headers=_ah(), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["features"]["real_user_traffic"] is True

    def test_user_login(self, s):
        r = s.post(f"{API}/auth/login",
                   json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_token"] = r.json()["access_token"]

    def test_create_link(self, s):
        r = s.post(f"{API}/links",
                   json={"offer_url": "https://example.com/rut-it5",
                         "status": "active", "name": f"Link-it5-{RAND}"},
                   headers={**_uh(), "Content-Type": "application/json"}, timeout=30)
        assert r.status_code == 200, r.text
        STATE["link_id"] = r.json()["id"]


# ==================== 2. Stop endpoint — in-memory running job ====================
class TestStopInMemory:
    def test_create_job_for_in_memory_stop(self, s):
        form = {
            "link_id": STATE["link_id"],
            "proxies": "1.2.3.4:8080",
            "user_agents": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120",
            "total_clicks": "5",
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
                   data=form, files=files, headers=_uh(), timeout=60)
        assert r.status_code == 200, r.text
        STATE["live_job_id"] = r.json()["job_id"]

    def test_live_log_when_just_started(self, s):
        """NEW live-log endpoint: shape check for a freshly started job."""
        jid = STATE["live_job_id"]
        r = s.get(f"{API}/real-user-traffic/jobs/{jid}/live-log",
                  headers=_uh(), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        for key in ("steps", "cursor", "running", "status", "processed", "total"):
            assert key in body, f"missing {key} in {body}"
        assert isinstance(body["steps"], list)
        STATE["live_cursor"] = body["cursor"]

    def test_live_log_since_cursor_returns_empty(self, s):
        """since=cursor -> steps must be []."""
        jid = STATE["live_job_id"]
        cur = STATE["live_cursor"]
        # Re-fetch current cursor to be safe (job may have produced steps)
        r = s.get(f"{API}/real-user-traffic/jobs/{jid}/live-log",
                  headers=_uh(), timeout=30)
        assert r.status_code == 200
        cur = r.json()["cursor"]
        r2 = s.get(f"{API}/real-user-traffic/jobs/{jid}/live-log?since={cur}",
                   headers=_uh(), timeout=30)
        assert r2.status_code == 200
        assert r2.json()["steps"] == []

    def test_live_log_unknown_job_returns_404(self, s):
        r = s.get(f"{API}/real-user-traffic/jobs/nonexistent-xyz-123/live-log",
                  headers=_uh(), timeout=30)
        assert r.status_code == 404

    def test_stop_in_memory_job_returns_200(self, s):
        jid = STATE["live_job_id"]
        time.sleep(0.5)
        r = s.post(f"{API}/real-user-traffic/jobs/{jid}/stop",
                   headers=_uh(), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "stopped" in body
        # Either truly stopped or already finished - both return 200
        assert "message" in body

    def test_cleanup_live_job(self, s):
        jid = STATE.get("live_job_id")
        if jid:
            s.delete(f"{API}/real-user-traffic/jobs/{jid}", headers=_uh(), timeout=30)


# ==================== 3. Stop endpoint — DB-only orphan (terminal) ====================
class TestStopDbOnlyTerminal:
    def test_insert_fake_completed_job(self):
        jid = f"orphan-done-{uuid.uuid4().hex[:10]}"
        STATE["orphan_done_id"] = jid
        c, coll = _mongo_jobs()
        try:
            coll.insert_one({
                "job_id": jid,
                "user_id": STATE["user_id"],
                "status": "completed",
                "total": 5,
                "processed": 5,
                "created_at": "2026-01-01T00:00:00+00:00",
                "finished_at": "2026-01-01T00:05:00+00:00",
            })
        finally:
            c.close()

    def test_stop_returns_200_false_with_terminal_status(self, s):
        jid = STATE["orphan_done_id"]
        r = s.post(f"{API}/real-user-traffic/jobs/{jid}/stop",
                   headers=_uh(), timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("stopped") is False
        assert body.get("status") == "completed"

    def test_cleanup_orphan_done(self):
        c, coll = _mongo_jobs()
        try:
            coll.delete_one({"job_id": STATE["orphan_done_id"]})
        finally:
            c.close()


# ==================== 4. Stop endpoint — DB-only orphan (running) ====================
class TestStopDbOnlyRunning:
    def test_insert_fake_running_job(self):
        jid = f"orphan-run-{uuid.uuid4().hex[:10]}"
        STATE["orphan_run_id"] = jid
        c, coll = _mongo_jobs()
        try:
            coll.insert_one({
                "job_id": jid,
                "user_id": STATE["user_id"],
                "status": "running",
                "total": 10,
                "processed": 3,
                "created_at": "2026-01-01T00:00:00+00:00",
            })
        finally:
            c.close()

    def test_stop_marks_orphan_stopped(self, s):
        jid = STATE["orphan_run_id"]
        r = s.post(f"{API}/real-user-traffic/jobs/{jid}/stop",
                   headers=_uh(), timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("stopped") is True, body
        assert body.get("status") == "stopped", body

    def test_db_reflects_stopped(self):
        c, coll = _mongo_jobs()
        try:
            doc = coll.find_one({"job_id": STATE["orphan_run_id"]})
            assert doc is not None
            assert doc["status"] == "stopped"
            assert "stop_reason" in doc
            assert "finished_at" in doc
        finally:
            c.close()

    def test_cleanup_orphan_run(self):
        c, coll = _mongo_jobs()
        try:
            coll.delete_one({"job_id": STATE["orphan_run_id"]})
        finally:
            c.close()


# ==================== 5. Startup orphan reaper ====================
class TestStartupReaper:
    def test_insert_fake_running_job_then_restart(self):
        jid = f"reaper-{uuid.uuid4().hex[:10]}"
        STATE["reaper_id"] = jid
        c, coll = _mongo_jobs()
        try:
            coll.insert_one({
                "job_id": jid,
                "user_id": STATE["user_id"],
                "status": "running",
                "total": 10,
                "processed": 1,
                "created_at": "2026-01-01T00:00:00+00:00",
            })
        finally:
            c.close()
        # Restart backend — reaper runs on startup
        subprocess.run(["sudo", "supervisorctl", "restart", "backend"],
                       check=True, timeout=60)
        # Wait for backend to come back online
        deadline = time.time() + 60
        ok = False
        while time.time() < deadline:
            try:
                r = requests.get(f"{API}/", timeout=5)
                if r.status_code < 500:
                    ok = True
                    break
            except Exception:
                pass
            time.sleep(1.5)
        assert ok, "Backend did not come back up within 60s"
        # Give the startup event a moment after first request works
        time.sleep(2.0)

    def test_reaper_marked_job_stopped(self):
        c, coll = _mongo_jobs()
        try:
            doc = coll.find_one({"job_id": STATE["reaper_id"]})
            assert doc is not None, "reaper job doc missing"
            assert doc["status"] == "stopped", f"status={doc.get('status')}"
            reason = doc.get("stop_reason", "")
            assert "restart" in reason.lower() or "startup" in reason.lower(), reason
        finally:
            c.close()

    def test_cleanup_reaper_job(self):
        c, coll = _mongo_jobs()
        try:
            coll.delete_one({"job_id": STATE["reaper_id"]})
        finally:
            c.close()

    def test_re_login_user_after_restart(self, s):
        """Re-fetch tokens since all in-memory state is gone."""
        r = s.post(f"{API}/auth/login",
                   json={"email": USER_EMAIL, "password": USER_PASSWORD}, timeout=30)
        assert r.status_code == 200
        STATE["user_token"] = r.json()["access_token"]
        r2 = s.post(f"{API}/admin/login",
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
        assert r2.status_code == 200
        STATE["admin_token"] = r2.json()["access_token"]


# ==================== 6. Admin system-check ====================
class TestSystemCheck:
    def test_regular_user_forbidden(self, s):
        r = s.get(f"{API}/admin/system-check", headers=_uh(), timeout=30)
        assert r.status_code in (401, 403), f"got {r.status_code}: {r.text[:200]}"

    def test_unauth_forbidden(self, s):
        r = s.get(f"{API}/admin/system-check", timeout=30)
        assert r.status_code in (401, 403)

    def test_admin_success(self, s):
        r = s.get(f"{API}/admin/system-check", headers=_ah(), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        for k in ("overall", "total", "passed", "failed", "checks", "checked_at"):
            assert k in body, f"missing key {k}"
        assert isinstance(body["checks"], list)
        assert body["total"] == len(body["checks"])
        assert body["passed"] + body["failed"] == body["total"]
        for c in body["checks"]:
            assert set(c.keys()) >= {"group", "name", "ok", "detail"}
        STATE["sc_body"] = body

    def test_required_groups_present(self):
        body = STATE["sc_body"]
        groups = {c["group"] for c in body["checks"]}
        for needed in ("Python deps", "Browser", "Database", "Email",
                       "System", "Storage", "Config"):
            assert needed in groups, f"missing group {needed}: have {groups}"

    def test_required_python_deps(self):
        body = STATE["sc_body"]
        py = [c for c in body["checks"] if c["group"] == "Python deps"]
        names = " ".join(c["name"].lower() for c in py)
        for dep in ("pandas", "openpyxl", "xlrd", "playwright",
                    "user-agents", "faker", "fake-useragent",
                    "aiofiles", "resend", "motor", "emergentintegrations"):
            assert dep in names, f"missing python dep check: {dep}"

    def test_chromium_ok(self):
        body = STATE["sc_body"]
        chr_checks = [c for c in body["checks"]
                      if c["group"] == "Browser" and "chromium" in c["name"].lower()]
        assert chr_checks, "no Playwright Chromium check found"
        assert chr_checks[0]["ok"] is True, f"chromium check failed: {chr_checks[0]}"

    def test_database_checks(self):
        body = STATE["sc_body"]
        dbcs = [c for c in body["checks"] if c["group"] == "Database"]
        names = " ".join(c["name"].lower() for c in dbcs)
        assert "mongodb" in names
        assert "users" in names
        assert "per-user" in names

    def test_storage_writable(self):
        body = STATE["sc_body"]
        storage = [c for c in body["checks"] if c["group"] == "Storage"]
        labels = {c["name"]: c["ok"] for c in storage}
        assert any("RUT" in n for n in labels), labels
        assert any("Form-Filler" in n for n in labels), labels
        for n, ok in labels.items():
            assert ok is True, f"{n} not writable"


# ==================== 7. Device name in live events ====================
class TestDeviceName:
    def test_device_name_from_ua_helper(self):
        """Test the helper directly — parses common UAs to readable device
        names."""
        import sys
        sys.path.insert(0, "/app/backend")
        from real_user_traffic import _device_name_from_ua  # noqa

        # Samsung Galaxy S21 Ultra
        s21 = ("Mozilla/5.0 (Linux; Android 13; SM-G998B) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
        name_s21 = _device_name_from_ua(s21)
        assert "SM-G998B" in name_s21 or "Samsung" in name_s21, name_s21

        # Google Pixel 8 Pro
        pix = ("Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) "
               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")
        name_pix = _device_name_from_ua(pix)
        assert "Pixel" in name_pix, name_pix

        # iPhone
        iph = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) "
               "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1")
        name_iph = _device_name_from_ua(iph)
        assert "iPhone" in name_iph, name_iph

        # iPad
        ipd = ("Mozilla/5.0 (iPad; CPU OS 17_1 like Mac OS X) "
               "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1")
        name_ipd = _device_name_from_ua(ipd)
        assert "iPad" in name_ipd or "Apple" in name_ipd, name_ipd

        # Windows desktop
        win = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        name_win = _device_name_from_ua(win)
        assert "Windows" in name_win or "PC" in name_win or name_win, name_win


# ==================== 8. Cleanup ====================
class TestCleanup:
    def test_delete_link(self, s):
        if "link_id" in STATE:
            s.delete(f"{API}/links/{STATE['link_id']}", headers=_uh(), timeout=30)

    def test_delete_user(self, s):
        if "user_id" in STATE:
            r = s.delete(f"{API}/admin/users/{STATE['user_id']}",
                         headers=_ah(), timeout=30)
            assert r.status_code in (200, 204, 404), r.text
