"""
Form Filler / Survey Bot
-------------------------
Auto-fills a target form using data rows from Excel/CSV or a Google Sheet
(published-as-CSV URL). Uses Playwright headless Chromium — one submission
per row — takes a screenshot of the post-submit page.

Usage flow (invoked from server.py endpoints):
    1. POST /api/form-filler/jobs  -> create job, upload data, kick off bg task
    2. GET  /api/form-filler/jobs           -> list jobs
    3. GET  /api/form-filler/jobs/{id}      -> status + progress
    4. GET  /api/form-filler/jobs/{id}/download -> ZIP (screenshots + report.csv)
"""
from __future__ import annotations
import asyncio
import csv
import io
import os
import random
import re
import shutil
import time
import uuid
import zipfile
import logging

# Ensure Playwright finds the Chromium that was installed at the system path.
# The pip `playwright install chromium` command put browsers in /pw-browsers/;
# Playwright looks at the default ~/.cache/ms-playwright unless this env var
# is set. MUST be set BEFORE `from playwright.async_api import ...`.
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and os.path.isdir("/pw-browsers"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "/pw-browsers"

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any

import httpx
import pandas as pd
from playwright.async_api import async_playwright, Page, BrowserContext

logger = logging.getLogger(__name__)

# ─────── Storage root ──────────────────────────────────────────────
RESULTS_ROOT = Path("/app/backend/form_filler_results")
RESULTS_ROOT.mkdir(parents=True, exist_ok=True)

# In-memory job registry (jobs also persisted in Mongo; this is the hot cache)
JOBS: Dict[str, Dict[str, Any]] = {}

# ─────── Captcha detection heuristics ──────────────────────────────
# We look for ACTUAL challenge widgets / iframes that block interaction —
# NOT any random script tag. Cloudflare's preview-pod / proxy edge often
# injects `<script>…/cdn-cgi/challenge-platform/scripts/jsd/main.js…</script>`
# (passive bot analytics, not a real challenge) into every response —
# matching that bare string was producing 100% false positives and made
# Real-User-Traffic mark every preview-pod tracker visit as
# `skipped_captcha`. The patterns below match only genuine, visible
# challenge surfaces:
#   • iframe srcs on the canonical challenge hosts (challenges.cloudflare.com
#     / google reCAPTCHA / hCaptcha)
#   • specific widget classes / IDs that imply a rendered challenge
#   • the literal Turnstile widget tag.
CAPTCHA_PATTERNS = [
    re.compile(r'src=["\'][^"\']*challenges\.cloudflare\.com', re.I),
    re.compile(r'src=["\'][^"\']*google\.com/recaptcha', re.I),
    re.compile(r'src=["\'][^"\']*recaptcha\.net', re.I),
    re.compile(r'src=["\'][^"\']*hcaptcha\.com', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*g-recaptcha\b', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*h-captcha\b', re.I),
    re.compile(r'<div[^>]+class=["\'][^"\']*cf-turnstile\b', re.I),
    re.compile(r'<iframe[^>]+title=["\'][^"\']*recaptcha', re.I),
    re.compile(r'<iframe[^>]+title=["\'][^"\']*hcaptcha', re.I),
    # Real Cloudflare interstitial pages — the "Just a moment…" page —
    # have BOTH the `__cf_chl_` query-arg JS AND the cf-mitigated script;
    # the bare "/cdn-cgi/challenge-platform/scripts/jsd/main.js" injection
    # used by preview pods does NOT have these.
    re.compile(r'__cf_chl_jschl_tk__|__cf_chl_managed_tk__', re.I),
    re.compile(r'cf-mitigated|cf-error-details', re.I),
]


async def _page_has_captcha(page: Page) -> bool:
    """Return True only when a GENUINE captcha / interactive challenge
    widget is visible on the page. Returns False for Cloudflare's passive
    /cdn-cgi/challenge-platform/scripts/jsd/main.js bot analytics
    injection which preview-pod / proxy edges add to every response."""
    try:
        html = await page.content()
    except Exception:
        return False
    return any(p.search(html) for p in CAPTCHA_PATTERNS)


# ─────── Input data loading ────────────────────────────────────────
def load_rows_from_excel(file_bytes: bytes, filename: str) -> List[Dict[str, Any]]:
    """Load rows from an uploaded Excel/CSV file. Returns list of dicts keyed
    by column name (snake-cased + lower-cased for robust matching)."""
    if filename.lower().endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))
    df.columns = [_norm_key(c) for c in df.columns]
    return df.to_dict(orient="records")


async def load_rows_from_google_sheet(public_csv_url: str) -> List[Dict[str, Any]]:
    """Fetch rows from a Google Sheet that has been published as CSV.
    (File → Share → Publish to web → CSV, or the public /export?format=csv URL.)"""
    # Accept both the /edit URL and the /export URL
    if "/edit" in public_csv_url and "export" not in public_csv_url:
        m = re.search(r"/d/([a-zA-Z0-9_-]+)", public_csv_url)
        if m:
            public_csv_url = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as cli:
        r = await cli.get(public_csv_url)
        if r.status_code != 200:
            raise ValueError(f"Could not fetch Google Sheet (HTTP {r.status_code}). Make sure it's 'Publish to web → CSV' or the shared view URL.")
        df = pd.read_csv(io.BytesIO(r.content))
    df.columns = [_norm_key(c) for c in df.columns]
    return df.to_dict(orient="records")


def _norm_key(k: str) -> str:
    """Normalise a column header for robust matching (lower + non-alnum→'_')."""
    return re.sub(r"[^a-z0-9]+", "_", str(k).lower()).strip("_")


# ─────── Column alias map ──────────────────────────────────────────
# Maps common spreadsheet column names → the form field name they likely match.
# Used as a second-pass fallback when the raw key doesn't match any field.
_COLUMN_ALIASES: Dict[str, List[str]] = {
    "first":       ["first_name", "fname", "firstname", "given_name", "given"],
    "first_name":  ["first", "fname", "firstname", "given_name"],
    "last":        ["last_name", "lname", "lastname", "surname", "family_name"],
    "last_name":   ["last", "lname", "lastname", "surname", "family_name"],
    "fullname":    ["name", "full_name"],
    "name":        ["full_name", "fullname"],
    "email":       ["email_address", "emailaddress", "e_mail", "mail"],
    "cellphone":   ["phone", "phone_number", "phonenumber", "mobile", "mobilephone", "cell", "contact", "tel", "telephone"],
    "cell":        ["phone", "phone_number", "mobile", "cellphone"],
    "mobile":      ["phone", "phone_number", "cellphone"],
    "phone":       ["cellphone", "cell", "mobile", "phone_number", "tel", "contact", "telephone"],
    "address":     ["street_address", "streetaddress", "street", "addr", "address1", "address_1", "line1"],
    "street":      ["address", "street_address", "streetaddress", "addr"],
    "address1":    ["address", "street_address", "line1"],
    "zip":         ["zipcode", "zip_code", "postal", "postal_code", "postcode"],
    "zipcode":     ["zip", "zip_code", "postal", "postal_code"],
    "postal":      ["zip", "zipcode", "zip_code", "postal_code"],
    "dob":         ["date_of_birth", "birth", "birthdate", "birthday"],
    "day":         ["dob_day", "dobday", "birth_day", "birthday", "bday", "day_of_birth"],
    "month":       ["dob_month", "dobmonth", "birth_month", "bmonth", "month_of_birth"],
    "year":        ["dob_year", "dobyear", "birth_year", "byear", "year_of_birth"],
    "state":       ["region", "province"],
    "city":        ["town", "locality"],
}


def _value_for_key(row: Dict[str, Any], candidate_keys: List[str]) -> Optional[Any]:
    """Given a list of normalised keys (from a form field's name/id/placeholder
    /label), return a matching value from `row`. Uses exact match, then aliases,
    then fuzzy substring match."""
    for k in candidate_keys:
        if not k:
            continue
        # 1. Exact match
        if k in row and row[k] not in (None, ""):
            return row[k]
        # 2. Alias match — does any alias of a row column equal this key?
        for rk, rv in row.items():
            if rv in (None, ""):
                continue
            if k in _COLUMN_ALIASES.get(rk, []):
                return rv
        # 3. Does any alias of `k` exist in row?
        for alias in _COLUMN_ALIASES.get(k, []):
            if alias in row and row[alias] not in (None, ""):
                return row[alias]
    # 4. Fuzzy substring match as last resort
    for k in candidate_keys:
        if not k:
            continue
        for rk, rv in row.items():
            if rv in (None, ""):
                continue
            if (rk in k or k in rk) and len(rk) >= 3:
                return rv
    return None


def _reformat_value(cand_keys: List[str], attrs: dict, raw_value: Any) -> str:
    """Apply common format conversions — phone numbers, for example, often
    need `xxx-xxx-xxxx` when the source has plain digits."""
    s = str(raw_value).strip()
    joined_key = " ".join(cand_keys) + " " + (attrs.get("placeholder") or "")
    joined_key = joined_key.lower()
    is_phone = any(tok in joined_key for tok in ("phone", "cell", "mobile", "tel"))
    if is_phone:
        digits = re.sub(r"\D", "", s)
        if len(digits) == 10:
            # Prefer hyphenated format when the placeholder hints it
            if "-" in (attrs.get("placeholder") or "") or "000-000-0000" in joined_key:
                return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
            if "(" in (attrs.get("placeholder") or ""):
                return f"({digits[0:3]}) {digits[3:6]}-{digits[6:10]}"
            # Default: return hyphenated (most common US format)
            return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
        if len(digits) == 11 and digits.startswith("1"):
            d = digits[1:]
            return f"{d[0:3]}-{d[3:6]}-{d[6:10]}"
    return s


# ─────── Landing-page CTA auto-click ───────────────────────────────
_LANDING_CTA_SELECTORS = [
    'button:has-text("UNLOCK")', 'a:has-text("UNLOCK")',
    'button:has-text("Claim")',  'a:has-text("Claim")',
    'button:has-text("Get Started")', 'a:has-text("Get Started")',
    'button:has-text("Start Now")', 'a:has-text("Start Now")',
    'button:has-text("Start")', 'a:has-text("Start")',
    'button:has-text("Continue")', 'a:has-text("Continue")',
    'button:has-text("Begin")', 'a:has-text("Begin")',
    'button:has-text("Sign up")', 'a:has-text("Sign up")',
    'button:has-text("Enter")', 'a:has-text("Enter")',
    'button:has-text("Next")', 'a:has-text("Next")',
    'a.btn', 'button.btn-primary', 'button.cta', '.cta-button',
]


async def _dismiss_popups(page: Page):
    """Best-effort: dismiss cookie banners / popups / age gates that block clicks."""
    for sel in [
        'button:has-text("Accept")', 'button:has-text("Accept All")',
        'button:has-text("I Agree")', 'button:has-text("Agree")',
        'button:has-text("OK")', 'button:has-text("Got it")',
        'button:has-text("Allow")', 'button:has-text("Yes")',
        '[aria-label="Close"]', 'button.close', '.cookie-accept',
    ]:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(500)
        except Exception:
            continue


async def _ensure_form_visible(page: Page, max_tries: int = 2) -> int:
    """If the current page has no fillable inputs, click a prominent CTA up to
    `max_tries` times. Returns the number of fillable inputs finally visible."""
    for attempt in range(max_tries + 1):
        await _dismiss_popups(page)
        inputs = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), "
            "textarea, select"
        )
        # Count real text-input fields (at least one visible)
        visible_count = 0
        for inp in inputs[:40]:
            try:
                if await inp.is_visible():
                    visible_count += 1
            except Exception:
                pass
        if visible_count >= 2:
            return visible_count
        if attempt >= max_tries:
            return visible_count
        # Click first visible CTA
        clicked = False
        for sel in _LANDING_CTA_SELECTORS:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            return visible_count
        # Wait for navigation / form to render. Some landing pages take >15s to
        # settle (heavy analytics / third-party JS) — we wait both for DOM
        # content and then networkidle, but silence timeouts.
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        await page.wait_for_timeout(2000)
    return 0


async def _tick_consent_checkboxes(page: Page):
    """Tick any visible unchecked checkbox before submit (most forms have a
    single 'I agree / I consent' that blocks submit if unchecked).
    Uses click() + JS fallback because some sites bind custom handlers."""
    try:
        boxes = await page.query_selector_all("input[type=checkbox]")
        for cb in boxes:
            try:
                if not await cb.is_visible():
                    continue
                is_checked = await cb.is_checked()
                if not is_checked:
                    try:
                        await cb.check()
                    except Exception:
                        # JS fallback
                        await cb.evaluate("""e => {
                            e.checked = true;
                            e.dispatchEvent(new Event('change', {bubbles: true}));
                            e.dispatchEvent(new Event('click', {bubbles: true}));
                        }""")
            except Exception:
                continue
    except Exception:
        pass


# Selectors that typically DISMISS a "review / exit-intent / are you sure" modal
# and send the user back to the form for another submit attempt.
# NOTE: "Disregard" on some sites is actually the real submit (it closes the
# modal AND calls formSubmit()). We prefer buttons whose onclick attribute
# contains 'submit' or 'form', falling back to text heuristics.
_MODAL_SUBMIT_PREFERRED = [
    'button:has-text("Submit anyway")',
    'button:has-text("Yes, Submit")',
    'button:has-text("Yes, continue")',
    'button:has-text("Confirm")',
    'button:has-text("Disregard")',
    'a:has-text("Disregard")',
    'button:has-text("Continue")',
    'a:has-text("Continue")',
    'button:has-text("Yes")',
    'a:has-text("Yes")',
]


async def _dismiss_review_modal(page: Page) -> bool:
    """If a post-submit modal appeared, find the button that ACTUALLY submits
    (not the one that just returns to the form). Preferred picks:
        1. A button with onclick containing `submit` or `form`
        2. Text-based heuristics: Submit / Disregard / Continue / Yes / Confirm
    Returns True if a button was clicked."""
    # Strategy 1: inspect onclick attributes for submit intent
    try:
        candidates = await page.query_selector_all(
            ".modal button, .modal a, [role=dialog] button, [role=dialog] a, "
            ".popup button, .popup a, .overlay button, .overlay a, "
            "a.confirm, a.disregard, button.confirm, button.disregard"
        )
        for el in candidates:
            try:
                if not await el.is_visible():
                    continue
                info = await el.evaluate("""e => ({
                    onclick: (e.getAttribute('onclick') || '').toLowerCase(),
                    text: (e.innerText || '').trim().toLowerCase(),
                    cls: (e.className || '').toLowerCase()
                })""")
                if any(tok in info["onclick"] for tok in ("submit", "formsubmit", "form.submit")):
                    await el.click()
                    await page.wait_for_timeout(800)
                    return True
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 2: text-based heuristics
    for sel in _MODAL_SUBMIT_PREFERRED:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                await page.wait_for_timeout(800)
                return True
        except Exception:
            continue
    return False


# ─────── Form field auto-matching ───────────────────────────────────
async def _fill_form(page: Page, row: Dict[str, Any]) -> Dict[str, Any]:
    """
    For every input/textarea/select on the page, try to find a matching
    column in `row` by comparing the normalised forms of:
        name, id, placeholder, aria-label, label text
    Returns {filled: [keys], skipped: [keys], matched: n}
    """
    filled: List[str] = []
    try:
        inputs = await page.query_selector_all(
            "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=reset]):not([type=image]), "
            "textarea, select"
        )
    except Exception as e:
        return {"filled": [], "skipped": list(row.keys()), "error": str(e)}

    for el in inputs:
        try:
            if not await el.is_visible():
                continue
        except Exception:
            pass
        try:
            attrs = await el.evaluate("""el => ({
                name: el.name || '',
                id: el.id || '',
                type: (el.type || '').toLowerCase(),
                placeholder: el.placeholder || '',
                aria: el.getAttribute('aria-label') || '',
                tag: el.tagName.toLowerCase()
            })""")
        except Exception:
            continue
        if attrs.get("type") in ("checkbox", "radio"):
            continue  # handled separately by _tick_consent_checkboxes

        # Gather candidate keys
        cand_keys = [
            _norm_key(attrs.get("name", "")),
            _norm_key(attrs.get("id", "")),
            _norm_key(attrs.get("placeholder", "")),
            _norm_key(attrs.get("aria", "")),
        ]
        cand_keys = [k for k in cand_keys if k]

        # Try label text too
        try:
            label_text = await el.evaluate("""el => {
                if (el.id) {
                    const l = document.querySelector('label[for="'+el.id+'"]');
                    if (l) return l.innerText || '';
                }
                const parentLabel = el.closest('label');
                return parentLabel ? parentLabel.innerText : '';
            }""")
            if label_text:
                cand_keys.append(_norm_key(label_text))
        except Exception:
            pass

        value = _value_for_key(row, cand_keys)
        if value is None:
            # Date dropdown heuristic: if this is a <select> and we can detect
            # whether it's day/month/year based on options count
            if attrs.get("tag") == "select":
                try:
                    opts_count = await el.evaluate("e => e.options.length")
                    if opts_count in (13, 14) and "month" in row:  # 12 months + placeholder
                        value = row.get("month")
                        cand_keys.append("month")
                    elif opts_count in (29, 30, 31, 32) and "day" in row:
                        value = row.get("day")
                        cand_keys.append("day")
                    elif opts_count > 30 and "year" in row:
                        # likely a year dropdown
                        value = row.get("year")
                        cand_keys.append("year")
                except Exception:
                    pass
        if value is None or value == "":
            continue

        final_value = _reformat_value(cand_keys, attrs, value)
        try:
            if attrs.get("tag") == "select":
                # Try select by value / label / index
                try:
                    await el.select_option(value=str(final_value))
                except Exception:
                    try:
                        await el.select_option(label=str(final_value))
                    except Exception:
                        # Last resort — try by numeric index (month as "1" → index 1)
                        try:
                            idx = int(final_value)
                            await el.select_option(index=idx)
                        except Exception:
                            continue
            else:
                # Primary attempt: fast fill (works for most inputs)
                try:
                    await el.fill(str(final_value))
                except Exception as e:
                    logger.debug(f"fill raised: {e}")

                # Verify the value actually landed. Some inputs have JS masks
                # (e.g. phone `000-000-0000`) that silently reject .fill() or
                # strip the value on the `input` event. If the stored value
                # differs, fall back to the React/Vue-compatible JS native
                # setter — this dispatches the input/change events the mask
                # expects while bypassing the value-sync that fights .fill().
                try:
                    cur_val = await el.input_value()
                except Exception:
                    cur_val = None

                if not cur_val or cur_val.replace("-", "").replace(" ", "").replace("(", "").replace(")", "") != re.sub(r"[\s\-()]", "", str(final_value)):
                    try:
                        await el.evaluate("""(e, v) => {
                            const setter = Object.getOwnPropertyDescriptor(
                                window.HTMLInputElement.prototype, 'value'
                            )?.set || Object.getOwnPropertyDescriptor(
                                window.HTMLTextAreaElement.prototype, 'value'
                            )?.set;
                            if (setter) setter.call(e, v); else e.value = v;
                            e.dispatchEvent(new Event('input', {bubbles: true}));
                            e.dispatchEvent(new Event('change', {bubbles: true}));
                            e.dispatchEvent(new Event('blur', {bubbles: true}));
                        }""", str(final_value))
                    except Exception as e:
                        logger.debug(f"JS setter fallback failed on {cand_keys}: {e}")

                    # Last resort — simulate real typing with keyboard events
                    try:
                        cur_val2 = await el.input_value()
                    except Exception:
                        cur_val2 = None
                    if not cur_val2:
                        try:
                            await el.click()
                            await page.keyboard.press("Control+a")
                            await page.keyboard.press("Delete")
                            await page.keyboard.type(str(final_value), delay=30)
                        except Exception as e:
                            logger.debug(f"keyboard.type fallback failed on {cand_keys}: {e}")
            filled.append(cand_keys[0] if cand_keys else "")
        except Exception as e:
            logger.debug(f"fill failed on {cand_keys}: {e}")
            continue

    skipped = [k for k in row.keys() if k not in filled]
    return {"filled": filled, "skipped": skipped, "matched": len(filled)}


async def _click_submit(page: Page) -> bool:
    """Click the most likely submit button and return True on success."""
    candidates = [
        "button[type=submit]",
        "input[type=submit]",
        "button:has-text('Submit')",
        "button:has-text('Send')",
        "button:has-text('Continue')",
        "button:has-text('CONTINUE')",
        "button:has-text('Next')",
        "button:has-text('Finish')",
        "button:has-text('Complete')",
        "button:has-text('Claim')",
        "button:has-text('Unlock')",
        "button:has-text('Get')",
        "a:has-text('Continue')",
        "a:has-text('Submit')",
    ]
    for sel in candidates:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click()
                return True
        except Exception:
            continue
    try:
        await page.evaluate("const f = document.querySelector('form'); if (f) f.submit();")
        return True
    except Exception:
        return False


# ─────── Job runner ────────────────────────────────────────────────
async def run_form_filler_job(
    job_id: str,
    target_url: str,
    rows: List[Dict[str, Any]],
    count: int,
    duration_minutes: float,
    user_agents: Optional[List[str]] = None,
    proxies: Optional[List[str]] = None,
    skip_captcha: bool = True,
    db=None,
):
    """
    Runs the batch sequentially. Progress is written to JOBS[job_id]
    and (if db provided) to Mongo every few iterations.
    """
    total = min(count, len(rows))
    if total <= 0:
        _finalise(job_id, status="failed", error="No rows to process")
        return

    delay = max(1.0, (duration_minutes * 60.0) / total) if duration_minutes > 0 else 2.0

    job_dir = RESULTS_ROOT / job_id
    shots_dir = job_dir / "screenshots"
    shots_dir.mkdir(parents=True, exist_ok=True)

    report: List[Dict[str, Any]] = []
    JOBS[job_id].update({
        "status": "running",
        "total": total,
        "processed": 0,
        "succeeded": 0,
        "skipped_captcha": 0,
        "failed": 0,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "delay_seconds": round(delay, 2),
    })
    if db is not None:
        await _persist(db, job_id)

    try:
        async with async_playwright() as p:
            for i in range(total):
                row = rows[i % len(rows)]
                ua = random.choice(user_agents) if user_agents else None
                proxy_cfg = _parse_proxy(random.choice(proxies)) if proxies else None

                status = "pending"
                error = ""
                shot_path = ""
                skip_reason = ""
                lead_proof = {}
                browser = None
                try:
                    browser = await p.chromium.launch(
                        headless=True,
                        proxy=proxy_cfg,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                    context = await browser.new_context(user_agent=ua) if ua else await browser.new_context()
                    page = await context.new_page()
                    await page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(800)

                    if skip_captcha and await _page_has_captcha(page):
                        status = "skipped_captcha"
                        skip_reason = "Captcha detected — traffic skipped"
                    else:
                        # If the landing page has no form yet, auto-click a CTA
                        # (e.g. "UNLOCK NOW", "Claim", "Start", "Continue") until
                        # a real form becomes visible.
                        await _ensure_form_visible(page, max_tries=2)

                        if skip_captcha and await _page_has_captcha(page):
                            status = "skipped_captcha"
                            skip_reason = "Captcha detected after CTA click"
                        else:
                            # Multi-step form loop: keep filling + submitting
                            # until URL stops changing OR no more inputs visible
                            # OR a "thank you" / success page is detected.
                            total_filled = 0
                            max_steps = 6  # safety cap
                            last_url = ""
                            for step in range(max_steps):
                                # Wait for any step-2 inputs to render
                                await page.wait_for_timeout(800)
                                await _dismiss_popups(page)

                                fill_info = await _fill_form(page, row)
                                step_filled = len(fill_info.get("filled") or [])
                                total_filled += step_filled

                                # If nothing new got filled on this step AND it's
                                # the first step, bail out with no_fields_matched
                                if step == 0 and step_filled == 0:
                                    status = "no_fields_matched"
                                    error = "No fillable fields matched the provided columns"
                                    break

                                # Detect "thank you" / success page (has no more
                                # fillable fields) — declare success and exit
                                if step > 0 and step_filled == 0:
                                    # Check if it looks like a success page
                                    try:
                                        html_lower = (await page.content()).lower()
                                    except Exception:
                                        html_lower = ""
                                    success_tokens = (
                                        "thank you", "thanks!", "congratulations",
                                        "confirmation", "successfully", "submitted",
                                        "we received", "check your email",
                                    )
                                    if any(t in html_lower for t in success_tokens):
                                        status = "ok"
                                    else:
                                        # No form fields + no success text — may be
                                        # a redirect to offer/listing page. Still OK.
                                        status = "ok"
                                    break

                                await _tick_consent_checkboxes(page)
                                try:
                                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight/2)")
                                except Exception:
                                    pass

                                start_url = page.url
                                await _click_submit(page)

                                # Handle post-submit modals on each step
                                for _attempt in range(2):
                                    try:
                                        await page.wait_for_load_state(
                                            "networkidle", timeout=8000
                                        )
                                    except Exception:
                                        pass
                                    await page.wait_for_timeout(1200)
                                    if page.url != start_url:
                                        break
                                    handled = await _dismiss_review_modal(page)
                                    if handled:
                                        await _tick_consent_checkboxes(page)
                                        await page.wait_for_timeout(400)
                                        await _click_submit(page)
                                        continue
                                    break

                                # If URL didn't change and we can't find more
                                # forms, stop (final screenshot will still be
                                # taken below)
                                if page.url == start_url:
                                    if not status:
                                        status = "submitted_but_no_redirect"
                                    break

                                # URL changed — loop around to handle next step
                                last_url = page.url

                            if status not in ("no_fields_matched", "skipped_captcha"):
                                if not status or status == "pending":
                                    status = "ok"

                            # Capture lead-tracking proof (TrustedForm cert,
                            # LeadiD, universal_leadid) that many US lead-gen
                            # platforms inject into the final page after a
                            # successful submission.
                            try:
                                lead_proof = await page.evaluate("""() => {
                                    const grab = sel => {
                                        const el = document.querySelector(sel);
                                        return el ? (el.value || el.getAttribute('value') || '') : '';
                                    };
                                    return {
                                        trusted_form: grab('[name="xxTrustedFormCertUrl"]')
                                                   || grab('[name="xxTrustedFormToken"]'),
                                        lead_id: grab('#leadid_token')
                                              || grab('[name="universal_leadid"]')
                                              || grab('[name="LeadiD"]'),
                                    };
                                }""")
                            except Exception:
                                lead_proof = {}
                            try:
                                lead_proof["final_url"] = page.url
                            except Exception:
                                pass

                            # Wait an extra moment so dynamic offers / thank-you
                            # content renders before the screenshot
                            try:
                                await page.wait_for_load_state("networkidle", timeout=5000)
                            except Exception:
                                pass
                            await page.wait_for_timeout(1500)

                            # Screenshot the final page regardless of outcome
                            shot_path = str(shots_dir / f"row_{i+1:05d}.png")
                            try:
                                await page.screenshot(path=shot_path, full_page=True)
                            except Exception as e:
                                logger.warning(f"screenshot failed: {e}")
                    await context.close()
                except Exception as e:
                    status = "failed"
                    error = str(e)[:250]
                finally:
                    if browser is not None:
                        try: await browser.close()
                        except Exception: pass

                # Update counters
                j = JOBS[job_id]
                j["processed"] = i + 1
                if status == "ok":
                    j["succeeded"] += 1
                elif status == "skipped_captcha":
                    j["skipped_captcha"] += 1
                else:
                    j["failed"] += 1

                report.append({
                    "row_index": i + 1,
                    "status": status,
                    "error": error or skip_reason,
                    "screenshot": os.path.basename(shot_path) if shot_path else "",
                    "user_agent": ua or "",
                    "proxy": (proxy_cfg or {}).get("server", "") if proxy_cfg else "",
                    "trusted_form": (lead_proof or {}).get("trusted_form", ""),
                    "lead_id": (lead_proof or {}).get("lead_id", ""),
                    "final_url": (lead_proof or {}).get("final_url", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

                if db is not None and (i + 1) % 3 == 0:
                    await _persist(db, job_id)

                # Pacing
                if i < total - 1:
                    await asyncio.sleep(delay)

        # Write report.csv
        with open(job_dir / "report.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["row_index", "status", "error", "screenshot", "user_agent", "proxy", "trusted_form", "lead_id", "final_url", "timestamp"],
            )
            writer.writeheader()
            writer.writerows(report)

        # Build ZIP for download
        zip_path = job_dir / "results.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for p in shots_dir.glob("*.png"):
                zf.write(p, arcname=f"screenshots/{p.name}")
            zf.write(job_dir / "report.csv", arcname="report.csv")

        JOBS[job_id].update({
            "status": "completed",
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "report": report,
            "zip_path": str(zip_path),
        })
    except Exception as e:
        logger.exception(f"Job {job_id} crashed")
        _finalise(job_id, status="failed", error=str(e)[:300])
    finally:
        if db is not None:
            await _persist(db, job_id)


def _finalise(job_id: str, status: str, error: str = ""):
    j = JOBS.setdefault(job_id, {})
    j["status"] = status
    if error:
        j["error"] = error
    j["finished_at"] = datetime.now(timezone.utc).isoformat()


def _parse_proxy(proxy_str: str) -> Optional[Dict[str, str]]:
    """Parse `ip:port` or `ip:port:user:pass` or `http://user:pass@ip:port` into playwright proxy dict."""
    proxy_str = (proxy_str or "").strip()
    if not proxy_str:
        return None
    if proxy_str.startswith("http"):
        return {"server": proxy_str}
    parts = proxy_str.split(":")
    if len(parts) == 2:
        return {"server": f"http://{parts[0]}:{parts[1]}"}
    if len(parts) == 4:
        return {
            "server": f"http://{parts[0]}:{parts[1]}",
            "username": parts[2],
            "password": parts[3],
        }
    return None


async def _persist(db, job_id: str):
    j = JOBS.get(job_id, {})
    try:
        await db.form_filler_jobs.update_one(
            {"job_id": job_id},
            {"$set": {**j, "job_id": job_id}},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"Could not persist form-filler job {job_id}: {e}")


def create_job_record(
    job_id: str, user_id: str, target_url: str, total_rows: int,
    count: int, duration_minutes: float, data_source: str,
) -> Dict[str, Any]:
    JOBS[job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "target_url": target_url,
        "total_rows_loaded": total_rows,
        "count": count,
        "duration_minutes": duration_minutes,
        "data_source": data_source,
        "status": "queued",
        "total": min(count, total_rows),
        "processed": 0,
        "succeeded": 0,
        "skipped_captcha": 0,
        "failed": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    return JOBS[job_id]


def cleanup_old_job(job_id: str):
    """Delete screenshots + ZIP for a job (called on /delete)."""
    d = RESULTS_ROOT / job_id
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    JOBS.pop(job_id, None)
