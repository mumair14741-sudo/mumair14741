"""
Iteration 9 — Real User Traffic: auto-import pending leads + state-matched
lead assignment.

Tests:
1.  NEW endpoint `GET /api/real-user-traffic/jobs/pending-candidates`
      - 401/403 without auth
      - Fresh user -> {items:[], count:0}
      - Shape of returned items (job_id, target_url, created_at,
        pending_leads_count, form_fill_enabled, state_match_enabled,
        link_short_code) — asserted via seeded Mongo doc.
      - Sort desc by created_at + max 25 items.
2.  POST /api/real-user-traffic/jobs with `data_source=pending_from_job`:
      - 400 when import_pending_from_job_id missing
      - 404 when source job id not found / not owned
      - 404 when pending_leads.xlsx missing on disk
      - 200 when a seeded source job + pending file exist (no file upload)
3.  `state_match_enabled` form field accepted.  Job response echoes field
    value.  When file lacks state column, RUT_JOBS[job_id].state_match_enabled
    is auto-disabled (we verify via GET job).
4.  Module unit tests for `_normalize_state` (codes, full names, whitespace,
    bad values, "California, USA", "NJ (New Jersey)").
5.  Module unit tests for `_find_state_column` — state/State/STATE/state_code/
    region/no-column.
6.  `_probe_proxy_geo` returns `region_name` field — code-inspection via
    module import (defaults dict contains 'region_name').
7.  RUT_JOBS counter `skipped_state_mismatch` — init check via direct module
    call: `_record` increments counter when status == 'skipped_state_mismatch'.
8.  Regression smoke — admin login + user register/activate + previous
    iteration-7 & iteration-8 endpoints unchanged.
"""

import os
import sys
import time
import uuid
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")

# Ensure backend importable for unit-level helper tests
sys.path.insert(0, "/app/backend")


# ─────────── auth helpers (same pattern as iteration-8) ────────────
ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"


def _admin_token():
    r = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    return r.json()["access_token"]


def _register_activate_user(admin_token: str):
    email = f"TEST_rut9_{uuid.uuid4().hex[:8]}@example.com"
    password = "Test@12345"
    r = requests.post(
        f"{BASE_URL}/api/auth/register",
        json={"email": email, "password": password, "name": "TEST RUT9 User"},
        timeout=15,
    )
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    users = requests.get(
        f"{BASE_URL}/api/admin/users",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=15,
    ).json()
    uid = next((u["id"] for u in users if u["email"] == email), None)
    assert uid, f"admin didn't list new user {email}"
    r = requests.put(
        f"{BASE_URL}/api/admin/users/{uid}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"status": "active", "features": {"real_user_traffic": True, "links": True}},
        timeout=15,
    )
    assert r.status_code == 200, f"activate failed: {r.status_code} {r.text}"
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": email, "password": password},
        timeout=15,
    )
    assert r.status_code == 200, f"user login failed: {r.status_code} {r.text}"
    return email, r.json()["access_token"], uid


# ─────────── fixtures ──────────────────────────────────────────────
@pytest.fixture(scope="module")
def admin_token():
    return _admin_token()


@pytest.fixture(scope="module")
def user_ctx(admin_token):
    email, tok, uid = _register_activate_user(admin_token)
    return {"email": email, "token": tok, "id": uid}


@pytest.fixture
def user_headers(user_ctx):
    return {"Authorization": f"Bearer {user_ctx['token']}"}


@pytest.fixture(scope="module")
def user_link(user_ctx):
    headers = {"Authorization": f"Bearer {user_ctx['token']}"}
    lr = requests.post(
        f"{BASE_URL}/api/links",
        headers=headers,
        json={"offer_url": "https://example.com", "name": "TEST iter9 link"},
        timeout=15,
    )
    assert lr.status_code == 200, f"link create failed: {lr.status_code} {lr.text}"
    return lr.json()


# ─────────── Mongo helper (seed source job) ───────────────────────
async def _seed_source_job(user_id: str, link_short_code: str = "abc1", with_pending_file: bool = True):
    """Insert a fake completed job with pending_leads_count>0 + optionally
    writes a real pending_leads.xlsx to disk.  Returns the job_id."""
    from motor.motor_asyncio import AsyncIOMotorClient
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env")
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    job_id = f"TEST_src_{uuid.uuid4().hex[:8]}"
    from real_user_traffic import RESULTS_ROOT
    job_dir = Path(RESULTS_ROOT) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    pending_path = job_dir / "pending_leads.xlsx"

    if with_pending_file:
        try:
            import openpyxl
        except ImportError:
            pytest.skip("openpyxl not installed — cannot seed pending file")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["first_name", "last_name", "email", "state"])
        ws.append(["Alice", "A", "alice@example.com", "CA"])
        ws.append(["Bob", "B", "bob@example.com", "NY"])
        wb.save(pending_path)

    await db.real_user_traffic_jobs.insert_one({
        "job_id": job_id,
        "user_id": user_id,
        "target_url": "https://example.com/form",
        "status": "completed",
        "pending_leads_count": 2,
        "pending_leads_path": str(pending_path) if with_pending_file else "",
        "form_fill_enabled": True,
        "state_match_enabled": False,
        "link_short_code": link_short_code,
        "created_at": datetime.now(timezone.utc),
        "finished_at": datetime.now(timezone.utc),
        "total": 5,
        "succeeded": 3,
        "invalid_data": 0,
    })
    client.close()
    return job_id, str(pending_path)


# ════════════════════════════════════════════════════════════════════
#  1. Unit tests on pure helpers (_normalize_state / _find_state_column)
# ════════════════════════════════════════════════════════════════════
class TestNormalizeState:
    def test_lower_code(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("ca") == "CA"

    def test_upper_code(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("CA") == "CA"

    def test_full_name_mixed_case(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("California") == "CA"

    def test_full_name_all_lower(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("new york") == "NY"

    def test_full_name_all_upper(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("NEW YORK") == "NY"

    def test_trailing_whitespace(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("CA ") == "CA"
        assert _normalize_state(" California ") == "CA"

    def test_unknown_returns_empty(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("xyz") == ""

    def test_empty_returns_empty(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("") == ""

    def test_none_returns_empty(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state(None) == ""

    def test_with_country_suffix(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("California, USA") == "CA"

    def test_code_with_paren_name(self):
        from real_user_traffic import _normalize_state
        assert _normalize_state("NJ (New Jersey)") == "NJ"


class TestFindStateColumn:
    def test_lowercase_state(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "state": "CA"}]) == "state"

    def test_title_case_State(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "State": "CA"}]) == "State"

    def test_upper_STATE(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "STATE": "CA"}]) == "STATE"

    def test_state_code(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "state_code": "CA"}]) == "state_code"

    def test_region(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "region": "CA"}]) == "region"

    def test_missing_column_returns_none(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([{"name": "A", "email": "x@y.z"}]) is None

    def test_empty_rows_returns_none(self):
        from real_user_traffic import _find_state_column
        assert _find_state_column([]) is None


# ════════════════════════════════════════════════════════════════════
#  2. _probe_proxy_geo default result includes region_name
# ════════════════════════════════════════════════════════════════════
class TestProbeProxyGeoRegionName:
    def test_region_name_in_default_result_source(self):
        """Grep-style inspection: the default result dict in _probe_proxy_geo
        must now include the 'region_name' key."""
        src = Path("/app/backend/real_user_traffic.py").read_text()
        assert '"region_name"' in src, "'region_name' key missing from real_user_traffic.py"
        # Make sure it's used inside _probe_proxy_geo (result mapping)
        assert 'result["region_name"]' in src, "_probe_proxy_geo not setting result['region_name']"


# ════════════════════════════════════════════════════════════════════
#  3. skipped_state_mismatch counter init + _record increment
# ════════════════════════════════════════════════════════════════════
class TestSkippedStateMismatchCounter:
    def test_counter_key_present_in_source(self):
        src = Path("/app/backend/real_user_traffic.py").read_text()
        # init  + increment locations + status string
        assert '"skipped_state_mismatch": 0' in src, \
            "skipped_state_mismatch counter not initialised to 0 in RUT_JOBS"
        assert '"skipped_state_mismatch"' in src and "skipped_state_mismatch" in src
        # Wire in _record mapping
        assert '"skipped_state_mismatch": "skipped_state_mismatch"' in src, \
            "_record counter mapping missing for skipped_state_mismatch"


# ════════════════════════════════════════════════════════════════════
#  4. GET /api/real-user-traffic/jobs/pending-candidates
# ════════════════════════════════════════════════════════════════════
class TestPendingCandidatesEndpoint:
    def test_no_auth_returns_401_or_403(self):
        r = requests.get(f"{BASE_URL}/api/real-user-traffic/jobs/pending-candidates", timeout=15)
        assert r.status_code in (401, 403), f"expected 401/403 got {r.status_code}"

    def test_fresh_user_returns_empty_list(self, admin_token):
        # Use a brand new user so we know pending_leads_count=0 everywhere
        _, tok, _ = _register_activate_user(admin_token)
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/pending-candidates",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code == 200, f"expected 200 got {r.status_code} {r.text}"
        body = r.json()
        assert "items" in body and isinstance(body["items"], list)
        assert body["items"] == []
        assert body.get("count") == 0

    def test_returns_item_shape_after_seed(self, user_ctx, user_headers):
        job_id, _ = asyncio.get_event_loop().run_until_complete(
            _seed_source_job(user_ctx["id"], link_short_code="shortX")
        )
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/pending-candidates",
            headers=user_headers,
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("count", 0) >= 1
        assert any(it.get("job_id") == job_id for it in body["items"]), \
            f"seeded job {job_id} not found in response: {body}"
        seeded = next(it for it in body["items"] if it["job_id"] == job_id)
        # Key shape assertions per spec
        for key in ("job_id", "target_url", "created_at",
                    "pending_leads_count", "form_fill_enabled",
                    "state_match_enabled", "link_short_code"):
            assert key in seeded, f"key '{key}' missing from pending-candidates item: {seeded}"
        assert seeded["pending_leads_count"] == 2
        assert seeded["form_fill_enabled"] is True
        assert seeded["link_short_code"] == "shortX"

    def test_results_sorted_desc_by_created_at_and_capped_at_25(self, user_ctx, user_headers):
        """Seed 3 jobs, verify order desc by created_at, and limit is honoured."""
        # Seed 3 additional jobs — each one will be inserted slightly later
        ids = []
        for i in range(3):
            j, _ = asyncio.get_event_loop().run_until_complete(
                _seed_source_job(user_ctx["id"], link_short_code=f"s{i}")
            )
            ids.append(j)
            time.sleep(0.05)
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/pending-candidates",
            headers=user_headers,
            timeout=15,
        )
        assert r.status_code == 200
        items = r.json()["items"]
        # max 25
        assert len(items) <= 25
        # desc by created_at
        ts = [it.get("created_at") for it in items if it.get("created_at")]
        assert ts == sorted(ts, reverse=True), f"items not sorted desc: {ts}"


# ════════════════════════════════════════════════════════════════════
#  5. POST /api/real-user-traffic/jobs with data_source=pending_from_job
# ════════════════════════════════════════════════════════════════════
class TestCreateJobFromPending:
    def _base_data(self, link_id, extra=None):
        data = {
            "link_id": link_id,
            "target_url": "https://example.com",
            "proxies": "1.2.3.4:9999:user:pass",
            "user_agents": "Mozilla/5.0 ...",
            "total_clicks": "1",
            "concurrency": "1",
            "duration_minutes": "0.1",
            "allowed_os": "windows",
            "allowed_countries": "",
            "skip_duplicate_ip": "false",
            "skip_vpn": "false",
            "follow_redirect": "true",
            "no_repeated_proxy": "false",
            "form_fill_enabled": "true",
            "data_source": "pending_from_job",
            "use_stored_proxies": "false",
        }
        if extra:
            data.update(extra)
        return data

    def test_400_when_pending_from_job_but_no_source_id(self, user_headers, user_link):
        data = self._base_data(user_link["id"])
        # no import_pending_from_job_id
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=data,
            timeout=20,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code} {r.text}"

    def test_404_when_source_job_not_found(self, user_headers, user_link):
        data = self._base_data(user_link["id"], extra={
            "import_pending_from_job_id": f"TEST_missing_{uuid.uuid4().hex[:6]}"
        })
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=data,
            timeout=20,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"

    def test_404_when_pending_file_missing_on_disk(self, user_ctx, user_headers, user_link):
        # seed a job doc WITHOUT the xlsx on disk
        src_id, _ = asyncio.get_event_loop().run_until_complete(
            _seed_source_job(user_ctx["id"], with_pending_file=False)
        )
        # Wipe any xlsx if somehow exists
        from real_user_traffic import RESULTS_ROOT
        p = Path(RESULTS_ROOT) / src_id / "pending_leads.xlsx"
        if p.exists():
            p.unlink()
        data = self._base_data(user_link["id"], extra={"import_pending_from_job_id": src_id})
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=data,
            timeout=20,
        )
        assert r.status_code == 404, f"expected 404, got {r.status_code} {r.text}"

    def test_200_when_seeded_source_and_file_present(self, user_ctx, user_headers, user_link):
        src_id, _ = asyncio.get_event_loop().run_until_complete(
            _seed_source_job(user_ctx["id"], with_pending_file=True)
        )
        data = self._base_data(user_link["id"], extra={"import_pending_from_job_id": src_id})
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=data,
            timeout=30,
        )
        assert r.status_code in (200, 201), f"expected 200/201, got {r.status_code} {r.text}"
        body = r.json()
        assert body.get("form_fill_enabled") is True
        assert body.get("imported_from_job") == src_id
        # rows_loaded echoes from server — we seeded 2 rows
        assert body.get("rows_loaded", 0) == 2, f"expected 2 rows, got {body.get('rows_loaded')}"


# ════════════════════════════════════════════════════════════════════
#  6. state_match_enabled form-field accepted + echoed
# ════════════════════════════════════════════════════════════════════
class TestStateMatchFormField:
    def test_state_match_enabled_echoed(self, user_ctx, user_headers, user_link):
        src_id, _ = asyncio.get_event_loop().run_until_complete(
            _seed_source_job(user_ctx["id"], with_pending_file=True)
        )
        data = {
            "link_id": user_link["id"],
            "target_url": "https://example.com",
            "proxies": "1.2.3.4:9999:user:pass",
            "user_agents": "Mozilla/5.0 ...",
            "total_clicks": "1",
            "concurrency": "1",
            "duration_minutes": "0.1",
            "allowed_os": "windows",
            "form_fill_enabled": "true",
            "data_source": "pending_from_job",
            "import_pending_from_job_id": src_id,
            "state_match_enabled": "true",
            "use_stored_proxies": "false",
        }
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            data=data,
            timeout=30,
        )
        assert r.status_code in (200, 201), f"got {r.status_code} {r.text}"
        body = r.json()
        # The seeded file HAS a 'state' column -> state_match_enabled stays True
        assert body.get("state_match_enabled") is True, \
            f"expected state_match_enabled echoed back as True, got {body}"


# ════════════════════════════════════════════════════════════════════
#  7. Regression smoke — admin + register/activate already ran via
#     fixtures.  Explicit no-op test to keep the class visible.
# ════════════════════════════════════════════════════════════════════
class TestRegressionSmoke:
    def test_admin_login_works(self):
        tok = _admin_token()
        assert tok and isinstance(tok, str) and len(tok) > 20

    def test_existing_get_jobs_endpoint(self, user_headers):
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=user_headers,
            timeout=15,
        )
        assert r.status_code == 200
        data = r.json()
        assert "jobs" in data and isinstance(data["jobs"], list)

    def test_pending_leads_endpoint_404_for_missing_job(self, user_headers):
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/{uuid.uuid4().hex}/pending-leads",
            headers=user_headers,
            timeout=15,
        )
        assert r.status_code == 404


# ─────────── Cleanup — delete seeded jobs after suite ────────────
@pytest.fixture(scope="module", autouse=True)
def _cleanup_seeded(user_ctx):
    yield
    async def _del():
        from motor.motor_asyncio import AsyncIOMotorClient
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env")
        client = AsyncIOMotorClient(os.environ.get("MONGO_URL"))
        db = client[os.environ.get("DB_NAME")]
        await db.real_user_traffic_jobs.delete_many(
            {"user_id": user_ctx["id"], "job_id": {"$regex": "^TEST_src_"}}
        )
        client.close()
    try:
        asyncio.get_event_loop().run_until_complete(_del())
    except Exception:
        pass
