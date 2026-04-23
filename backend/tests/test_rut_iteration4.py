"""
Iteration 4 — Real User Traffic endpoint contract test.

Validates the RUT HTTP contract end-to-end with an xlsx upload after runtime
deps (openpyxl 3.1.5, xlrd 2.0.2, playwright chromium) were installed:

  POST   /api/real-user-traffic/jobs          (multipart, xlsx file, form_fill_enabled=true)
  GET    /api/real-user-traffic/jobs
  GET    /api/real-user-traffic/jobs/{job_id}
  POST   /api/real-user-traffic/jobs/{job_id}/stop
  DELETE /api/real-user-traffic/jobs/{job_id}
  GET    /api/form-filler/jobs                (sanity)

We do NOT wait for the background job to complete — proxy 1.2.3.4:8080 is
fake; we only verify the HTTP contract and job persistence.
"""

import io
import os
import time
import uuid
import pytest
import requests
from pathlib import Path

import openpyxl  # provided by the just-installed runtime dep


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

ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"

RAND = uuid.uuid4().hex[:8]
RUT_EMAIL = f"test_rut_{RAND}@example.com"
RUT_PASSWORD = "RutPass123!"

STATE: dict = {}


# -------- Fixtures --------
@pytest.fixture(scope="session")
def s():
    sess = requests.Session()
    return sess


def _uheaders():
    return {"Authorization": f"Bearer {STATE['user_token']}"}


def _ahdrs():
    return {"Authorization": f"Bearer {STATE['admin_token']}"}


def _build_xlsx_bytes() -> bytes:
    """Build a minimal xlsx in-memory with first_name/last_name/email/phone."""
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


# =================== 1. Setup: admin login, register + activate user ===================
class TestSetup:
    def test_admin_login(self, s):
        r = s.post(f"{API}/admin/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["admin_token"] = r.json()["access_token"]

    def test_register_user(self, s):
        r = s.post(f"{API}/auth/register",
                   json={"email": RUT_EMAIL, "password": RUT_PASSWORD, "name": "RUT Tester"},
                   timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        STATE["user_id"] = d["user"]["id"]

    def test_activate_user_with_rut_feature(self, s):
        payload = {
            "status": "active",
            "features": {
                "links": True,
                "clicks": True,
                "conversions": True,
                "proxies": True,
                "settings": True,
                "import_data": True,
                "real_user_traffic": True,
                "form_filler": True,
                "email_checker": True,
                "ua_generator": True,
                "vpn_ips": True,
                "proxy_ips": True,
                "max_links": 100,
                "max_clicks": 100000,
                "max_sub_users": 2,
            },
        }
        r = s.put(f"{API}/admin/users/{STATE['user_id']}",
                  json=payload, headers=_ahdrs(), timeout=30)
        assert r.status_code == 200, r.text
        feats = r.json().get("user", {}).get("features", {})
        assert feats.get("real_user_traffic") is True
        assert feats.get("form_filler") is True

    def test_user_login(self, s):
        r = s.post(f"{API}/auth/login",
                   json={"email": RUT_EMAIL, "password": RUT_PASSWORD},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["user_token"] = r.json()["access_token"]

    def test_create_link(self, s):
        r = s.post(f"{API}/links",
                   json={"offer_url": "https://example.com/rut-test", "status": "active",
                         "name": f"RUT Link {RAND}"},
                   headers={**_uheaders(), "Content-Type": "application/json"},
                   timeout=30)
        assert r.status_code == 200, r.text
        STATE["link_id"] = r.json()["id"]


# =================== 2. RUT job lifecycle ===================
class TestRutLifecycle:
    def test_create_rut_job_with_xlsx(self, s):
        xlsx_bytes = _build_xlsx_bytes()
        form = {
            "link_id": STATE["link_id"],
            "proxies": "1.2.3.4:8080",
            "user_agents": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            "total_clicks": "5",
            "concurrency": "1",
            "duration_minutes": "0",
            "skip_duplicate_ip": "true",
            "skip_vpn": "true",
            "form_fill_enabled": "true",
            "data_source": "excel",
            "skip_captcha": "true",
            "post_submit_wait": "6",
            "automation_json": '[{"action":"scroll","y":800}]',
            "self_heal": "true",
        }
        files = {"file": ("test_leads.xlsx", xlsx_bytes,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = s.post(
            f"{API}/real-user-traffic/jobs",
            data=form, files=files, headers=_uheaders(), timeout=60,
        )
        assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
        body = r.json()
        assert "job_id" in body and isinstance(body["job_id"], str)
        assert body["total"] == 5
        assert body["form_fill_enabled"] is True
        assert body["custom_automation"] is True
        assert body["proxies"] == 1
        assert body["user_agents"] == 1
        STATE["job_id"] = body["job_id"]

    def test_list_rut_jobs_contains_new_job(self, s):
        r = s.get(f"{API}/real-user-traffic/jobs", headers=_uheaders(), timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        jobs = body.get("jobs", body if isinstance(body, list) else [])
        ids = [j.get("job_id") for j in jobs]
        assert STATE["job_id"] in ids, f"job_id not in list: {ids[:5]}"

    def test_get_rut_job_detail(self, s):
        r = s.get(f"{API}/real-user-traffic/jobs/{STATE['job_id']}",
                  headers=_uheaders(), timeout=30)
        assert r.status_code == 200, r.text
        j = r.json()
        assert j.get("job_id") == STATE["job_id"]
        assert j.get("user_id") == STATE["user_id"]
        assert j.get("status") in ("pending", "queued", "running", "failed", "completed", "stopped")

    def test_stop_rut_job(self, s):
        # Give the background task a moment to pick it up (may also have already failed on fake proxy).
        time.sleep(1.0)
        r = s.post(f"{API}/real-user-traffic/jobs/{STATE['job_id']}/stop",
                   headers=_uheaders(), timeout=30)
        # Endpoint returns 200 regardless (stopped=true/false) OR 404 if already fully completed & worker dropped it
        assert r.status_code in (200, 404), r.text
        if r.status_code == 200:
            body = r.json()
            # Either a fresh stop or "already finished"
            assert "stopped" in body or "message" in body

    def test_detail_after_stop(self, s):
        time.sleep(1.5)
        r = s.get(f"{API}/real-user-traffic/jobs/{STATE['job_id']}",
                  headers=_uheaders(), timeout=30)
        assert r.status_code == 200, r.text
        status = r.json().get("status")
        # Acceptable terminal states — background may have crashed on fake proxy too
        assert status in ("stopped", "completed", "failed", "running", "pending", "queued"), status

    def test_delete_rut_job(self, s):
        r = s.delete(f"{API}/real-user-traffic/jobs/{STATE['job_id']}",
                     headers=_uheaders(), timeout=30)
        assert r.status_code == 200, r.text
        assert r.json().get("message") == "Deleted"

        # Verify gone
        r2 = s.get(f"{API}/real-user-traffic/jobs/{STATE['job_id']}",
                   headers=_uheaders(), timeout=30)
        assert r2.status_code == 404, r2.text


# =================== 3. Form-filler jobs GET sanity ===================
class TestFormFillerSanity:
    def test_form_filler_jobs_list(self, s):
        r = s.get(f"{API}/form-filler/jobs", headers=_uheaders(), timeout=30)
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:200]}"
        # Shape — list or dict-with-jobs
        body = r.json()
        assert isinstance(body, (list, dict))


# =================== 4. Validation sanity: xlsx required when form_fill=true ===================
class TestRutValidation:
    def test_missing_file_returns_400(self, s):
        form = {
            "link_id": STATE["link_id"],
            "proxies": "1.2.3.4:8080",
            "user_agents": "Mozilla/5.0 X",
            "total_clicks": "2",
            "concurrency": "1",
            "form_fill_enabled": "true",
            "data_source": "excel",
        }
        r = s.post(f"{API}/real-user-traffic/jobs",
                   data=form, headers=_uheaders(), timeout=30)
        assert r.status_code == 400, r.text
        assert "file" in r.text.lower() or "excel" in r.text.lower() or "csv" in r.text.lower()


# =================== 5. Cleanup ===================
class TestCleanup:
    def test_delete_link(self, s):
        if "link_id" in STATE:
            s.delete(f"{API}/links/{STATE['link_id']}", headers=_uheaders(), timeout=30)

    def test_admin_delete_user(self, s):
        if "user_id" in STATE:
            r = s.delete(f"{API}/admin/users/{STATE['user_id']}", headers=_ahdrs(), timeout=30)
            assert r.status_code in (200, 204, 404), r.text
