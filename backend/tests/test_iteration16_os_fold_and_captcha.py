"""
Iteration 16 — Bug-fix verification:
  (a) tracker OS filter at server.py:9855 is now case-insensitive
      (`visitor_os` vs `allowed_os` lowercased on both sides);
  (b) form_filler._page_has_captcha (CAPTCHA_PATTERNS at form_filler.py:64)
      no longer false-matches on Cloudflare's passive
      /cdn-cgi/challenge-platform/scripts/jsd/main.js bot-analytics
      injection that the Emergent preview-pod edge adds to every response.

Plus a brief regression sweep on existing engine-status / engine-prewarm /
links endpoints.
"""
# ─────── module: imports ───────────────────────────────────────────
import os
import sys
import uuid
import random
import asyncio
import importlib.util
from pathlib import Path

import pytest
import requests
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Frontend env holds the public BASE_URL the user actually sees
load_dotenv("/app/frontend/.env")
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL not set in /app/frontend/.env"

# Backend env for direct Mongo seeding (admin credentials & DB connection)
load_dotenv("/app/backend/.env")
MONGO_URL = os.environ["MONGO_URL"]
DB_NAME = os.environ["DB_NAME"]

ADMIN_EMAIL = "admin@trackmaster.local"
ADMIN_PASSWORD = "admin123"

ANDROID_UA = (
    "Mozilla/5.0 (Linux; Android 13; SM-S918B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)
IOS_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1"
)


def _rand_public_ipv4() -> str:
    """A deterministic-looking but unique-per-test public IPv4 to avoid
    tripping the cross-database duplicate-IP check."""
    return f"203.0.{random.randint(1, 250)}.{random.randint(1, 250)}"


# ─────── fixture: seed two test links directly in Mongo ────────────
@pytest.fixture(scope="module")
def seeded_links():
    """Insert two TEST_ tracking links bypassing the API (admin token cannot
    POST /api/links — that endpoint requires a regular user). Tests will hit
    the public /api/t/<short_code> route which only reads from db.links."""
    short_android = f"TEST_iter16_and_{uuid.uuid4().hex[:8]}"
    short_ios = f"TEST_iter16_ios_{uuid.uuid4().hex[:8]}"

    user_id = f"TEST_iter16_{uuid.uuid4().hex[:8]}"
    base_doc = {
        "offer_url": "https://example.com/offer",
        "status": "active",
        "name": "iter16 OS-fold test",
        "allowed_countries": [],
        "block_vpn": False,
        "duplicate_timer_enabled": False,
        "duplicate_timer_seconds": 30,
        "forced_source": None,
        "forced_source_name": None,
        "referrer_mode": "normal",
        "url_params": None,
        "simulate_platform": None,
        "clicks": 0,
        "conversions": 0,
        "revenue": 0.0,
        "user_id": user_id,
        "created_by": None,
    }

    docs = [
        {**base_doc, "id": str(uuid.uuid4()), "short_code": short_android, "allowed_os": ["android"]},
        {**base_doc, "id": str(uuid.uuid4()), "short_code": short_ios,     "allowed_os": ["ios"]},
    ]

    async def _seed():
        client = AsyncIOMotorClient(MONGO_URL)
        d = client[DB_NAME]
        await d.links.insert_many(docs)
        client.close()

    async def _cleanup():
        client = AsyncIOMotorClient(MONGO_URL)
        d = client[DB_NAME]
        await d.links.delete_many({"short_code": {"$in": [short_android, short_ios]}})
        client.close()

    asyncio.get_event_loop().run_until_complete(_seed()) if False else None
    # Simpler: use asyncio.run for setup/teardown (each in its own loop)
    asyncio.run(_seed())

    yield {"android": short_android, "ios": short_ios, "user_id": user_id}

    asyncio.run(_cleanup())


# ════════════════════════════════════════════════════════════════════
#                FEATURE (a) — tracker OS case-fold
# ════════════════════════════════════════════════════════════════════
class TestOsFoldTracker:
    """server.py:9855 — visitor_os and allowed_os must compare case-insensitively."""

    def test_android_ua_on_android_allowed_link_is_NOT_device_restricted(self, seeded_links):
        # Pre-fix: visitor_os="Android" (title) NOT IN ["android"] → 403 Device Restricted
        # Post-fix: lowercase fold makes it match → no Device Restricted page
        url = f"{BASE_URL}/api/t/{seeded_links['android']}"
        headers = {
            "User-Agent": ANDROID_UA,
            "X-Forwarded-For": _rand_public_ipv4(),
        }
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=20)

        # Either 200/302 (redirect/intermediate) — anything that is NOT the
        # Device Restricted 403 page is acceptable. We assert specifically on
        # the body NOT containing the Device Restricted heading.
        assert "Device Restricted" not in r.text, (
            f"OS-case-fold regression: Android UA on android-allowed link was "
            f"BLOCKED with status={r.status_code}. Body sample: {r.text[:300]}"
        )

    def test_ios_ua_on_android_allowed_link_IS_device_restricted(self, seeded_links):
        # Negative: not over-permissive. iOS UA on android-only link must still block.
        url = f"{BASE_URL}/api/t/{seeded_links['android']}"
        headers = {
            "User-Agent": IOS_UA,
            "X-Forwarded-For": _rand_public_ipv4(),
        }
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=20)
        assert r.status_code == 403, f"Expected 403 for iOS on android link, got {r.status_code}"
        assert "Device Restricted" in r.text
        assert "Your device: iOS" in r.text  # confirms detect_device produced 'iOS'

    def test_android_ua_on_ios_allowed_link_IS_device_restricted(self, seeded_links):
        # Negative: Android UA on ios-only link must still block.
        url = f"{BASE_URL}/api/t/{seeded_links['ios']}"
        headers = {
            "User-Agent": ANDROID_UA,
            "X-Forwarded-For": _rand_public_ipv4(),
        }
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=20)
        assert r.status_code == 403, f"Expected 403 for Android on ios link, got {r.status_code}"
        assert "Device Restricted" in r.text
        assert "Your device: Android" in r.text

    def test_ios_ua_on_ios_allowed_link_is_NOT_device_restricted(self, seeded_links):
        # Mirror of the positive android-on-android test — iOS on iOS-allowed.
        url = f"{BASE_URL}/api/t/{seeded_links['ios']}"
        headers = {
            "User-Agent": IOS_UA,
            "X-Forwarded-For": _rand_public_ipv4(),
        }
        r = requests.get(url, headers=headers, allow_redirects=False, timeout=20)
        assert "Device Restricted" not in r.text, (
            f"iOS UA on ios-allowed link was wrongly blocked. status={r.status_code} "
            f"body: {r.text[:300]}"
        )


# ════════════════════════════════════════════════════════════════════
#       FEATURE (b) — form_filler.CAPTCHA_PATTERNS regex sweep
# ════════════════════════════════════════════════════════════════════
def _import_form_filler_patterns():
    """Import form_filler from /app/backend without polluting sys.path
    permanently. Returns the CAPTCHA_PATTERNS list."""
    backend_dir = "/app/backend"
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    spec = importlib.util.spec_from_file_location(
        "form_filler_under_test", str(Path(backend_dir) / "form_filler.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.CAPTCHA_PATTERNS


CAPTCHA_PATTERNS = _import_form_filler_patterns()


def _has_captcha(html: str) -> bool:
    """Mirror of form_filler._page_has_captcha but on raw HTML (no Page)."""
    return any(p.search(html) for p in CAPTCHA_PATTERNS)


class TestCaptchaDetectorTrueNegatives:
    """HTML that LOOKS captcha-ish but is benign — must return False."""

    def test_cloudflare_passive_jsd_injection_is_not_captcha(self):
        # The exact Emergent preview-pod injection that caused 71/100 false
        # 'skipped_captcha' tags in the user's RUT job.
        html = """<!doctype html><html><head>
        <script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>
        </head><body><h1>Hello</h1></body></html>"""
        assert _has_captcha(html) is False, "False-positive on CF passive jsd injection"

    def test_word_captcha_in_prose_is_not_captcha(self):
        # A blog/article that just MENTIONS the word captcha must not trip.
        html = """<html><body>
        <p>Today we will talk about how captcha systems work in modern web apps.</p>
        <p>The word captcha appears multiple times in this captcha-themed article.</p>
        </body></html>"""
        assert _has_captcha(html) is False

    def test_empty_page_is_not_captcha(self):
        assert _has_captcha("<html></html>") is False

    def test_normal_form_without_widget_is_not_captcha(self):
        html = """<html><body><form>
            <input name="email"><input name="password" type="password">
            <button type="submit">Login</button>
        </form></body></html>"""
        assert _has_captcha(html) is False


class TestCaptchaDetectorTruePositives:
    """HTML containing a real challenge widget — must return True."""

    def test_cloudflare_turnstile_iframe_is_captcha(self):
        html = '<html><body><iframe src="https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/ov2/123"></iframe></body></html>'
        assert _has_captcha(html) is True

    def test_cf_turnstile_div_widget_is_captcha(self):
        html = '<html><body><div class="cf-turnstile" data-sitekey="0xAA"></div></body></html>'
        assert _has_captcha(html) is True

    def test_g_recaptcha_div_widget_is_captcha(self):
        html = '<html><body><div class="g-recaptcha" data-sitekey="6Lc..."></div></body></html>'
        assert _has_captcha(html) is True

    def test_h_captcha_div_widget_is_captcha(self):
        html = '<html><body><div class="h-captcha" data-sitekey="abc"></div></body></html>'
        assert _has_captcha(html) is True

    def test_recaptcha_iframe_src_is_captcha(self):
        html = '<html><body><iframe src="https://www.google.com/recaptcha/api2/anchor?ar=1"></iframe></body></html>'
        assert _has_captcha(html) is True

    def test_hcaptcha_iframe_src_is_captcha(self):
        html = '<html><body><iframe src="https://hcaptcha.com/captcha/v1"></iframe></body></html>'
        assert _has_captcha(html) is True

    def test_real_cf_interstitial_token_is_captcha(self):
        # Real "Just a moment…" page has these tokens — preview-pod jsd does not.
        html = '<html><script>window.__cf_chl_jschl_tk__="abc123";</script></html>'
        assert _has_captcha(html) is True

    def test_real_cf_managed_challenge_token_is_captcha(self):
        html = '<html><script>window.__cf_chl_managed_tk__="zzz";</script></html>'
        assert _has_captcha(html) is True

    def test_cf_mitigated_marker_is_captcha(self):
        html = '<html><meta name="cf-mitigated" content="challenge"></html>'
        assert _has_captcha(html) is True

    def test_recaptcha_iframe_title_is_captcha(self):
        html = '<html><iframe title="reCAPTCHA challenge expires in two minutes"></iframe></html>'
        assert _has_captcha(html) is True


# ════════════════════════════════════════════════════════════════════
#                 REGRESSION — prior iterations
# ════════════════════════════════════════════════════════════════════
@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/admin/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=15,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login failed: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


class TestRegressionPriorIterations:
    """Sanity sweep — verify nothing else broke."""

    def test_admin_login_works(self, admin_token):
        assert admin_token and isinstance(admin_token, str) and len(admin_token) > 20

    def test_engine_status_endpoint_still_works(self, admin_token):
        # iteration_14 endpoint
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/engine-status",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert r.status_code == 200, f"engine-status broken: {r.status_code} {r.text[:200]}"
        data = r.json()
        assert "status" in data
        assert data["status"] in {"ready", "missing", "installing"}
        # must NOT leak browser_path
        assert "browser_path" not in data

    def test_engine_prewarm_endpoint_still_works(self, admin_token):
        # iteration_15 endpoint — already_ready idempotent path
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/engine-prewarm",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20,
        )
        assert r.status_code == 200, f"engine-prewarm broken: {r.status_code} {r.text[:200]}"
        body = r.json()
        # In a healthy env chromium is installed → already_ready=True
        assert "started" in body and "status" in body

    def test_real_user_traffic_jobs_endpoint_still_lists(self, admin_token):
        # GET should at minimum not 500; 200 with list, or 403 if feature flag —
        # we only require it to NOT be a server error.
        r = requests.get(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=15,
        )
        assert r.status_code < 500, f"RUT jobs endpoint 5xx: {r.status_code} {r.text[:200]}"

    def test_unknown_short_code_returns_404(self):
        # Negative regression on tracker route after the OS-fold change.
        r = requests.get(
            f"{BASE_URL}/api/t/THIS_DOES_NOT_EXIST_iter16_xyz",
            headers={"User-Agent": ANDROID_UA, "X-Forwarded-For": _rand_public_ipv4()},
            timeout=15,
            allow_redirects=False,
        )
        assert r.status_code == 404
