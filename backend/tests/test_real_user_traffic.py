"""
Backend tests for the NEW "Real User Traffic" feature.

Covers:
  - POST /api/auth/login       (existing test user with feature enabled)
  - GET  /api/real-user-traffic/devices
  - POST /api/links            (need a valid link_id for the job)
  - POST /api/real-user-traffic/jobs        (with small CSV + fake proxy)
  - GET  /api/real-user-traffic/jobs
  - GET  /api/real-user-traffic/jobs/{job_id}      (poll until completed)
  - GET  /api/real-user-traffic/jobs/{job_id}/download
  - DELETE /api/real-user-traffic/jobs/{job_id}
  - Feature-gate: second user WITHOUT real_user_traffic → 403
  - Validation: empty proxies → 400, invalid devices → 400, non-owned link_id → 404
"""
import io
import os
import time
import uuid
import zipfile

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://upload-inspect-demo.preview.emergentagent.com").rstrip("/")

TEST_EMAIL = "testuser@demo.com"
TEST_PASSWORD = "test1234"

FAKE_PROXIES = "user:pass@127.0.0.1:9999\nuser:pass@127.0.0.1:9998"
DEVICES = "iphone_15_pro,samsung_s24"


# ───────── fixtures ─────────
@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def token(api):
    r = api.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
        timeout=20,
    )
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    assert data["user"]["features"].get("real_user_traffic") is True
    return data["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


@pytest.fixture(scope="module")
def link_id(api, auth_headers):
    """Create a tracker link so the RUT job has a valid link_id + short_code."""
    payload = {
        "name": f"TEST_RUT_{uuid.uuid4().hex[:8]}",
        "offer_url": "https://example.com/offer",
        "status": "active",
    }
    r = api.post(f"{BASE_URL}/api/links", json=payload, headers=auth_headers, timeout=20)
    assert r.status_code in (200, 201), f"create link failed: {r.status_code} {r.text}"
    lid = r.json().get("id")
    assert lid
    yield lid
    # cleanup
    try:
        api.delete(f"{BASE_URL}/api/links/{lid}", headers=auth_headers, timeout=10)
    except Exception:
        pass


@pytest.fixture(scope="module")
def second_user(api):
    """Register a NEW user (via /auth/register) → DEFAULT_FEATURES has real_user_traffic=False."""
    email = f"TEST_rut_nogate_{uuid.uuid4().hex[:8]}@demo.com"
    r = api.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": "test1234", "name": "RUT Gate Test"},
        timeout=20,
    )
    if r.status_code not in (200, 201):
        pytest.skip(f"Could not register second user: {r.status_code} {r.text}")
    data = r.json()
    # Must NOT have real_user_traffic enabled by default
    assert data["user"]["features"].get("real_user_traffic") is False
    return {"email": email, "token": data["access_token"], "user_id": data["user"]["id"]}


# ───────── tests ─────────
# Feature: login
class TestAuthAndFeatures:
    def test_login_returns_feature_flag(self, token):
        assert token and isinstance(token, str) and len(token) > 10


# Feature: list device presets
class TestDevices:
    def test_list_devices(self, api, auth_headers):
        r = api.get(f"{BASE_URL}/api/real-user-traffic/devices", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        devices = r.json().get("devices")
        assert isinstance(devices, list) and len(devices) == 7, f"expected 7 presets, got {len(devices) if isinstance(devices, list) else devices}"
        # Every item has key, label, kind
        for d in devices:
            assert "key" in d and "label" in d and "kind" in d
            assert d["kind"] in ("mobile", "desktop")
        keys = {d["key"] for d in devices}
        for expected in ["iphone_15_pro", "samsung_s24", "pixel_8", "windows_chrome", "macbook_chrome"]:
            assert expected in keys, f"missing preset {expected}"

    def test_devices_feature_gate_403(self, api, second_user):
        hdr = {"Authorization": f"Bearer {second_user['token']}"}
        r = api.get(f"{BASE_URL}/api/real-user-traffic/devices", headers=hdr, timeout=15)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"


# Feature: validation errors
class TestJobValidation:
    def _csv_bytes(self):
        return b"first_name,last_name,email,phone,zip\nAlice,Smith,alice@x.com,1234567890,10001\nBob,Jones,bob@x.com,1234567891,10002\n"

    def test_empty_proxies_400(self, api, auth_headers, link_id):
        """Whitespace-only proxies should hit the manual 400 branch ('At least one proxy required').
        Note: truly empty string triggers FastAPI 422 (field required) which is also a valid reject."""
        files = {"file": ("leads.csv", self._csv_bytes(), "text/csv")}
        data = {
            "link_id": link_id,
            "proxies": "   \n  \n",           # whitespace-only → manual 400
            "devices": DEVICES,
            "concurrency": 1,
            "skip_captcha": "true",
        }
        r = api.post(f"{BASE_URL}/api/real-user-traffic/jobs",
                     headers=auth_headers, data=data, files=files, timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422 got {r.status_code} {r.text[:300]}"

    def test_invalid_devices_400(self, api, auth_headers, link_id):
        """Device string with only garbage/unknown keys must 400 (no valid device preset)."""
        files = {"file": ("leads.csv", self._csv_bytes(), "text/csv")}
        data = {
            "link_id": link_id,
            "proxies": FAKE_PROXIES,
            "devices": "  ,  ,  ",            # parses to [] → manual 400
            "concurrency": 1,
            "skip_captcha": "true",
        }
        r = api.post(f"{BASE_URL}/api/real-user-traffic/jobs",
                     headers=auth_headers, data=data, files=files, timeout=30)
        assert r.status_code in (400, 422), f"expected 400/422 got {r.status_code} {r.text[:300]}"

    def test_non_owned_link_id_404(self, api, auth_headers):
        files = {"file": ("leads.csv", self._csv_bytes(), "text/csv")}
        data = {
            "link_id": "this-link-does-not-exist-" + uuid.uuid4().hex,
            "proxies": FAKE_PROXIES,
            "devices": DEVICES,
            "concurrency": 1,
            "skip_captcha": "true",
        }
        r = api.post(f"{BASE_URL}/api/real-user-traffic/jobs",
                     headers=auth_headers, data=data, files=files, timeout=30)
        assert r.status_code == 404, f"expected 404 got {r.status_code} {r.text[:300]}"


# Feature: full happy-path job lifecycle (with fake proxies → expected failures per row)
class TestJobLifecycle:
    CSV_BYTES = b"first_name,last_name,email,phone,zip\nAlice,Smith,alice@x.com,1234567890,10001\nBob,Jones,bob@x.com,1234567891,10002\n"

    @pytest.fixture(scope="class")
    def created_job(self, api, auth_headers, link_id):
        files = {"file": ("leads.csv", self.CSV_BYTES, "text/csv")}
        data = {
            "link_id": link_id,
            "proxies": FAKE_PROXIES,
            "devices": DEVICES,
            "concurrency": 1,
            "skip_captcha": "true",
        }
        r = api.post(f"{BASE_URL}/api/real-user-traffic/jobs",
                     headers=auth_headers, data=data, files=files, timeout=30)
        assert r.status_code == 200, f"create job failed: {r.status_code} {r.text[:500]}"
        body = r.json()
        assert "job_id" in body and body.get("total") == 2
        assert body.get("devices") == ["iphone_15_pro", "samsung_s24"]
        return body["job_id"]

    def test_job_created(self, created_job):
        assert created_job and isinstance(created_job, str)

    def test_job_appears_in_list(self, api, auth_headers, created_job):
        r = api.get(f"{BASE_URL}/api/real-user-traffic/jobs", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        jobs = r.json().get("jobs", [])
        ids = [j.get("job_id") for j in jobs]
        assert created_job in ids, f"newly created job not in list: {ids[:10]}"

    def test_job_progresses_to_completed(self, api, auth_headers, created_job):
        deadline = time.time() + 120  # 2 minutes max
        last_status = None
        last_body = {}
        while time.time() < deadline:
            r = api.get(f"{BASE_URL}/api/real-user-traffic/jobs/{created_job}",
                        headers=auth_headers, timeout=15)
            assert r.status_code == 200, r.text
            last_body = r.json()
            last_status = last_body.get("status")
            if last_status in ("completed", "failed"):
                break
            time.sleep(3)
        assert last_status == "completed", f"job did not complete in time, last status={last_status}, body={last_body}"
        # With bogus proxies, all rows should fail gracefully (no 500, no exception)
        assert last_body.get("total") == 2
        assert last_body.get("processed") == 2
        # succeeded may be 0; failed can be up to 2
        assert (last_body.get("failed", 0) + last_body.get("skipped_captcha", 0) + last_body.get("succeeded", 0)) == 2

    def test_download_zip(self, api, auth_headers, created_job):
        r = api.get(f"{BASE_URL}/api/real-user-traffic/jobs/{created_job}/download",
                    headers=auth_headers, timeout=30)
        assert r.status_code == 200, f"download failed: {r.status_code} {r.text[:200]}"
        assert r.headers.get("content-type", "").startswith("application/zip"), r.headers
        # Validate it's actually a zip and contains report.csv
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert "report.csv" in names, f"report.csv missing from zip: {names}"

    def test_delete_job(self, api, auth_headers, created_job):
        r = api.delete(f"{BASE_URL}/api/real-user-traffic/jobs/{created_job}",
                       headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text
        # Verify gone
        r2 = api.get(f"{BASE_URL}/api/real-user-traffic/jobs/{created_job}",
                     headers=auth_headers, timeout=10)
        assert r2.status_code == 404
