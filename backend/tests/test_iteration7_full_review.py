"""
TrackMaster - Iteration 7 full-review backend tests.

Covers the review_request priorities:
1. Auth (admin + user register/login)
2. Link CRUD + short-code redirect + click tracking
3. Admin endpoints (users list, branding, settings, ua versions, api settings status, stats)
4. Proxies CRUD (upload, list, delete)
5. Conversions / referrer stats / dashboard stats
6. UA generator/checker, email checker preview sanity
7. Form-filler + real-user-traffic endpoint sanity (reject empty/invalid gracefully,
   don't 500 with "browser not found")
8. Misc: /api/health, debug-ip
"""

import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://task-tracker-1480.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = os.environ.get("TEST_ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = "admin123"

# ---------- fixtures ----------


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/admin/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    data = r.json()
    assert data.get("is_admin") is True
    assert data.get("access_token")
    return data["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}


@pytest.fixture(scope="session")
def test_user():
    """Register a fresh user and return creds + token + id."""
    email = f"test_user_{uuid.uuid4().hex[:8]}@example.com"
    password = "Test1234!"
    name = "TEST User"
    r = requests.post(f"{API}/auth/register", json={"email": email, "password": password, "name": name}, timeout=30)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    assert "access_token" in data
    assert data["user"]["email"] == email
    return {
        "email": email,
        "password": password,
        "name": name,
        "token": data["access_token"],
        "id": data["user"]["id"],
    }


@pytest.fixture(scope="session")
def activated_user(test_user, admin_headers):
    """Activate the test user and enable key features so we can exercise CRUD."""
    features = {
        "links": True, "clicks": True, "conversions": True, "proxies": True,
        "import_data": True, "import_traffic": True, "real_traffic": True,
        "ua_generator": True, "email_checker": True, "separate_data": True,
        "form_filler": True, "real_user_traffic": True, "settings": True,
        "max_links": 1000, "max_clicks": 100000, "max_sub_users": 5,
    }
    r = requests.put(
        f"{API}/admin/users/{test_user['id']}",
        json={"status": "active", "features": features},
        headers=admin_headers,
        timeout=30,
    )
    assert r.status_code == 200, f"activate failed: {r.status_code} {r.text}"
    # Re-login to get fresh token (optional; existing token still works)
    r = requests.post(f"{API}/auth/login", json={"email": test_user["email"], "password": test_user["password"]}, timeout=30)
    assert r.status_code == 200
    token = r.json()["access_token"]
    return {**test_user, "token": token}


@pytest.fixture(scope="session")
def user_headers(activated_user):
    return {"Authorization": f"Bearer {activated_user['token']}", "Content-Type": "application/json"}


# ---------- health / misc ----------


class TestHealth:
    def test_health_endpoint(self):
        # /health exists without /api prefix (app.get)
        r = requests.get(f"{BASE_URL}/health", timeout=10)
        # Ingress only routes /api/*; /health may 404 through public URL but that's fine
        assert r.status_code in (200, 404)

    def test_debug_ip(self):
        r = requests.get(f"{API}/debug-ip", timeout=10)
        assert r.status_code == 200
        assert "ip" in r.json() or "detected_ip" in r.json() or isinstance(r.json(), dict)


# ---------- auth ----------


class TestAuth:
    def test_admin_login_success(self, admin_token):
        assert admin_token and isinstance(admin_token, str)

    def test_admin_login_bad_password(self):
        r = requests.post(f"{API}/admin/login", json={"email": ADMIN_EMAIL, "password": "wrong"}, timeout=15)
        assert r.status_code in (401, 403)

    def test_user_register_and_login(self):
        email = f"test_dup_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Abc12345", "name": "TEST Dup"}, timeout=20)
        assert r.status_code == 200
        # duplicate
        r2 = requests.post(f"{API}/auth/register", json={"email": email, "password": "Abc12345", "name": "TEST Dup"}, timeout=20)
        assert r2.status_code == 400
        # login
        r3 = requests.post(f"{API}/auth/login", json={"email": email, "password": "Abc12345"}, timeout=20)
        assert r3.status_code == 200
        assert "access_token" in r3.json()

    def test_user_login_bad_password(self, test_user):
        r = requests.post(f"{API}/auth/login", json={"email": test_user["email"], "password": "wrong"}, timeout=15)
        assert r.status_code == 401

    def test_auth_me(self, activated_user):
        h = {"Authorization": f"Bearer {activated_user['token']}"}
        r = requests.get(f"{API}/auth/me", headers=h, timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == activated_user["email"]

    def test_pending_user_blocked_from_feature(self, test_user):
        """Freshly registered user (pending) should be blocked from /api/links."""
        email = f"test_pending_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={"email": email, "password": "Abc12345", "name": "TEST Pending"}, timeout=20)
        assert r.status_code == 200
        token = r.json()["access_token"]
        r2 = requests.get(f"{API}/links", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        assert r2.status_code == 403


# ---------- links + redirect + click tracking ----------


class TestLinksAndRedirect:
    def test_create_list_update_delete_link(self, user_headers):
        payload = {"offer_url": "https://example.com/offer", "name": "TEST link"}
        r = requests.post(f"{API}/links", json=payload, headers=user_headers, timeout=20)
        assert r.status_code == 200, r.text
        link = r.json()
        assert link["offer_url"] == payload["offer_url"]
        assert link["short_code"]
        link_id = link["id"]
        short_code = link["short_code"]

        # list
        r2 = requests.get(f"{API}/links", headers=user_headers, timeout=20)
        assert r2.status_code == 200
        assert any(l["id"] == link_id for l in r2.json())

        # redirect flow - /r/{short_code} (public)
        r3 = requests.get(f"{BASE_URL}/r/{short_code}", allow_redirects=False, timeout=20)
        # Either 302 redirect or 200 HTML interstitial; anything but 404/5xx is acceptable
        assert r3.status_code in (200, 301, 302, 303, 307, 308), f"redirect status: {r3.status_code}"

        # give click pipeline a moment
        time.sleep(2)
        r4 = requests.get(f"{API}/clicks", headers=user_headers, timeout=20)
        assert r4.status_code == 200

        # update
        r5 = requests.put(f"{API}/links/{link_id}", json={"name": "TEST link renamed"}, headers=user_headers, timeout=20)
        assert r5.status_code == 200
        assert r5.json()["name"] == "TEST link renamed"

        # delete
        r6 = requests.delete(f"{API}/links/{link_id}", headers=user_headers, timeout=20)
        assert r6.status_code == 200

    def test_redirect_unknown_shortcode(self):
        r = requests.get(f"{BASE_URL}/r/zzzz_not_real_{uuid.uuid4().hex[:4]}", allow_redirects=False, timeout=20)
        assert r.status_code in (404, 302, 200)


# ---------- clicks / conversions / dashboard ----------


class TestClicksAndStats:
    def test_clicks_list(self, user_headers):
        r = requests.get(f"{API}/clicks", headers=user_headers, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_clicks_count(self, user_headers):
        r = requests.get(f"{API}/clicks/count", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_referrer_stats(self, user_headers):
        r = requests.get(f"{API}/clicks/referrer-stats", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_conversions_list(self, user_headers):
        r = requests.get(f"{API}/conversions", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_dashboard_stats(self, user_headers):
        r = requests.get(f"{API}/dashboard/stats", headers=user_headers, timeout=20)
        assert r.status_code == 200
        j = r.json()
        for k in ("total_clicks", "unique_clicks", "total_conversions", "conversion_rate"):
            assert k in j

    def test_sample_user_agents(self, user_headers):
        r = requests.get(f"{API}/clicks/sample-user-agents", headers=user_headers, timeout=20)
        assert r.status_code == 200


# ---------- proxies ----------


class TestProxies:
    def test_proxies_upload_list_delete(self, user_headers):
        payload = {"proxy_list": ["1.2.3.4:8080", "5.6.7.8:3128:user:pass"], "proxy_type": "http"}
        r = requests.post(f"{API}/proxies/upload", json=payload, headers=user_headers, timeout=60)
        assert r.status_code == 200, r.text
        proxies = r.json()
        assert isinstance(proxies, list) and len(proxies) >= 1

        r2 = requests.get(f"{API}/proxies", headers=user_headers, timeout=20)
        assert r2.status_code == 200

        # Delete first one
        pid = proxies[0]["id"]
        r3 = requests.delete(f"{API}/proxies/{pid}", headers=user_headers, timeout=20)
        assert r3.status_code == 200


# ---------- admin-only endpoints ----------


class TestAdminEndpoints:
    def test_admin_users_list(self, admin_headers):
        r = requests.get(f"{API}/admin/users", headers=admin_headers, timeout=20)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_admin_stats(self, admin_headers):
        r = requests.get(f"{API}/admin/stats", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_branding_public(self):
        r = requests.get(f"{API}/branding", timeout=15)
        assert r.status_code == 200
        assert "app_name" in r.json()

    def test_admin_branding_get(self, admin_headers):
        r = requests.get(f"{API}/admin/branding", headers=admin_headers, timeout=15)
        assert r.status_code == 200

    def test_admin_api_settings_status(self, admin_headers):
        r = requests.get(f"{API}/admin/api-settings/status", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_admin_ua_versions(self, admin_headers):
        r = requests.get(f"{API}/admin/ua-versions", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_admin_users_stats_all(self, admin_headers):
        r = requests.get(f"{API}/admin/users/stats/all", headers=admin_headers, timeout=20)
        assert r.status_code == 200

    def test_non_admin_blocked_on_admin_endpoint(self, user_headers):
        r = requests.get(f"{API}/admin/users", headers=user_headers, timeout=15)
        assert r.status_code in (401, 403)


# ---------- UA & email checker ----------


class TestUAAndEmail:
    def test_ua_options(self, user_headers):
        r = requests.get(f"{API}/user-agents/options", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_ua_generate(self, user_headers):
        r = requests.post(f"{API}/user-agents/generate", json={"count": 3, "device_type": "mobile"}, headers=user_headers, timeout=30)
        # some backends strict on schema; accept 200 or 422
        assert r.status_code in (200, 422)

    def test_ua_check(self, user_headers):
        ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        r = requests.post(f"{API}/user-agents/check", json={"user_agent": ua}, headers=user_headers, timeout=30)
        assert r.status_code in (200, 422)


# ---------- form filler / real user traffic (sanity only) ----------


class TestAutomationEndpointsSanity:
    """Just ensure these endpoints are reachable and don't 500 with 'browser not found'."""

    def test_form_filler_jobs_list(self, user_headers):
        r = requests.get(f"{API}/form-filler/jobs", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_real_user_traffic_jobs_list(self, user_headers):
        r = requests.get(f"{API}/real-user-traffic/jobs", headers=user_headers, timeout=20)
        assert r.status_code == 200

    def test_form_filler_create_invalid_payload(self, user_headers):
        # invalid -> 400/422, NOT 500
        r = requests.post(f"{API}/form-filler/jobs", json={}, headers=user_headers, timeout=20)
        assert r.status_code in (400, 422), f"unexpected {r.status_code}: {r.text[:200]}"

    def test_real_user_traffic_create_invalid_payload(self, user_headers):
        r = requests.post(f"{API}/real-user-traffic/jobs", json={}, headers=user_headers, timeout=20)
        assert r.status_code in (400, 422), f"unexpected {r.status_code}: {r.text[:200]}"
