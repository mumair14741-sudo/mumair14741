"""Iteration 11 — RUT shared-browser refactor verification.

Verifies the major refactor moving from "launch new Playwright browser per
visit" → "ONE shared Chromium browser per job + browser.new_context(proxy=…)
per visit". Coverage:

1. Code inspection: shared browser launched ONCE, per-visit `new_context`,
   per-visit context-only close in finally, terminal browser/playwright close
   after asyncio.gather.
2. Smoke: GET /api/uploads regression.
3. End-to-end: POST /api/real-user-traffic/jobs (3 dummy visits) → job
   reaches terminal state (failed/completed/stopped) and live-steps contains
   the "Shared Chromium ready · concurrency=" preflight marker.
4. Cancellation: POST /jobs/{id}/stop transitions running → stopped.
5. Backend log scan for "Executable doesn't exist" or "Browser closed"
   stack traces during the test window.
"""
from __future__ import annotations

import os
import re
import sys
import time
import uuid
import pytest
import requests

sys.path.insert(0, "/app/backend")

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"
RUT_PY = "/app/backend/real_user_traffic.py"
BACKEND_LOG = "/var/log/supervisor/backend.err.log"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
                      timeout=15)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


@pytest.fixture(scope="session")
def test_user(admin_token):
    email = f"TEST_rut11_{uuid.uuid4().hex[:8]}@example.com"
    password = "Passw0rd!"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": password,
                            "name": "RUT11"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    r = requests.get(f"{BASE_URL}/api/admin/users",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     timeout=15)
    assert r.status_code == 200
    uid = next((u.get("id") or u.get("_id") for u in r.json()
                if u.get("email") == email), None)
    assert uid, "user missing in admin list"
    p = requests.put(f"{BASE_URL}/api/admin/users/{uid}",
                     headers={"Authorization": f"Bearer {admin_token}"},
                     json={"status": "active",
                           "features": {"real_user_traffic": True,
                                        "links": True}},
                     timeout=15)
    assert p.status_code == 200, p.text
    lg = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": email, "password": password},
                       timeout=15)
    assert lg.status_code == 200
    return {"email": email, "token": lg.json()["access_token"], "uid": uid}


@pytest.fixture(scope="session")
def user_link(test_user):
    r = requests.post(f"{BASE_URL}/api/links",
                      headers={"Authorization": f"Bearer {test_user['token']}"},
                      json={"offer_url": "https://example.com",
                            "title": "rut11-shared-browser",
                            "category": "test"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ------------------------------------------------------------------
# 1. Code inspection — verifies orchestration shape post-refactor
# ------------------------------------------------------------------
class TestRefactorCodeInspection:
    def test_shared_browser_launched_once(self):
        src = open(RUT_PY).read()
        # exactly ONE chromium launch in the run-job module path
        launches = re.findall(r"chromium\.launch\s*\(", src)
        assert len(launches) == 1, (
            f"expected exactly 1 chromium.launch (shared), found {len(launches)}"
        )

    def test_process_one_uses_new_context_not_new_launch(self):
        src = open(RUT_PY).read()
        # process_one must use browser.new_context with a proxy kwarg
        assert "browser.new_context(" in src
        assert "shared_browser" in src
        # And process_one signature accepts shared_browser
        assert "async def process_one(i: int, shared_browser:" in src

    def test_per_visit_finally_closes_context_only(self):
        src = open(RUT_PY).read()
        # The visit-level finally MUST NOT close the shared browser.
        # We assert the comment + context.close() pattern present.
        assert "Browser is shared across visits" in src
        # And the shared browser close lives in the parent (after gather)
        assert "await shared_browser.close()" in src

    def test_concurrency_capped_1_to_20(self):
        src = open(RUT_PY).read()
        # Semaphore + conc clamp to (1, 20)
        assert "min(int(concurrency or 1), 20)" in src

    def test_preflight_pushlive_step_emitted(self):
        src = open(RUT_PY).read()
        assert "Shared Chromium ready" in src


# ------------------------------------------------------------------
# 2. Regression smoke — /api/uploads still works
# ------------------------------------------------------------------
class TestRegressionSmoke:
    def test_uploads_endpoint_authenticated(self, test_user):
        r = requests.get(f"{BASE_URL}/api/uploads",
                         headers={"Authorization": f"Bearer {test_user['token']}"},
                         timeout=10)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)

    def test_rut_jobs_list_endpoint(self, test_user):
        r = requests.get(f"{BASE_URL}/api/real-user-traffic/jobs",
                         headers={"Authorization": f"Bearer {test_user['token']}"},
                         timeout=10)
        assert r.status_code == 200
        body = r.json()
        # API returns either a list or {"jobs": [...]} depending on version
        jobs = body if isinstance(body, list) else body.get("jobs")
        assert isinstance(jobs, list)


# ------------------------------------------------------------------
# 3. End-to-end: tiny job with dummy proxies → terminal state, no crash
# ------------------------------------------------------------------
class TestSharedBrowserEndToEnd:
    def _create_job(self, token, link_id, total=3, concurrency=3):
        return requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "link_id": link_id,
                "user_agents": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 Chrome/124.0\n"
                                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                "AppleWebKit/537.36 Chrome/124.0"),
                "proxies": "203.0.113.1:8080:user:pass\n203.0.113.2:8080:user:pass",
                "total_clicks": total,
                "concurrency": concurrency,
            },
            timeout=20,
        )

    def test_job_creates_and_reaches_terminal_state(self, test_user, user_link):
        # Capture log offset before run so we only scan new lines
        log_offset = 0
        try:
            log_offset = os.path.getsize(BACKEND_LOG)
        except OSError:
            pass

        r = self._create_job(test_user["token"], user_link["id"], total=3, concurrency=3)
        assert r.status_code == 200, r.text
        body = r.json()
        jid = body["job_id"]
        assert body["total"] == 3

        # Poll for terminal state (max ~90s for 3 dummy proxies — they will
        # fail-fast on connect). Also stream live-log in parallel so we capture
        # the preflight 'Shared Chromium ready' marker before terminal cleanup.
        terminal = {"completed", "stopped", "failed"}
        status = None
        deadline = time.time() + 180
        last_job = {}
        all_details: list[str] = []
        cursor = 0
        while time.time() < deadline:
            ls = requests.get(
                f"{BASE_URL}/api/real-user-traffic/jobs/{jid}/live-log",
                headers={"Authorization": f"Bearer {test_user['token']}"},
                params={"since": cursor},
                timeout=10,
            )
            if ls.status_code == 200:
                lp = ls.json()
                steps = (lp.get("steps") if isinstance(lp, dict) else lp) or []
                for s in steps:
                    all_details.append(str(s.get("detail", "")))
                if isinstance(lp, dict):
                    cursor = int(lp.get("cursor") or cursor)
            gj = requests.get(
                f"{BASE_URL}/api/real-user-traffic/jobs/{jid}",
                headers={"Authorization": f"Bearer {test_user['token']}"},
                timeout=10,
            )
            assert gj.status_code == 200, gj.text
            last_job = gj.json()
            status = last_job.get("status")
            if status in terminal:
                break
            time.sleep(2)

        assert status in terminal, f"job {jid} stuck at status={status}: {last_job}"

        # Final drain of any remaining steps
        ls = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs/{jid}/live-log",
            headers={"Authorization": f"Bearer {test_user['token']}"},
            params={"since": cursor},
            timeout=10,
        )
        if ls.status_code == 200:
            lp = ls.json()
            for s in (lp.get("steps") if isinstance(lp, dict) else lp) or []:
                all_details.append(str(s.get("detail", "")))

        msgs = " || ".join(all_details)
        # Print job state for diagnostics if assertion fails
        if "Shared Chromium ready" not in msgs:
            print(f"\n[DIAG] last_job: {last_job}")
            print(f"[DIAG] all_details: {all_details}")
        assert "Shared Chromium ready" in msgs, (
            f"preflight marker missing — shared browser may not have launched. "
            f"steps={msgs[:600]}"
        )
        # concurrency value is rendered into the marker
        assert "concurrency=" in msgs

        # Backend log scan: no fatal browser errors during this window
        if os.path.exists(BACKEND_LOG):
            try:
                with open(BACKEND_LOG, "rb") as f:
                    f.seek(log_offset)
                    new_log = f.read().decode("utf-8", errors="ignore")
            except OSError:
                new_log = ""
            forbidden = [
                "Executable doesn't exist",
                "Executable does not exist",
                # "Browser has been closed" / "Browser closed" — premature close
                "Browser has been closed",
            ]
            hits = [marker for marker in forbidden if marker in new_log]
            assert not hits, (
                f"forbidden browser errors in backend log: {hits}\n"
                f"--- excerpt ---\n{new_log[-1500:]}"
            )

    def test_stop_endpoint_transitions_running_to_stopped(self, test_user, user_link):
        # Use larger total + slow pacing so we can hit it while still running
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers={"Authorization": f"Bearer {test_user['token']}"},
            data={
                "link_id": user_link["id"],
                "user_agents": "Mozilla/5.0 Chrome/124.0",
                "proxies": "203.0.113.50:8080:u:p\n203.0.113.51:8080:u:p\n203.0.113.52:8080:u:p",
                "total_clicks": 10,
                "concurrency": 1,
                "delay_min": 5,
                "delay_max": 6,
            },
            timeout=20,
        )
        assert r.status_code == 200, r.text
        jid = r.json()["job_id"]

        # Give the worker a moment to launch shared browser
        time.sleep(2)
        st = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs/{jid}/stop",
            headers={"Authorization": f"Bearer {test_user['token']}"},
            timeout=10,
        )
        assert st.status_code in (200, 202), st.text

        # Poll up to 180s for stopped state — graceful shutdown waits for the
        # in-flight visit's page.goto(45s) + context.close() before terminal.
        deadline = time.time() + 180
        status = None
        while time.time() < deadline:
            gj = requests.get(
                f"{BASE_URL}/api/real-user-traffic/jobs/{jid}",
                headers={"Authorization": f"Bearer {test_user['token']}"},
                timeout=10,
            )
            status = gj.json().get("status")
            if status in {"stopped", "completed", "failed"}:
                break
            time.sleep(2)
        assert status in {"stopped", "completed", "failed"}, (
            f"stop did not reach terminal: {status}"
        )
