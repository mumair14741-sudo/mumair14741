"""
Iteration 14 — Backend tests for the new
GET /api/real-user-traffic/engine-status endpoint and the underlying
get_engine_status() helper in real_user_traffic.py.

Scope (per main agent review_request):
  (a) Endpoint returns 200 with body schema {status, message, expected_revision}
      when authenticated.
  (b) status == 'ready' currently because chromium-headless-shell rev 1148 is
      already on disk.
  (c) Auth-protected: unauthenticated request → 401/403.
  (d) Feature flag (real_user_traffic) gating — verified by code inspection
      and via a regular user that lacks the flag.
  (e) expected_revision matches the value declared in playwright's bundled
      browsers.json for chromium-headless-shell.
  (f) No regression of existing RUT endpoints from iteration_13:
        GET  /api/real-user-traffic/jobs
        POST /api/real-user-traffic/jobs (validation path)

Run:
  cd /app/backend && python -m pytest \
    tests/test_iteration14_rut_engine_status.py \
    -v --tb=short \
    --junitxml=/app/test_reports/pytest/iteration14.xml
"""
import json
import os
import sys
import uuid
from pathlib import Path

import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # Fall back to /app/frontend/.env if env not loaded
    try:
        for line in (Path("/app/frontend/.env").read_text().splitlines()):
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL must be configured"

API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = os.environ.get("TEST_ADMIN_PASSWORD", "admin123")


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
    """Admin auth via /api/admin/login (per iteration_13 finding)."""
    r = session.post(
        f"{API}/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=20,
    )
    if r.status_code != 200:
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


@pytest.fixture(scope="module")
def expected_chromium_revision():
    """Read the chromium-headless-shell revision Playwright expects from its
    bundled browsers.json. Used to assert the API echoes the SAME revision."""
    candidates = [
        "/root/.venv/lib/python3.11/site-packages/playwright/driver/package/browsers.json",
    ]
    # Also locate via `import playwright` to be robust to venv path changes
    try:
        import playwright  # type: ignore
        bj = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        candidates.insert(0, str(bj))
    except Exception:
        pass

    for p in candidates:
        if os.path.exists(p):
            with open(p) as fh:
                data = json.load(fh)
            for entry in data.get("browsers", []):
                if entry.get("name") == "chromium-headless-shell":
                    rev = str(entry.get("revision") or "").strip()
                    if rev:
                        return rev
    pytest.skip("Could not locate playwright browsers.json to read expected revision")


# ---------------------------------------------------------------------------
# Auth sanity
# ---------------------------------------------------------------------------
class TestAuthSanity:
    def test_admin_login_returns_token(self, admin_token):
        assert isinstance(admin_token, str) and len(admin_token) > 20


# ---------------------------------------------------------------------------
# (a) + (b) + (e) — happy path: GET engine-status returns ready w/ rev
# ---------------------------------------------------------------------------
class TestEngineStatusEndpoint:
    """GET /api/real-user-traffic/engine-status — happy path."""

    def test_endpoint_returns_200(self, session, auth_headers):
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text[:200]}"

    def test_response_schema_has_required_keys(self, session, auth_headers):
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200
        body = r.json()
        # Required fields per spec
        assert "status" in body, f"Missing 'status' in body: {body}"
        assert "message" in body, f"Missing 'message' in body: {body}"
        assert "expected_revision" in body, f"Missing 'expected_revision' in body: {body}"

    def test_response_does_not_leak_browser_path(self, session, auth_headers):
        """server.py strips browser_path to avoid leaking /pw-browsers/... to clients."""
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert "browser_path" not in body, (
            "Server should NOT leak filesystem path 'browser_path' to clients; "
            f"got body={body}"
        )

    def test_status_is_ready_currently(self, session, auth_headers):
        """Per main agent: rev 1148 is on disk so status MUST be 'ready'."""
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ready", (
            f"Expected status='ready' (binary present on disk), "
            f"got status='{body.get('status')}', body={body}"
        )

    def test_status_is_one_of_known_values(self, session, auth_headers):
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        body = r.json()
        assert body.get("status") in ("ready", "installing", "missing", "error"), (
            f"Unknown status value: {body.get('status')}"
        )

    def test_expected_revision_matches_browsers_json(
        self, session, auth_headers, expected_chromium_revision
    ):
        """API.expected_revision MUST equal browsers.json chromium-headless-shell.revision."""
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        body = r.json()
        assert body.get("expected_revision") == expected_chromium_revision, (
            f"expected_revision mismatch: API='{body.get('expected_revision')}' "
            f"vs browsers.json='{expected_chromium_revision}'"
        )

    def test_message_mentions_revision(self, session, auth_headers,
                                       expected_chromium_revision):
        r = session.get(f"{API}/real-user-traffic/engine-status",
                        headers=auth_headers, timeout=20)
        body = r.json()
        msg = (body.get("message") or "")
        assert expected_chromium_revision in msg, (
            f"message='{msg}' should mention revision={expected_chromium_revision}"
        )

    def test_binary_actually_exists_on_disk(self, expected_chromium_revision):
        """Cross-check: the chromium-headless-shell binary for the declared
        revision really is present (this is why the API reports 'ready')."""
        browsers_root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/pw-browsers")
        bin_path = Path(browsers_root) / f"chromium_headless_shell-{expected_chromium_revision}" / "chrome-linux" / "headless_shell"
        assert bin_path.exists(), f"Expected binary missing on disk: {bin_path}"


# ---------------------------------------------------------------------------
# (c) Auth gating
# ---------------------------------------------------------------------------
class TestEngineStatusAuthGating:
    def test_unauthenticated_request_rejected(self, session):
        r = session.get(f"{API}/real-user-traffic/engine-status", timeout=15)
        assert r.status_code in (401, 403), (
            f"Unauth request must be 401/403, got {r.status_code}: {r.text[:200]}"
        )

    def test_bogus_token_rejected(self, session):
        r = session.get(
            f"{API}/real-user-traffic/engine-status",
            headers={"Authorization": "Bearer this.is.not.a.real.jwt"},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"Bad token must be 401/403, got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# (d) Feature flag gating (real_user_traffic)
# ---------------------------------------------------------------------------
class TestEngineStatusFeatureFlagGating:
    """A freshly registered regular user should NOT have the
    `real_user_traffic` flag enabled by default → 403 Feature not enabled."""

    def test_user_without_feature_flag_blocked(self, session):
        # Register fresh user
        email = f"TEST_rut_engine_{uuid.uuid4().hex[:10]}@example.com"
        password = "Passw0rd!123"
        reg = session.post(
            f"{API}/auth/register",
            json={"email": email, "password": password, "name": "TEST RUT Engine"},
            timeout=20,
        )
        if reg.status_code not in (200, 201):
            pytest.skip(f"Could not register fresh user: {reg.status_code} {reg.text[:200]}")

        # Login (some apps don't return token on register)
        login = session.post(
            f"{API}/auth/login",
            json={"email": email, "password": password},
            timeout=20,
        )
        assert login.status_code == 200, (
            f"Fresh-user login failed: {login.status_code} {login.text[:200]}"
        )
        tok = login.json().get("access_token") or login.json().get("token")
        assert tok, "No token for fresh user"

        r = session.get(
            f"{API}/real-user-traffic/engine-status",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        # Expect 403 (feature flag) — but a 200 could also occur if backend
        # auto-enables for all users. Require 4xx and capture for review.
        assert r.status_code in (401, 403), (
            f"User without 'real_user_traffic' flag should be blocked (4xx), "
            f"got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# Direct module-level test of get_engine_status() — exercises the
# 'installing' code path that we cannot easily simulate via HTTP.
# ---------------------------------------------------------------------------
class TestGetEngineStatusHelper:
    """Import and call backend.real_user_traffic.get_engine_status() directly,
    flipping the module-level _CHROMIUM_INSTALL_IN_PROGRESS to verify the
    'installing' branch returns the right shape."""

    def test_helper_reports_ready_when_binary_present(self):
        sys.path.insert(0, "/app/backend")
        from real_user_traffic import get_engine_status  # type: ignore
        info = get_engine_status()
        assert info["status"] == "ready", info
        assert info["expected_revision"], info
        assert info["browser_path"], info
        assert "ready" in (info.get("message") or "").lower()

    def test_helper_reports_installing_when_flag_set_and_binary_missing(self,
                                                                        monkeypatch):
        sys.path.insert(0, "/app/backend")
        import real_user_traffic as rut  # type: ignore

        # Point browsers root at a tmp dir so the binary lookup misses, then
        # set the in-progress flag and assert 'installing' is reported.
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/tmp/nonexistent_pw_root_for_test")
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", True, raising=False)
        info = rut.get_engine_status()
        assert info["status"] == "installing", info
        assert info["expected_revision"], info
        assert "downloading" in (info.get("message") or "").lower() or \
               "install" in (info.get("message") or "").lower()

    def test_helper_reports_missing_when_no_binary_and_no_install(self,
                                                                  monkeypatch):
        sys.path.insert(0, "/app/backend")
        import real_user_traffic as rut  # type: ignore
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/tmp/nonexistent_pw_root_for_test2")
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", False, raising=False)
        info = rut.get_engine_status()
        assert info["status"] == "missing", info
        assert info["expected_revision"], info


# ---------------------------------------------------------------------------
# (f) Regression: existing RUT endpoints must still work
# ---------------------------------------------------------------------------
class TestRutRegressionExistingEndpoints:
    def test_get_jobs_still_works(self, session, auth_headers):
        r = session.get(f"{API}/real-user-traffic/jobs",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200, (
            f"Regression: GET /real-user-traffic/jobs failed: "
            f"{r.status_code} {r.text[:200]}"
        )
        body = r.json()
        assert "jobs" in body, f"Expected 'jobs' key in response: {body}"
        assert isinstance(body["jobs"], list), f"'jobs' should be list, got {type(body['jobs'])}"

    def test_get_pending_candidates_still_works(self, session, auth_headers):
        """Iteration 8+ endpoint — must not regress."""
        r = session.get(
            f"{API}/real-user-traffic/jobs/pending-candidates",
            headers=auth_headers,
            timeout=20,
        )
        # 200 expected; some iterations return {jobs: [...]} — accept any 200 JSON.
        assert r.status_code == 200, (
            f"Regression: pending-candidates failed: {r.status_code} {r.text[:200]}"
        )

    def test_post_jobs_validation_path_still_works(self, session, auth_headers):
        """POST without required fields must produce 4xx (validation), not 5xx.
        We don't actually start a real job here — just verify the route exists
        and the validation is intact (no regression to 500)."""
        r = session.post(
            f"{API}/real-user-traffic/jobs",
            headers=auth_headers,
            data={},  # intentionally empty
            timeout=20,
        )
        assert 400 <= r.status_code < 500, (
            f"POST /real-user-traffic/jobs with empty body should be 4xx, "
            f"got {r.status_code}: {r.text[:200]}"
        )
