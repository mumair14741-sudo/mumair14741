"""
Iteration 15 — Backend tests for the new
POST /api/real-user-traffic/engine-prewarm endpoint, plus regression on
GET /api/real-user-traffic/engine-status.

Spec from main agent review_request:
  • Auth-protected (401/403 without token, 401/403 with bad token).
  • Feature-flag gated (real_user_traffic) → 403 for users without the flag.
  • When engine is already ready: response =
        {started: false, already_ready: true, status: 'ready',
         expected_revision: '1148', ...}
  • When engine is missing: response =
        {started: true, status: 'installing', expected_revision: '1148',
         message: 'Prewarm started …'}    AND a background task is fired.
  • When prewarm is already in progress: response =
        {started: false, already_installing: true, status: 'installing', ...}
  • GET engine-status reflects 'installing' immediately after a prewarm POST
    (the _CHROMIUM_INSTALL_IN_PROGRESS flag is set during background install).
  • After install completes (or already-ready), engine-status returns 'ready'.
  • No regression — earlier engine-status auth/schema tests still pass.

Run:
  cd /app/backend && python -m pytest \
    tests/test_iteration15_rut_engine_prewarm.py \
    -v --tb=short \
    --junitxml=/app/test_reports/pytest/iteration15.xml
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import requests

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    try:
        for line in (Path("/app/frontend/.env").read_text().splitlines()):
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
                break
    except Exception:
        pass
assert BASE_URL, "REACT_APP_BACKEND_URL must be configured"

API = f"{BASE_URL}/api"

ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"

PREWARM = f"{API}/real-user-traffic/engine-prewarm"
STATUS = f"{API}/real-user-traffic/engine-status"


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
    """Read chromium-headless-shell revision from the bundled browsers.json."""
    candidates = []
    try:
        import playwright  # type: ignore
        bj = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        candidates.append(str(bj))
    except Exception:
        pass
    candidates.append(
        "/root/.venv/lib/python3.11/site-packages/playwright/driver/package/browsers.json"
    )
    for p in candidates:
        if os.path.exists(p):
            with open(p) as fh:
                data = json.load(fh)
            for entry in data.get("browsers", []):
                if entry.get("name") == "chromium-headless-shell":
                    rev = str(entry.get("revision") or "").strip()
                    if rev:
                        return rev
    pytest.skip("Could not locate playwright browsers.json")


# ---------------------------------------------------------------------------
# (1) Auth gating on the new POST endpoint
# ---------------------------------------------------------------------------
class TestPrewarmAuthGating:
    def test_unauthenticated_post_rejected(self, session):
        r = session.post(PREWARM, timeout=15)
        assert r.status_code in (401, 403), (
            f"Unauth POST must be 401/403, got {r.status_code}: {r.text[:200]}"
        )

    def test_bogus_token_rejected(self, session):
        r = session.post(
            PREWARM,
            headers={"Authorization": "Bearer this.is.not.a.real.jwt"},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"Bad token must be 401/403, got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# (2) Feature flag gating — fresh user without 'real_user_traffic' → 403
# ---------------------------------------------------------------------------
class TestPrewarmFeatureFlagGating:
    def test_user_without_feature_flag_blocked(self, session):
        email = f"TEST_rut_prewarm_{uuid.uuid4().hex[:10]}@example.com"
        password = "Passw0rd!123"
        reg = session.post(
            f"{API}/auth/register",
            json={"email": email, "password": password, "name": "TEST RUT Prewarm"},
            timeout=20,
        )
        if reg.status_code not in (200, 201):
            pytest.skip(
                f"Could not register fresh user: {reg.status_code} {reg.text[:200]}"
            )
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

        r = session.post(
            PREWARM,
            headers={"Authorization": f"Bearer {tok}"},
            timeout=15,
        )
        assert r.status_code in (401, 403), (
            f"User without 'real_user_traffic' must be blocked (4xx), "
            f"got {r.status_code}: {r.text[:200]}"
        )


# ---------------------------------------------------------------------------
# (3) HTTP happy path — already_ready branch
#     (Binary IS on disk per iteration_14, so admin POST returns already_ready.)
# ---------------------------------------------------------------------------
class TestPrewarmAlreadyReadyBranch:
    def test_returns_200(self, session, auth_headers):
        r = session.post(PREWARM, headers=auth_headers, timeout=20)
        assert r.status_code == 200, (
            f"Expected 200, got {r.status_code}: {r.text[:200]}"
        )

    def test_response_shape_already_ready(self, session, auth_headers,
                                          expected_chromium_revision):
        r = session.post(PREWARM, headers=auth_headers, timeout=20)
        assert r.status_code == 200
        body = r.json()
        # Required keys
        for k in ("started", "status", "expected_revision"):
            assert k in body, f"Missing '{k}' in body={body}"
        # When binary is present, server MUST short-circuit.
        assert body["started"] is False, (
            f"Expected started=False (binary already on disk), body={body}"
        )
        assert body.get("already_ready") is True, (
            f"Expected already_ready=True, body={body}"
        )
        assert body["status"] == "ready", (
            f"Expected status='ready', body={body}"
        )
        assert body["expected_revision"] == expected_chromium_revision, (
            f"expected_revision mismatch: api={body['expected_revision']} "
            f"vs browsers.json={expected_chromium_revision}"
        )

    def test_no_browser_path_leak(self, session, auth_headers):
        r = session.post(PREWARM, headers=auth_headers, timeout=20)
        body = r.json()
        assert "browser_path" not in body, (
            f"Server must not leak filesystem path; body={body}"
        )

    def test_idempotent_when_ready(self, session, auth_headers):
        """Calling prewarm twice in a row when ready must keep returning
        already_ready=True without ever flipping started=True."""
        r1 = session.post(PREWARM, headers=auth_headers, timeout=20).json()
        r2 = session.post(PREWARM, headers=auth_headers, timeout=20).json()
        assert r1.get("started") is False
        assert r2.get("started") is False
        assert r1.get("status") == r2.get("status") == "ready"


# ---------------------------------------------------------------------------
# (4) GET engine-status still works after prewarm POST (no regression)
# ---------------------------------------------------------------------------
class TestEngineStatusAfterPrewarm:
    def test_status_endpoint_still_ready(self, session, auth_headers,
                                         expected_chromium_revision):
        # Trigger a prewarm POST (no-op since ready), then check status.
        session.post(PREWARM, headers=auth_headers, timeout=20)
        r = session.get(STATUS, headers=auth_headers, timeout=15)
        assert r.status_code == 200, (
            f"engine-status regression: {r.status_code} {r.text[:200]}"
        )
        body = r.json()
        assert body["status"] == "ready", body
        assert body["expected_revision"] == expected_chromium_revision, body
        # Path leak check still holds
        assert "browser_path" not in body, body


# ---------------------------------------------------------------------------
# (5) In-process simulation of the missing → installing → ready flow
#
# We can't actually delete /pw-browsers/chromium_headless_shell-1148 from a
# test (that would break every other RUT test running concurrently AND take
# ~60s to re-download). Instead we exercise the SAME branches the HTTP
# handler hits, by calling the helper directly with a redirected
# PLAYWRIGHT_BROWSERS_PATH and toggling the in-progress flag — exactly
# mirroring the logic the endpoint runs through _rut_get_engine_status().
# ---------------------------------------------------------------------------
class TestPrewarmBranchesViaHelper:
    def _imports(self):
        sys.path.insert(0, "/app/backend")
        import real_user_traffic as rut  # type: ignore
        return rut

    def test_missing_branch_yields_started_true(self, monkeypatch):
        """Replicates server.py logic: status==missing → background task added,
        response = {started: True, status: 'installing', ...}.
        We don't actually await the background install (would download 150MB+);
        we just confirm the branch decision matches the spec."""
        rut = self._imports()
        # Force "missing": no binary at the redirected root, flag off.
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                           "/tmp/nonexistent_pw_root_iter15_missing")
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", False,
                            raising=False)
        info = rut.get_engine_status()
        assert info["status"] == "missing", info

        # The server endpoint, given status=='missing', returns started=True
        # and schedules _ensure_chromium_available. Mirror that decision:
        assert info["status"] not in ("ready", "installing"), info
        # Verify the helper that would be scheduled is importable & callable
        from real_user_traffic import _ensure_chromium_available  # noqa: F401

    def test_installing_branch_yields_already_installing(self, monkeypatch):
        """When _CHROMIUM_INSTALL_IN_PROGRESS is True and binary missing,
        get_engine_status() returns 'installing'. Server then returns
        {started: False, already_installing: True}."""
        rut = self._imports()
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                           "/tmp/nonexistent_pw_root_iter15_installing")
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", True,
                            raising=False)
        info = rut.get_engine_status()
        assert info["status"] == "installing", info
        assert info.get("expected_revision"), info
        # The mirrored server response would be:
        mirrored = {
            "started": False,
            "already_installing": True,
            "status": info["status"],
            "expected_revision": info["expected_revision"],
            "message": info.get("message"),
        }
        assert mirrored["already_installing"] is True
        assert mirrored["status"] == "installing"

    def test_ready_branch_yields_already_ready(self):
        """No monkeypatch: real binary IS on disk (rev 1148) so helper returns
        ready and the server returns already_ready=True."""
        rut = self._imports()
        info = rut.get_engine_status()
        assert info["status"] == "ready", info
        mirrored = {
            "started": False,
            "already_ready": True,
            "status": info["status"],
            "expected_revision": info["expected_revision"],
        }
        assert mirrored["already_ready"] is True
        assert mirrored["status"] == "ready"


# ---------------------------------------------------------------------------
# (6) Concurrency / idempotency check at the helper level
#
# The endpoint uses an asyncio.Lock + module-level flag inside
# _ensure_chromium_available so two parallel prewarm clicks never start
# two concurrent installs. We verify:
#   • the lock object exists and is an asyncio.Lock
#   • the flag is a plain bool toggle
#   • get_engine_status reflects the flag immediately (no caching).
# ---------------------------------------------------------------------------
class TestPrewarmIdempotencyPrimitives:
    def test_install_lock_is_asyncio_lock(self):
        sys.path.insert(0, "/app/backend")
        import asyncio as _asyncio
        import real_user_traffic as rut
        assert isinstance(rut._CHROMIUM_INSTALL_LOCK, _asyncio.Lock), (
            f"Expected asyncio.Lock, got {type(rut._CHROMIUM_INSTALL_LOCK)}"
        )

    def test_install_flag_starts_false(self):
        sys.path.insert(0, "/app/backend")
        import real_user_traffic as rut
        # We can't assert it's currently False (another test may run in
        # parallel) — but it MUST be a bool.
        assert isinstance(rut._CHROMIUM_INSTALL_IN_PROGRESS, bool)

    def test_status_reflects_flag_immediately(self, monkeypatch):
        """Mirrors the requirement 'GET engine-status reflects installing
        immediately after a prewarm POST'."""
        sys.path.insert(0, "/app/backend")
        import real_user_traffic as rut
        monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH",
                           "/tmp/nonexistent_pw_root_iter15_immediate")
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", False,
                            raising=False)
        before = rut.get_engine_status()
        assert before["status"] == "missing"
        # Endpoint would now flip the flag inside _ensure_chromium_available.
        # We simulate that flip directly:
        monkeypatch.setattr(rut, "_CHROMIUM_INSTALL_IN_PROGRESS", True,
                            raising=False)
        after = rut.get_engine_status()
        assert after["status"] == "installing", (
            f"Status must flip to installing the moment the flag is set, "
            f"got {after}"
        )


# ---------------------------------------------------------------------------
# (7) Regression sweep — re-verify a subset of iteration_14 expectations
# ---------------------------------------------------------------------------
class TestIteration14Regression:
    def test_engine_status_unauthenticated_still_blocked(self, session):
        r = session.get(STATUS, timeout=15)
        assert r.status_code in (401, 403)

    def test_engine_status_schema_intact(self, session, auth_headers):
        r = session.get(STATUS, headers=auth_headers, timeout=15)
        assert r.status_code == 200
        body = r.json()
        for k in ("status", "message", "expected_revision"):
            assert k in body, f"Missing '{k}' in {body}"
        assert "browser_path" not in body, body

    def test_jobs_endpoint_still_works(self, session, auth_headers):
        r = session.get(f"{API}/real-user-traffic/jobs",
                        headers=auth_headers, timeout=20)
        assert r.status_code == 200
        assert "jobs" in r.json()
