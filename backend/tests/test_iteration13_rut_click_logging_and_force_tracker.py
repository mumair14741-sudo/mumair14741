"""
Iteration 13 — Backend regression tests for:

  1. DB-name mismatch bug fix: RUT click mirror must write into the SAME
     per-user DB that dashboard/Clicks read from
     (`trackmaster_user_{user_id.replace('-','_')[:20]}`).
  2. New `force_tracker_url` Form param on POST /api/real-user-traffic/jobs
     - When True → auto-swap bypass is disabled; target_url is /api/t/<sc>
     - When False (default) → legacy auto-swap swaps to offer URL on preview pods.

Run:
  cd /app/backend && python -m pytest \
    tests/test_iteration13_rut_click_logging_and_force_tracker.py \
    -v --tb=short \
    --junitxml=/app/test_reports/pytest/iteration13.xml
"""
import os
import time
import uuid
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://project-track-8.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"
ADMIN_USER_ID = "6e0e38a5-08f3-4403-90d8-5e4cf0813b1a"
EXPECTED_DB = "trackmaster_user_6e0e38a5_08f3_4403_9"  # helper: user_id.replace('-','_')[:20]
TEST_LINK_SHORT = "2735ad44"
TEST_LINK_ID = "baa47816-ccea-4b6b-98d1-c8fbfa6bd18b"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Accept": "application/json"})
    return s


@pytest.fixture(scope="module")
def admin_token(session):
    # Admin credentials are accepted by /api/admin/login (not /api/auth/login)
    r = session.post(
        f"{API}/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
        # Fallback: regular /auth/login
        r = session.post(
            f"{API}/auth/login",
            json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
            timeout=20,
        )
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:200]}"
    data = r.json()
    tok = data.get("access_token") or data.get("token")
    assert tok, f"No token in login response: {data}"
    return tok


@pytest.fixture(scope="module")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


# ---------------------------------------------------------------------------
# Sanity: admin login + user identity
# ---------------------------------------------------------------------------
class TestAuthSanity:
    def test_admin_login_succeeds(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20

    def test_me_returns_expected_admin_user_id(self, session, auth_headers):
        r = session.get(f"{API}/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        # /auth/me may return {user: {...}} or the user dict directly
        u = body.get("user") if isinstance(body, dict) and "user" in body else body
        assert u.get("id") == ADMIN_USER_ID, (
            f"Expected admin id {ADMIN_USER_ID}, got {u.get('id')}. "
            "If this fails the DB-name truncation assumption may be wrong for a re-seeded env."
        )


# ---------------------------------------------------------------------------
# Bug-fix 1 — DB-name mismatch: clicks must live in the truncated per-user DB
# ---------------------------------------------------------------------------
class TestClickStorageDbName:
    """The migrated 648 clicks should be in trackmaster_user_6e0e38a5_08f3_4403_9.
    No sibling DB with the FULL-uuid name should still hold orphaned clicks."""

    def test_expected_per_user_db_has_clicks(self):
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        user_db = client[EXPECTED_DB]
        count = user_db.clicks.count_documents({})
        assert count >= 631, (
            f"Expected ≥631 clicks in {EXPECTED_DB} (user reported 648 migrated); "
            f"got {count}."
        )

    def test_clicks_are_rut_sourced(self):
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        user_db = client[EXPECTED_DB]
        rut_count = user_db.clicks.count_documents({"source": "real_user_traffic"})
        ref_count = user_db.clicks.count_documents({"referrer_source": "rut"})
        # At least a substantial fraction of the 631 clicks should be RUT-sourced
        assert rut_count >= 500, f"source=real_user_traffic count too low: {rut_count}"
        assert ref_count >= 500, f"referrer_source=rut count too low: {ref_count}"

    def test_no_orphaned_full_uuid_db(self):
        """The pre-fix bug would write to trackmaster_user_<FULL-uuid>.
        Verify no such orphan DB still contains unmigrated clicks."""
        from pymongo import MongoClient
        client = MongoClient(os.environ.get("MONGO_URL", "mongodb://localhost:27017"))
        orphan_names = [
            n for n in client.list_database_names()
            if n.startswith("trackmaster_user_6e0e38a5") and n != EXPECTED_DB
        ]
        # Orphan DBs can exist empty; they just must not hold clicks anymore.
        for name in orphan_names:
            count = client[name].clicks.count_documents({})
            assert count == 0, f"Orphan DB {name} still has {count} un-migrated clicks"


# ---------------------------------------------------------------------------
# Bug-fix 1 — Dashboard + /api/clicks must surface the migrated clicks
# ---------------------------------------------------------------------------
class TestDashboardAndClicksApi:
    def test_dashboard_stats_shows_migrated_clicks(self, session, auth_headers):
        r = session.get(f"{API}/dashboard/stats", headers=auth_headers, timeout=20)
        assert r.status_code == 200, r.text[:200]
        body = r.json()
        total = body.get("total_clicks")
        assert isinstance(total, int), f"total_clicks not int: {body}"
        assert total >= 631, (
            f"Dashboard total_clicks={total}, expected ≥631. "
            "Bug-fix not visible — clicks still missing from user DB or dashboard query."
        )

    def test_clicks_endpoint_returns_rut_sourced_rows(self, session, auth_headers):
        r = session.get(
            f"{API}/clicks",
            headers=auth_headers,
            params={"limit": 50},
            timeout=30,
        )
        assert r.status_code == 200, r.text[:200]
        rows = r.json()
        assert isinstance(rows, list), f"Clicks response not a list: {type(rows)}"
        assert len(rows) > 0, "No clicks returned — dashboard sees them but /api/clicks doesn't"
        # At least one RUT-sourced row among the recent 50
        rut_rows = [
            r for r in rows
            if r.get("source") == "real_user_traffic" or r.get("referrer_source") == "rut"
        ]
        assert len(rut_rows) > 0, (
            f"No RUT-sourced clicks in latest 50 — visibility of the migrated clicks failed. "
            f"Sample row keys: {list(rows[0].keys()) if rows else 'none'}"
        )

    def test_clicks_response_excludes_mongo_id(self, session, auth_headers):
        r = session.get(
            f"{API}/clicks",
            headers=auth_headers,
            params={"limit": 5},
            timeout=15,
        )
        assert r.status_code == 200
        rows = r.json()
        if rows:
            assert "_id" not in rows[0], "Mongo _id leaked into /api/clicks response"


# ---------------------------------------------------------------------------
# New feature — force_tracker_url Form param on POST /api/real-user-traffic/jobs
# ---------------------------------------------------------------------------
class TestForceTrackerUrlFlag:
    """Validate the NEW force_tracker_url wiring.
    We do NOT rely on a proxy actually working — we just care that the server
    parses the flag and picks the right `target_url` before starting the job."""

    DUMMY_PROXIES = "127.0.0.1:8080:test:test\n127.0.0.1:8081:test:test"
    DUMMY_UA = "Mozilla/5.0 (X11; Linux x86_64) TestAgent/1.0"

    def _post_job(self, session, headers, *, force: bool):
        form = {
            "link_id": TEST_LINK_ID,
            "proxies": self.DUMMY_PROXIES,
            "user_agents": self.DUMMY_UA,
            "use_stored_proxies": "false",
            "total_clicks": "1",
            "concurrency": "1",
            "duration_minutes": "0",
            "skip_duplicate_ip": "true",
            "skip_vpn": "true",
            "follow_redirect": "false",
            "no_repeated_proxy": "false",
            "form_fill_enabled": "false",
            "skip_captcha": "true",
            "post_submit_wait": "3",
            "self_heal": "false",
            "force_tracker_url": "true" if force else "false",
        }
        return session.post(
            f"{API}/real-user-traffic/jobs",
            headers=headers,
            data=form,
            timeout=60,
        )

    def _stop_job(self, session, headers, job_id):
        try:
            session.post(f"{API}/real-user-traffic/jobs/{job_id}/stop",
                         headers=headers, timeout=15)
        except Exception:
            pass

    def test_force_tracker_true_returns_tracker_url(self, session, auth_headers):
        r = self._post_job(session, auth_headers, force=True)
        assert r.status_code == 200, f"Create job failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        tu = body.get("target_url", "")
        assert "/api/t/" in tu, (
            f"Expected target_url to contain '/api/t/' when force_tracker_url=true, "
            f"got: {tu!r}"
        )
        assert TEST_LINK_SHORT in tu, f"target_url missing short_code: {tu}"
        # On a preview pod, the host should be the preview-pod host (not the offer host)
        assert "apptrk.addtitans.in" not in tu, (
            f"Auto-swap was NOT suppressed — got offer host instead of tracker: {tu}"
        )
        # Best-effort: stop the freshly-created job so it doesn't hold resources
        self._stop_job(session, auth_headers, body.get("job_id"))

    def test_force_tracker_false_auto_swaps_to_offer_on_preview(self, session, auth_headers):
        r = self._post_job(session, auth_headers, force=False)
        assert r.status_code == 200, f"Create job failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        tu = body.get("target_url", "")
        # Preview pods auto-swap to offer_url so the browser actually reaches
        # the real advertiser. offer_url for this link is on apptrk.addtitans.in.
        assert "apptrk.addtitans.in" in tu, (
            f"Expected auto-swap to offer URL on preview pod when "
            f"force_tracker_url=false; got target_url={tu!r}"
        )
        assert "/api/t/" not in tu, (
            f"target_url should NOT contain /api/t/ under legacy auto-swap; got {tu!r}"
        )
        self._stop_job(session, auth_headers, body.get("job_id"))


# ---------------------------------------------------------------------------
# End-to-end sanity — tiny RUT job increments dashboard clicks
# ---------------------------------------------------------------------------
class TestClickLoggingIncrement:
    """Run a minimal RUT job and verify dashboard total_clicks is monotonically
    non-decreasing. We CANNOT guarantee +1 because a dummy proxy may fail
    before reaching the log_click hook; the point of this test is to confirm
    (a) the job API accepts the call, (b) the dashboard query still works
    post-job, and (c) counts don't regress. The hard assertion (≥631) is
    already covered by TestDashboardAndClicksApi."""

    def test_dashboard_counts_are_stable_and_nondecreasing(self, session, auth_headers):
        r = session.get(f"{API}/dashboard/stats", headers=auth_headers, timeout=20)
        assert r.status_code == 200
        before = r.json().get("total_clicks", 0)

        form = {
            "link_id": TEST_LINK_ID,
            "proxies": "127.0.0.1:9999:dummy:dummy",
            "user_agents": "Mozilla/5.0 Test",
            "total_clicks": "1",
            "concurrency": "1",
            "duration_minutes": "0",
            "skip_duplicate_ip": "false",
            "skip_vpn": "false",
            "form_fill_enabled": "false",
            "force_tracker_url": "false",
        }
        r2 = session.post(f"{API}/real-user-traffic/jobs",
                          headers=auth_headers, data=form, timeout=60)
        assert r2.status_code == 200, r2.text[:300]
        job_id = r2.json().get("job_id")
        # Give the engine a short window to produce at least one entry
        time.sleep(6)
        # Stop the job regardless
        try:
            session.post(f"{API}/real-user-traffic/jobs/{job_id}/stop",
                         headers=auth_headers, timeout=15)
        except Exception:
            pass

        r3 = session.get(f"{API}/dashboard/stats", headers=auth_headers, timeout=20)
        assert r3.status_code == 200
        after = r3.json().get("total_clicks", 0)
        assert after >= before, (
            f"Dashboard clicks went DOWN after RUT job (before={before} after={after}). "
            "Indicates a click-delete regression or DB routing bug."
        )
