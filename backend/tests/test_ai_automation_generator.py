"""
Tests for the AI Automation Generator feature on Real User Traffic.

Endpoints covered:
  POST /api/real-user-traffic/ai-generate-automation    (new)
  POST /api/real-user-traffic/jobs                      (self_heal field)
"""
import io
import os
import pytest
import requests
from PIL import Image, ImageDraw

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://upload-inspect-demo.preview.emergentagent.com").rstrip("/")
LOGIN_EMAIL = "testuser@demo.com"
LOGIN_PASSWORD = "test1234"


# ── fixtures ──────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": LOGIN_EMAIL, "password": LOGIN_PASSWORD},
        timeout=30,
    )
    assert r.status_code == 200, f"Login failed: {r.status_code} {r.text[:200]}"
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="module")
def mock_png_bytes():
    """Small PNG with a mock form (UNLOCK NOW + First/Last/Email + SUBMIT)."""
    img = Image.new("RGB", (600, 800), "white")
    d = ImageDraw.Draw(img)
    d.rectangle([50, 50, 550, 150], outline="red", width=3)
    d.text((150, 90), "UNLOCK NOW", fill="red")
    d.text((50, 200), "First Name:", fill="black")
    d.rectangle([50, 230, 550, 270], outline="black")
    d.text((50, 300), "Last Name:", fill="black")
    d.rectangle([50, 330, 550, 370], outline="black")
    d.text((50, 400), "Email:", fill="black")
    d.rectangle([50, 430, 550, 470], outline="black")
    d.rectangle([50, 550, 550, 620], outline="green", width=3)
    d.text((250, 580), "SUBMIT", fill="green")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── AI Automation Generator endpoint ─────────────────────────────────
class TestAiAutomationGenerator:
    """POST /api/real-user-traffic/ai-generate-automation"""

    def test_requires_auth(self):
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/ai-generate-automation",
            files={"files": ("x.png", b"\x89PNG\r\n", "image/png")},
            timeout=15,
        )
        assert r.status_code in (401, 403), f"expected 401/403, got {r.status_code}"

    def test_invalid_file_type_returns_400(self, auth_headers):
        """Only an unsupported file (.txt) → 400 No valid image/video files."""
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/ai-generate-automation",
            headers=auth_headers,
            files={"files": ("bad.txt", b"hello world", "text/plain")},
            timeout=30,
        )
        assert r.status_code == 400
        msg = (r.json().get("detail") or "").lower()
        assert "no valid" in msg or "image" in msg or "video" in msg

    def test_more_than_one_video_returns_400(self, auth_headers):
        """Two video uploads → 400 'Only one video per request'."""
        tiny = b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 64
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/ai-generate-automation",
            headers=auth_headers,
            files=[
                ("files", ("a.mp4", tiny, "video/mp4")),
                ("files", ("b.mp4", tiny, "video/mp4")),
            ],
            timeout=60,
        )
        assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text[:200]}"
        assert "one video" in (r.json().get("detail") or "").lower()

    def test_happy_path_with_png_returns_steps(self, auth_headers, mock_png_bytes):
        """Real Gemini 2.5 Pro call — 1 PNG, short description. Expects status=ok with steps[]."""
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/ai-generate-automation",
            headers=auth_headers,
            data={
                "target_url": "https://example-offer.com",
                "description": "Click UNLOCK NOW, fill first, last, email, click SUBMIT.",
                "excel_columns": "first,last,email",
            },
            files=[("files", ("mock_form.png", mock_png_bytes, "image/png"))],
            timeout=180,
        )
        assert r.status_code == 200, f"status {r.status_code}: {r.text[:400]}"
        data = r.json()
        # Accept either 'ok' with steps, or a clean 'failed' (AI key/call issue) — but flag it.
        assert isinstance(data, dict)
        if data.get("status") != "ok":
            pytest.fail(f"Gemini call did not return ok: {data}")
        steps = data.get("steps")
        assert isinstance(steps, list) and len(steps) > 0, f"no steps returned: {data}"
        # sanitiser: every step must have an allowed action
        allowed = {"goto", "click", "fill", "type", "select", "check", "uncheck",
                   "press", "wait", "wait_for_selector", "wait_for_navigation",
                   "wait_for_load", "wait_for_networkidle", "scroll",
                   "screenshot", "evaluate"}
        for s in steps:
            assert isinstance(s, dict) and s.get("action") in allowed, f"bad step: {s}"


# ── self_heal field on jobs endpoint ─────────────────────────────────
class TestJobsSelfHealField:
    """POST /api/real-user-traffic/jobs must accept self_heal form field without breaking."""

    def _get_or_create_link(self, headers):
        r = requests.get(f"{BASE_URL}/api/links", headers=headers, timeout=30)
        assert r.status_code == 200, r.text[:200]
        items = r.json()
        if isinstance(items, dict):
            items = items.get("items") or items.get("links") or []
        if items:
            return items[0]["id"]
        # create one
        c = requests.post(
            f"{BASE_URL}/api/links",
            headers={**headers, "Content-Type": "application/json"},
            json={"name": "TEST_rut_selfheal", "target_url": "https://example.com",
                  "category": "default"},
            timeout=30,
        )
        assert c.status_code in (200, 201), c.text[:200]
        return c.json()["id"]

    def test_jobs_accepts_self_heal_true(self, auth_headers):
        link_id = self._get_or_create_link(auth_headers)
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=auth_headers,
            data={
                "link_id": link_id,
                "target_url": "https://example.com",
                "proxies": "1.2.3.4:8080",
                "user_agents": "Mozilla/5.0 (Test) selfheal",
                "use_stored_proxies": "false",
                "total_clicks": 1,
                "concurrency": 1,
                "duration_minutes": 0,
                "skip_duplicate_ip": "false",
                "skip_vpn": "false",
                "follow_redirect": "false",
                "no_repeated_proxy": "false",
                "form_fill_enabled": "false",
                "self_heal": "true",
            },
            timeout=30,
        )
        # Must NOT 422 (unknown field) — backend should accept self_heal
        assert r.status_code != 422, f"422 Unprocessable — self_heal not accepted: {r.text[:300]}"
        # Job create should succeed (200/201) or fail with a business-logic 4xx that is NOT 422
        assert r.status_code in (200, 201), f"job create failed: {r.status_code} {r.text[:300]}"
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        assert job_id, f"no job_id in response: {body}"

        # Cleanup — best-effort delete the job
        try:
            requests.delete(f"{BASE_URL}/api/real-user-traffic/jobs/{job_id}",
                            headers=auth_headers, timeout=15)
        except Exception:
            pass

    def test_jobs_accepts_self_heal_false(self, auth_headers):
        link_id = self._get_or_create_link(auth_headers)
        r = requests.post(
            f"{BASE_URL}/api/real-user-traffic/jobs",
            headers=auth_headers,
            data={
                "link_id": link_id,
                "target_url": "https://example.com",
                "proxies": "1.2.3.4:8080",
                "user_agents": "Mozilla/5.0 (Test) noheal",
                "use_stored_proxies": "false",
                "total_clicks": 1,
                "concurrency": 1,
                "duration_minutes": 0,
                "form_fill_enabled": "false",
                "self_heal": "false",
            },
            timeout=30,
        )
        assert r.status_code != 422
        assert r.status_code in (200, 201)
        body = r.json()
        job_id = body.get("job_id") or body.get("id")
        assert job_id
        try:
            requests.delete(f"{BASE_URL}/api/real-user-traffic/jobs/{job_id}",
                            headers=auth_headers, timeout=15)
        except Exception:
            pass
