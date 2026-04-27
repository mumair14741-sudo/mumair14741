"""Iteration 10 backend tests

Covers:
1. _is_thank_you_page helper (synthetic URL + text cases; Playwright content test)
2. Target-mode validation on POST /api/real-user-traffic/jobs
3. RUT_JOBS initialisation (conversions, target_mode, target_conversions, max_attempts, target_reached)
4. Backward-compat: target_mode='clicks' behaves like legacy fixed-count flow
5. Response of POST includes new fields + all regression fields
6. Cancel_event path in dispatcher (code-inspection)
"""

import os
import io
import sys
import time
import uuid
import asyncio
import pytest
import requests

# Make backend/ importable so we can import helper
sys.path.insert(0, "/app/backend")
from real_user_traffic import (  # noqa: E402
    _is_thank_you_page,
    _did_reach_conversion,
    _THANKYOU_URL_KEYWORDS,
    _THANKYOU_TEXT_KEYWORDS,
    _FORM_PAGE_TEXT_NEGATIVES,
    RUT_JOBS,
    run_real_user_traffic_job,
)

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://task-tracker-1480.preview.emergentagent.com").rstrip("/")
ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=15)
    if r.status_code != 200:
        pytest.skip(f"admin login failed: {r.status_code} {r.text[:200]}")
    return r.json().get("access_token")


@pytest.fixture(scope="session")
def test_user(admin_token):
    """Register a fresh user + admin-activate real_user_traffic + links features."""
    email = f"TEST_rut10_{uuid.uuid4().hex[:8]}@example.com"
    password = "Passw0rd!"
    r = requests.post(f"{BASE_URL}/api/auth/register",
                      json={"email": email, "password": password, "name": "RUT10"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    # admin activate + grant features
    r = requests.get(f"{BASE_URL}/api/admin/users",
                     headers={"Authorization": f"Bearer {admin_token}"}, timeout=15)
    assert r.status_code == 200
    uid = None
    for u in r.json():
        if u.get("email") == email:
            uid = u.get("id") or u.get("_id")
            break
    assert uid, "new user not found in admin list"
    put = requests.put(f"{BASE_URL}/api/admin/users/{uid}",
                       headers={"Authorization": f"Bearer {admin_token}"},
                       json={"status": "active",
                             "features": {"real_user_traffic": True, "links": True}}, timeout=15)
    assert put.status_code == 200, put.text
    # login
    lg = requests.post(f"{BASE_URL}/api/auth/login",
                       json={"email": email, "password": password}, timeout=15)
    assert lg.status_code == 200
    return {"email": email, "token": lg.json()["access_token"], "uid": uid}


@pytest.fixture(scope="session")
def user_link(test_user):
    """Create a link we can reference in POST /real-user-traffic/jobs."""
    token = test_user["token"]
    r = requests.post(f"{BASE_URL}/api/links",
                      headers={"Authorization": f"Bearer {token}"},
                      json={"offer_url": "https://example.com",
                            "title": "rut10-test", "category": "test"}, timeout=15)
    assert r.status_code in (200, 201), r.text
    return r.json()


# ------------------------------------------------------------------
# 1. _is_thank_you_page helper — synthetic URL + text combinations
# ------------------------------------------------------------------
class TestIsThankYouPage:
    def test_same_host_form_text_false(self):
        # (a) same-host form page with 'Please fill' text → False
        assert _is_thank_you_page(
            "https://form-site.com/index.php",
            "https://form-site.com/index.php",
            page_text="Please fill out the form below",
            page_title="Enter details",
        ) is False

    def test_different_host_thankyou_text_true(self):
        # (b) different-host + 'Thank You' → host_changed + text_keyword = 2 signals → True
        assert _is_thank_you_page(
            "https://form-site.com/index.php",
            "https://offer-partner.com/landing",
            page_text="Thank You for signing up",
            page_title="Welcome",
        ) is True

    def test_same_host_only_text_false(self):
        # (c) same-host + 'Congratulations' only (1 signal) → False
        assert _is_thank_you_page(
            "https://form-site.com/index.php",
            "https://form-site.com/index.php",
            page_text="Congratulations",
            page_title="",
        ) is False

    def test_all_three_signals_true(self):
        # (d) different host + '/thankyou.php' in URL + 'Your Prize' → True
        assert _is_thank_you_page(
            "https://form-site.com/index.php",
            "https://offers.com/thankyou.php",
            page_text="Your Prize awaits",
            page_title="",
        ) is True

    def test_same_host_url_keyword_plus_text_true(self):
        # (e) same host, URL has '/offers-flow' + text 'Claim Your $750' → 2 signals → True
        assert _is_thank_you_page(
            "https://site.com/index.php",
            "https://site.com/offers-flow?x=1",
            page_text="Claim Your $750 Now",
            page_title="",
        ) is True

    def test_empty_page_false(self):
        # (f) empty page → False
        assert _is_thank_you_page("https://form.com/", "", page_text="", page_title="") is False
        assert _is_thank_you_page("", "", page_text="", page_title="") is False

    def test_stimulus_thnkspg_flow_true(self):
        # (g) stimulus flow — thnkspg.com with 'Claim Your $750 ... Ways to Earn' → True
        assert _is_thank_you_page(
            "https://form-site.com/landing.php",
            "https://thnkspg.com/?apikey=xx",
            page_text="Stimulus Assistant Claim Your $750 Prize Ways to Earn & Save",
            page_title="Claim",
        ) is True

    def test_form_negative_overrides_two_signals(self):
        # host change + url keyword but page screams 'please fill' → still form page → False
        # (need all 3 signals when negatives present)
        result = _is_thank_you_page(
            "https://form-site.com/index.php",
            "https://other.com/thank-you",
            page_text="Please fill out the form below to continue",
            page_title="",
        )
        # 2 positive signals (host+url) but negative hit, so needs 3 → False
        assert result is False


class TestLegacyHelperKept:
    def test_did_reach_conversion_still_exists(self):
        assert callable(_did_reach_conversion)
        # basic host-change sanity
        assert _did_reach_conversion("https://a.com/p", "https://b.com/q") is True
        assert _did_reach_conversion("https://a.com/p", "https://a.com/p") is False


# ------------------------------------------------------------------
# 2. Helper: signature kwargs exist for run_real_user_traffic_job
# ------------------------------------------------------------------
class TestRunJobSignature:
    def test_run_job_has_new_kwargs(self):
        import inspect
        sig = inspect.signature(run_real_user_traffic_job)
        params = sig.parameters
        for k in ("target_mode", "target_conversions", "max_attempts"):
            assert k in params, f"missing kwarg {k} in run_real_user_traffic_job"
        assert params["target_mode"].default == "clicks"
        assert params["target_conversions"].default == 0
        assert params["max_attempts"].default == 0


# ------------------------------------------------------------------
# 3 + 5. POST /real-user-traffic/jobs — validation + response shape
# ------------------------------------------------------------------
class TestRutCreateJobValidation:
    def _post(self, token, data, files=None):
        return requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers={"Authorization": f"Bearer {token}"},
            data=data,
            files=files,
            timeout=20,
        )

    def test_invalid_target_mode_400(self, test_user, user_link):
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
            "target_mode": "bogus",
        })
        assert r.status_code == 400
        assert "target_mode" in r.text.lower()

    def test_conversions_mode_without_target_conversions_400(self, test_user, user_link):
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
            "target_mode": "conversions",
            # target_conversions defaults 0 → invalid for this mode
        })
        assert r.status_code == 400
        assert "target_conversions" in r.text.lower()

    def test_max_attempts_less_than_target_conversions_400(self, test_user, user_link):
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
            "target_mode": "conversions",
            "target_conversions": 10,
            "max_attempts": 5,
        })
        assert r.status_code == 400
        assert "max_attempts" in r.text.lower()

    def test_target_conversions_out_of_range_400(self, test_user, user_link):
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
            "target_mode": "conversions",
            "target_conversions": 99999,
        })
        assert r.status_code == 400

    def test_clicks_mode_default_response_fields(self, test_user, user_link):
        # Legacy behaviour: no target_mode sent → clicks mode
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        # New fields
        assert body.get("target_mode") == "clicks"
        assert body.get("target_conversions") == 0
        assert body.get("max_attempts") == 0
        # Regression fields
        for f in ("job_id", "total", "form_fill_enabled", "state_match_enabled",
                  "imported_from_job", "rows_loaded"):
            assert f in body, f"missing regression field {f}"
        assert body["total"] == 1  # clicks mode honours total_clicks
        # Verify job persisted via API (RUT_JOBS is in-process in backend, not importable here)
        jid = body["job_id"]
        time.sleep(0.5)
        gj = requests.get(f"{BASE_URL}/api/real-user-traffic/jobs/{jid}",
                          headers={"Authorization": f"Bearer {test_user['token']}"}, timeout=10)
        assert gj.status_code == 200, gj.text
        job = gj.json()
        assert job.get("target_mode", "clicks") == "clicks"
        assert int(job.get("conversions") or 0) == 0
        # stop it
        requests.post(f"{BASE_URL}/api/real-user-traffic/jobs/{jid}/stop",
                      headers={"Authorization": f"Bearer {test_user['token']}"}, timeout=10)

    def test_conversions_mode_job_fields_and_rut_jobs(self, test_user, user_link):
        r = self._post(test_user["token"], {
            "link_id": user_link["id"],
            "user_agents": "Mozilla/5.0",
            "proxies": "1.1.1.1:80",
            "total_clicks": 1,
            "concurrency": 1,
            "target_mode": "conversions",
            "target_conversions": 2,
            "max_attempts": 3,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("target_mode") == "conversions"
        assert body.get("target_conversions") == 2
        assert body.get("max_attempts") == 3
        jid = body["job_id"]
        time.sleep(0.8)
        gj = requests.get(f"{BASE_URL}/api/real-user-traffic/jobs/{jid}",
                          headers={"Authorization": f"Bearer {test_user['token']}"}, timeout=10)
        assert gj.status_code == 200, gj.text
        job = gj.json()
        assert job.get("target_mode") == "conversions"
        assert int(job.get("target_conversions") or 0) == 2
        assert int(job.get("max_attempts") or 0) == 3
        # Stop
        requests.post(f"{BASE_URL}/api/real-user-traffic/jobs/{jid}/stop",
                      headers={"Authorization": f"Bearer {test_user['token']}"}, timeout=10)


# ------------------------------------------------------------------
# 4. Dispatcher code-inspection: conversions path + cancel_event exit
# ------------------------------------------------------------------
class TestDispatcherCodeInspection:
    def test_conversions_dispatcher_present(self):
        src = open("/app/backend/real_user_traffic.py").read()
        # dispatcher must branch on target_mode == 'conversions'
        assert 'target_mode == "conversions"' in src
        assert "attempt_counter" in src
        assert "max_att" in src
        # cancel_event flipping on target reach
        assert "cancel_event.set()" in src
        assert 'RUT_JOBS[job_id]["target_reached"] = True' in src

    def test_cancel_event_in_worker_loop(self):
        src = open("/app/backend/real_user_traffic.py").read()
        # The worker wait loop checks cancel_event
        assert "if cancel_event.is_set():" in src

    def test_rut_jobs_init_fields(self):
        src = open("/app/backend/real_user_traffic.py").read()
        # Ensure all five new fields are initialised
        for f in ("target_mode", "target_conversions", "max_attempts",
                  "target_reached", "\"conversions\":"):
            assert f in src, f"RUT_JOBS missing init for {f}"
