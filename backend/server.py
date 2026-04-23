from fastapi import FastAPI, APIRouter, HTTPException, Depends, status, Request, WebSocket, WebSocketDisconnect, UploadFile, File, Form, BackgroundTasks, Body
from fastapi.responses import RedirectResponse, Response, FileResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import logging
import uuid
import httpx
import asyncio
import json
import time
import random
from user_agents import parse
from pathlib import Path
import resend
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Debug: Print environment variables (remove in production)
import sys
# print(f"DEBUG: ADMIN_EMAIL from env = {os.environ.get('ADMIN_EMAIL', 'NOT SET')}", file=sys.stderr)
# print(f"DEBUG: MONGO_URL present = {bool(os.environ.get('MONGO_URL'))}", file=sys.stderr)

# Get MongoDB URL - support both MONGO_URL and DATABASE_URL
mongo_url = os.environ.get('MONGO_URL') or os.environ.get('DATABASE_URL')
if not mongo_url:
    raise Exception("MONGO_URL environment variable is required!")

# Get database name
db_name = os.environ.get('DB_NAME', 'trackmaster')

client = AsyncIOMotorClient(
    mongo_url,
    maxPoolSize=100,  # Increase connection pool
    minPoolSize=20,
    maxIdleTimeMS=30000
)
main_db = client[db_name]  # Main database for users/admin
db = main_db  # Alias for backward compatibility - will be refactored for per-user DBs

# Cache for click IPs - refreshes every 5 minutes
_click_ips_cache = {
    "ips": set(),
    "last_updated": 0,
    "ttl": 300  # 5 minutes cache
}

# Link cache for high traffic - refreshes every 60 seconds
_link_cache = {}
_link_cache_ttl = 30  # Reduced to 30 seconds for more accurate status checking

# NO VPN cache - check fresh every time for accuracy

async def get_cached_link(short_code: str):
    """Get link from cache or database - cache is short-lived for accuracy"""
    global _link_cache
    current_time = time.time()
    
    # Check cache
    if short_code in _link_cache:
        cached = _link_cache[short_code]
        if current_time - cached["time"] < _link_cache_ttl:
            return cached["link"]
    
    # Fetch from database
    link = await db.links.find_one({"short_code": short_code}, {"_id": 0})
    
    # Cache the result (even if None)
    _link_cache[short_code] = {"link": link, "time": current_time}
    
    # Clean old cache entries (keep max 10000)
    if len(_link_cache) > 10000:
        sorted_keys = sorted(_link_cache.keys(), key=lambda k: _link_cache[k]["time"])
        for k in sorted_keys[:5000]:
            del _link_cache[k]
    
    return link

# Helper function to get user-specific database
def get_user_db(user_id: str):
    """Get database for specific main user - sub-users use parent's database"""
    db_name = f"trackmaster_user_{user_id.replace('-', '_')[:20]}"
    return client[db_name]

def get_db_for_user(user: dict):
    """
    Get the correct database for a user (main user or sub-user).
    - Main users: get their own database
    - Sub-users: get their parent's database
    """
    if user.get("is_sub_user"):
        # Sub-user uses parent's database
        parent_id = user.get("parent_user_id") or user.get("id")
        return get_user_db(parent_id)
    else:
        # Main user uses their own database
        return get_user_db(user["id"])

async def get_all_click_ips_from_entire_database(force_refresh=False):
    """
    Collect ALL IPs from CLICKS in ENTIRE database (all users).
    Uses caching to avoid slow queries on every request.
    
    IMPORTANT: This checks ALL IP fields to match the link redirect duplicate detection:
    - ip_address, ipv4, ipv6 (main IPs)
    - proxy_ips, all_ips (array fields containing intermediate/proxy IPs)
    
    This ensures proxy test duplicate check matches exactly with link redirect duplicate check.
    """
    global _click_ips_cache
    
    current_time = time.time()
    
    # Return cached data if still valid and not forcing refresh
    if not force_refresh and _click_ips_cache["ips"] and (current_time - _click_ips_cache["last_updated"]) < _click_ips_cache["ttl"]:
        logger.info(f"Using cached IPs: {len(_click_ips_cache['ips'])} IPs (cached {int(current_time - _click_ips_cache['last_updated'])}s ago)")
        return _click_ips_cache["ips"]
    
    logger.info("Refreshing click IPs cache (checking ALL IP fields)...")
    all_click_ips = set()
    
    # Fields to check - MUST match link redirect duplicate check fields
    single_ip_fields = ["ip_address", "ipv4", "detected_ip"]
    array_ip_fields = ["proxy_ips", "all_ips"]
    
    async def extract_ips_from_db(database, db_name=""):
        """Extract all IPs from a database's clicks collection"""
        extracted = set()
        try:
            # Get distinct values from single-value IP fields
            for field in single_ip_fields:
                try:
                    distinct_ips = await database.clicks.distinct(field)
                    for ip in distinct_ips:
                        if ip and ip != "unknown" and isinstance(ip, str):
                            extracted.add(ip)
                except Exception:
                    pass
            
            # Get IPs from array fields (proxy_ips, all_ips)
            for field in array_ip_fields:
                try:
                    # Use aggregation to unwind and get distinct IPs from arrays
                    pipeline = [
                        {"$match": {field: {"$exists": True, "$ne": None, "$ne": []}}},
                        {"$unwind": f"${field}"},
                        {"$group": {"_id": f"${field}"}}
                    ]
                    async for doc in database.clicks.aggregate(pipeline):
                        ip = doc.get("_id")
                        if ip and ip != "unknown" and isinstance(ip, str):
                            extracted.add(ip)
                except Exception:
                    pass
        except Exception as e:
            if db_name:
                logger.warning(f"Error extracting IPs from {db_name}: {e}")
        return extracted
    
    # 1. Get ALL IPs from main_db.clicks
    try:
        main_ips = await extract_ips_from_db(db, "main_db")
        all_click_ips.update(main_ips)
    except Exception as e:
        logger.error(f"Error fetching IPs from main_db: {e}")
    
    # 2. Get ALL IPs from ALL user-specific databases
    try:
        db_names = await client.list_database_names()
        user_dbs = [name for name in db_names if name.startswith("trackmaster_user_")]
        
        for db_name in user_dbs[:20]:  # Process max 20 user databases
            try:
                user_db_instance = client[db_name]
                user_ips = await extract_ips_from_db(user_db_instance, db_name)
                all_click_ips.update(user_ips)
            except Exception as e:
                logger.warning(f"Error fetching IPs from {db_name}: {e}")
    except Exception as e:
        logger.warning(f"Could not list user databases: {e}")
    
    # Update cache
    _click_ips_cache["ips"] = all_click_ips
    _click_ips_cache["last_updated"] = current_time
    
    logger.info(f"Cached {len(all_click_ips)} unique IPs from all clicks (all IP fields)")
    return all_click_ips

app = FastAPI()

# Auto-detect environment and set API prefix accordingly
# DigitalOcean strips /api prefix, Emergent preview needs it
IS_DIGITALOCEAN = os.environ.get("DIGITALOCEAN_APP", "").lower() == "true"
api_prefix = "" if IS_DIGITALOCEAN else "/api"
api_router = APIRouter(prefix=api_prefix)

# Health check endpoint (no prefix needed)
@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "admin_email_configured": ADMIN_EMAIL,
        "mongo_connected": bool(mongo_url)
    }

# Debug endpoint to search for a specific IP in ALL databases
@app.get("/debug-search-ip/{ip}")
@app.get("/api/debug-search-ip/{ip}")
async def debug_search_ip(ip: str):
    """Search for an IP in ALL databases - for debugging duplicate issues"""
    results = {
        "searched_ip": ip,
        "found_in": [],
        "total_found": 0
    }
    
    ip_conditions = [
        {"ip_address": ip},
        {"ipv4": ip},
        {"ipv4": ip},
        {"detected_ip": ip},
        {"all_ips": ip},
        {"proxy_ips": ip}
    ]
    duplicate_query = {"$or": ip_conditions}
    
    # Check main database
    try:
        count = await db.clicks.count_documents(duplicate_query)
        if count > 0:
            results["found_in"].append({"database": "main_db", "count": count})
            results["total_found"] += count
    except Exception as e:
        results["found_in"].append({"database": "main_db", "error": str(e)})
    
    # Check ALL user databases
    try:
        all_db_names = await client.list_database_names()
        user_databases = [name for name in all_db_names if name.startswith("trackmaster_user_")]
        
        for db_name in user_databases:
            try:
                user_db_instance = client[db_name]
                count = await user_db_instance.clicks.count_documents(duplicate_query)
                if count > 0:
                    results["found_in"].append({"database": db_name, "count": count})
                    results["total_found"] += count
            except:
                continue
    except Exception as e:
        results["error"] = str(e)
    
    return results

# Debug endpoint to see what IPs the server detects from your request
@app.get("/debug-ip")
@app.get("/api/debug-ip")
async def debug_ip(request: Request):
    """Debug endpoint to see all IPs detected from your request"""
    client_ips = get_all_client_ips(request)
    
    # Get all click IPs from database for comparison
    all_db_ips = await get_all_click_ips_from_entire_database()
    
    # Check which of your IPs are in the database
    your_ips_in_db = []
    your_ips_not_in_db = []
    
    all_your_ips = set()
    if client_ips["primary"]:
        all_your_ips.add(client_ips["primary"])
    if client_ips["ipv4"]:
        all_your_ips.add(client_ips["ipv4"])
    for ip in client_ips["all"]:
        all_your_ips.add(ip)
    for ip in client_ips["proxy_ips"]:
        all_your_ips.add(ip)
    
    for ip in all_your_ips:
        if ip in all_db_ips:
            your_ips_in_db.append(ip)
        else:
            your_ips_not_in_db.append(ip)
    
    return {
        "message": "These are ALL IPs the server sees from your request (IPv4 ONLY)",
        "your_detected_ips": {
            "primary_ip": client_ips["primary"],
            "ipv4": client_ips["ipv4"],
            "all_ips": client_ips["all"],
            "proxy_intermediate_ips": client_ips["proxy_ips"]
        },
        "headers": {
            "X-Forwarded-For": request.headers.get("X-Forwarded-For"),
            "X-Real-IP": request.headers.get("X-Real-IP"),
            "CF-Connecting-IP": request.headers.get("CF-Connecting-IP")
        },
        "database_check": {
            "your_ips_already_in_database": your_ips_in_db,
            "your_ips_NOT_in_database": your_ips_not_in_db,
            "would_be_blocked": len(your_ips_in_db) > 0
        },
        "total_ips_in_database": len(all_db_ips)
    }

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 7 * 24 * 60
POSTBACK_TOKEN = os.environ.get("POSTBACK_TOKEN", "secure-postback-token-123")

# Admin configuration
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@trackmaster.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

# Email configuration - Gmail SMTP (primary) or Resend (fallback)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")

# Use the frontend URL for reset links - check environment variable first, then frontend .env
APP_URL = os.environ.get("APP_URL", "")
if not APP_URL:
    try:
        frontend_env_path = ROOT_DIR.parent / 'frontend' / '.env'
        if frontend_env_path.exists():
            with open(frontend_env_path) as f:
                for line in f:
                    if line.startswith('REACT_APP_BACKEND_URL='):
                        APP_URL = line.strip().split('=', 1)[1].strip('"\'')
                        break
    except Exception:
        pass

# Ensure APP_URL has a value - use the request origin if still empty (handled dynamically in endpoints)

# Setup logger early
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Initialize email service
if SMTP_USER and SMTP_PASSWORD:
    logger.info(f"Gmail SMTP configured for {SMTP_USER}")
elif RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY
    logger.info("Resend email service configured")
else:
    logger.warning("No email service configured - emails will be logged only")
ADMIN_CONTACT_EMAIL = "admin@trackmaster.local"

# Email sending helper function
async def send_password_reset_email(to_email: str, user_name: str, reset_token: str, user_type: str = "user"):
    """Send password reset email using Gmail SMTP (primary) or Resend (fallback)"""
    reset_url = f"{APP_URL}/reset-password?token={reset_token}"
    
    # Get branding settings
    branding_doc = await main_db.settings.find_one({"key": "branding"})
    branding = branding_doc.get("value", DEFAULT_BRANDING) if branding_doc else DEFAULT_BRANDING
    
    app_name = branding.get("app_name", "TrackMaster")
    tagline = branding.get("tagline", "Traffic Tracking & Link Management")
    primary_color = branding.get("primary_color", "#3B82F6")
    logo_url = branding.get("logo_url", "")
    footer_text = branding.get("footer_text", f"© 2026 {app_name}. All rights reserved.")
    
    # Logo HTML - show image if logo_url exists, otherwise show app name as text
    logo_html = f'<img src="{logo_url}" alt="{app_name}" style="max-height: 50px; max-width: 200px;">' if logo_url else f'<h1 style="color: #FFFFFF; margin: 0 0 10px 0; font-size: 28px;">{app_name}</h1>'
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="margin: 0; padding: 0; font-family: Arial, sans-serif; background-color: #09090B;">
        <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #09090B; padding: 40px 20px;">
            <tr>
                <td align="center">
                    <table width="100%" max-width="600" cellpadding="0" cellspacing="0" style="background-color: #18181B; border-radius: 12px; border: 1px solid #27272A;">
                        <tr>
                            <td style="padding: 40px 30px; text-align: center;">
                                {logo_html}
                                <p style="color: #A1A1AA; margin: 10px 0 0 0; font-size: 14px;">{tagline}</p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 0 30px 30px 30px;">
                                <h2 style="color: #FFFFFF; margin: 0 0 20px 0; font-size: 20px;">Password Reset Request</h2>
                                <p style="color: #A1A1AA; margin: 0 0 20px 0; font-size: 14px; line-height: 1.6;">
                                    Hi {user_name},
                                </p>
                                <p style="color: #A1A1AA; margin: 0 0 30px 0; font-size: 14px; line-height: 1.6;">
                                    We received a request to reset your password for your {user_type} account. Click the button below to create a new password:
                                </p>
                                <table width="100%" cellpadding="0" cellspacing="0">
                                    <tr>
                                        <td align="center" style="padding: 20px 0;">
                                            <a href="{reset_url}" style="display: inline-block; background-color: {primary_color}; color: #FFFFFF; text-decoration: none; padding: 14px 40px; border-radius: 8px; font-size: 16px; font-weight: bold;">
                                                Reset Password
                                            </a>
                                        </td>
                                    </tr>
                                </table>
                                <p style="color: #71717A; margin: 30px 0 0 0; font-size: 12px; line-height: 1.6;">
                                    This link will expire in <strong style="color: #F59E0B;">1 hour</strong>. If you didn't request this, you can safely ignore this email.
                                </p>
                                <p style="color: #71717A; margin: 20px 0 0 0; font-size: 12px; line-height: 1.6;">
                                    If the button doesn't work, copy and paste this URL into your browser:<br>
                                    <span style="color: {primary_color}; word-break: break-all;">{reset_url}</span>
                                </p>
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 20px 30px; border-top: 1px solid #27272A; text-align: center;">
                                <p style="color: #52525B; margin: 0; font-size: 12px;">
                                    {footer_text}
                                </p>
                            </td>
                        </tr>
                    </table>
                </td>
            </tr>
        </table>
    </body>
    </html>
    """
    
    email_subject = f"Reset Your {app_name} Password"
    
    # Try Gmail SMTP first (primary)
    if SMTP_USER and SMTP_PASSWORD:
        try:
            def send_smtp_email():
                msg = MIMEMultipart('alternative')
                msg['Subject'] = email_subject
                msg['From'] = f"{app_name} <{SMTP_USER}>"
                msg['To'] = to_email
                
                # Attach HTML content
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)
                
                # Connect to Gmail SMTP
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                    server.starttls()
                    server.login(SMTP_USER, SMTP_PASSWORD)
                    server.sendmail(SMTP_USER, to_email, msg.as_string())
                
                return True
            
            # Run sync SMTP in thread to keep FastAPI non-blocking
            await asyncio.to_thread(send_smtp_email)
            logger.info(f"Password reset email sent via Gmail SMTP to {to_email}")
            return {"status": "sent", "message": "Email sent successfully via Gmail"}
        except Exception as e:
            logger.error(f"Gmail SMTP failed for {to_email}: {str(e)}")
            # Fall through to try Resend
    
    # Try Resend as fallback
    if RESEND_API_KEY:
        try:
            params = {
                "from": SENDER_EMAIL,
                "to": [to_email],
                "subject": email_subject,
                "html": html_content
            }
            
            # Run sync SDK in thread to keep FastAPI non-blocking
            email_response = await asyncio.to_thread(resend.Emails.send, params)
            logger.info(f"Password reset email sent via Resend to {to_email}, ID: {email_response.get('id')}")
            return {"status": "sent", "message": "Email sent successfully via Resend", "email_id": email_response.get("id")}
        except Exception as e:
            logger.error(f"Resend failed for {to_email}: {str(e)}")
            return {"status": "error", "message": str(e)}
    
    # No email service configured - log only
    logger.info(f"[EMAIL DEMO] Password reset email would be sent to {to_email}")
    logger.info(f"[EMAIL DEMO] Reset URL: {reset_url}")
    return {"status": "demo", "message": "Email logged (no email service configured)", "reset_url": reset_url}

# WebSocket connection manager for real-time updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(websocket)
    
    def disconnect(self, websocket: WebSocket, user_id: str):
        if user_id in self.active_connections:
            if websocket in self.active_connections[user_id]:
                self.active_connections[user_id].remove(websocket)
    
    async def send_to_user(self, user_id: str, message: dict):
        if user_id in self.active_connections:
            for connection in self.active_connections[user_id]:
                try:
                    await connection.send_json(message)
                except:
                    pass
    
    async def broadcast_click(self, user_id: str, click_data: dict):
        await self.send_to_user(user_id, {"type": "new_click", "data": click_data})

manager = ConnectionManager()

# Default feature permissions for new users
DEFAULT_FEATURES = {
    "links": False,
    "clicks": False,
    "conversions": False,
    "proxies": False,
    "import_data": False,
    # Granular sub-features (previously gated under import_data)
    "import_traffic": False,
    "real_traffic": False,
    "ua_generator": False,
    "email_checker": False,
    "separate_data": False,
    "form_filler": False,
    "real_user_traffic": False,
    "settings": True,  # Settings access - default ON for main users
    "max_links": 0,
    "max_clicks": 0,
    "max_sub_users": 0
}

# Default branding settings
DEFAULT_BRANDING = {
    "app_name": "TrackMaster",
    "tagline": "Traffic Tracking & Link Management System",
    "logo_url": "",
    "favicon_url": "",
    "primary_color": "#3B82F6",
    "secondary_color": "#22C55E",
    "accent_color": "#8B5CF6",
    "danger_color": "#EF4444",
    "warning_color": "#F59E0B",
    "success_color": "#22C55E",
    "background_color": "#09090B",
    "card_color": "#18181B",
    "border_color": "#27272A",
    "text_color": "#FAFAFA",
    "muted_color": "#A1A1AA",
    "login_bg_url": "",
    "admin_email": "admin@trackmaster.local",
    "footer_text": "© 2026 TrackMaster. All rights reserved.",
    "sidebar_style": "dark",
    "button_style": "rounded",
    "font_family": "Inter",
    "updated_at": None
}

class BrandingUpdate(BaseModel):
    app_name: Optional[str] = None
    tagline: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    primary_color: Optional[str] = None
    secondary_color: Optional[str] = None
    accent_color: Optional[str] = None
    danger_color: Optional[str] = None
    warning_color: Optional[str] = None
    success_color: Optional[str] = None
    background_color: Optional[str] = None
    card_color: Optional[str] = None
    border_color: Optional[str] = None
    text_color: Optional[str] = None
    muted_color: Optional[str] = None
    login_bg_url: Optional[str] = None
    admin_email: Optional[str] = None
    footer_text: Optional[str] = None
    sidebar_style: Optional[str] = None
    button_style: Optional[str] = None
    font_family: Optional[str] = None

# Default API settings for VPN detection services
DEFAULT_API_SETTINGS = {
    "proxycheck": {
        "name": "ProxyCheck.io",
        "enabled": True,
        "api_key": "",
        "endpoint": "http://proxycheck.io/v2/",
        "priority": 1,
        "description": "VPN/Proxy detection service (free tier available)"
    },
    "ipapi": {
        "name": "IP-API.com",
        "enabled": True,
        "api_key": "",
        "endpoint": "http://ip-api.com/json/",
        "priority": 2,
        "description": "Geolocation and proxy detection (free tier available)"
    },
    "scamalytics": {
        "name": "Scamalytics",
        "enabled": False,
        "api_key": "",
        "endpoint": "https://scamalytics.com/ip/",
        "priority": 3,
        "description": "Fraud score detection (requires API key)"
    },
    "ipqualityscore": {
        "name": "IPQualityScore",
        "enabled": False,
        "api_key": "",
        "endpoint": "https://ipqualityscore.com/api/json/ip/",
        "priority": 4,
        "description": "Advanced fraud detection (requires API key)"
    },
    "iphub": {
        "name": "IPHub",
        "enabled": False,
        "api_key": "",
        "endpoint": "http://v2.api.iphub.info/ip/",
        "priority": 5,
        "description": "IP intelligence service (requires API key)"
    }
}

class APISettingUpdate(BaseModel):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None
    priority: Optional[int] = None
    description: Optional[str] = None

class CustomAPICreate(BaseModel):
    key: str  # unique identifier like "custom_vpn_1"
    name: str
    enabled: bool = True
    api_key: str = ""
    endpoint: str
    priority: int = 10
    description: str = ""

class UserCreate(BaseModel):
    email: str
    password: str
    name: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: dict

class AdminLogin(BaseModel):
    email: str
    password: str

class AdminToken(BaseModel):
    access_token: str
    token_type: str
    is_admin: bool = True

class UserFeatures(BaseModel):
    # Allow the admin UI to send granular feature keys (import_traffic,
    # real_traffic, ua_generator, email_checker, separate_data, etc.)
    # without them being silently stripped by Pydantic.
    model_config = ConfigDict(extra="allow")

    links: bool = False
    clicks: bool = False
    conversions: bool = False
    proxies: bool = False
    import_data: bool = False
    # Granular sub-features
    import_traffic: bool = False
    real_traffic: bool = False
    ua_generator: bool = False
    email_checker: bool = False
    separate_data: bool = False
    form_filler: bool = False
    real_user_traffic: bool = False
    settings: bool = True  # Settings access - default True for main users
    max_links: int = 0
    max_clicks: int = 0
    max_sub_users: int = 0  # How many sub-users this user can create

class UserUpdate(BaseModel):
    status: Optional[str] = None  # active, blocked, pending
    features: Optional[UserFeatures] = None
    subscription_note: Optional[str] = None
    email: Optional[str] = None  # Admin can edit email
    password: Optional[str] = None  # Admin can edit password
    subscription_type: Optional[str] = None  # free, monthly, yearly
    subscription_expires: Optional[str] = None  # ISO date string
    max_sub_users: Optional[int] = None  # Direct update for max sub-users

class UserProfileUpdate(BaseModel):
    name: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None

class SubUserCreate(BaseModel):
    email: str
    password: str
    name: str
    permissions: dict = {}  # e.g., {"view_clicks": True, "view_links": True}

class SubUserUpdate(BaseModel):
    name: Optional[str] = None
    password: Optional[str] = None
    permissions: Optional[dict] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    status: str = "pending"
    features: dict = {}
    subscription_note: Optional[str] = None
    subscription_type: Optional[str] = None
    subscription_expires: Optional[str] = None
    parent_user_id: Optional[str] = None  # For sub-users
    sub_user_count: int = 0  # Number of sub-users this user has
    created_at: str

class SubUserResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: str
    name: str
    permissions: dict = {}
    is_active: bool = True
    last_active: Optional[str] = None
    created_at: str

class IPListImport(BaseModel):
    link_id: Optional[str] = None  # Optional - can import without link
    ip_list: List[str]
    country: str = "Unknown"

class LinkCreate(BaseModel):
    offer_url: str
    status: str = "active"
    name: Optional[str] = None
    custom_short_code: Optional[str] = None
    allowed_countries: Optional[List[str]] = None  # Empty = all countries allowed
    allowed_os: Optional[List[str]] = None  # Empty = all OS allowed (iOS, Android, Windows, macOS, Linux)
    block_vpn: bool = False
    duplicate_timer_enabled: bool = False  # Enable/disable duplicate IP timer
    duplicate_timer_seconds: int = 5  # Seconds before duplicate IP is allowed again
    forced_source: Optional[str] = None  # Force traffic source (facebook, google, whatsapp, etc.)
    forced_source_name: Optional[str] = None  # Display name for the forced source
    # Referrer control options
    referrer_mode: str = "normal"  # normal, no_referrer, with_params
    url_params: Optional[dict] = None  # Custom URL parameters to add to offer URL
    simulate_platform: Optional[str] = None  # facebook, tiktok, instagram, google, etc.

class LinkUpdate(BaseModel):
    offer_url: Optional[str] = None
    status: Optional[str] = None
    name: Optional[str] = None
    allowed_countries: Optional[List[str]] = None
    allowed_os: Optional[List[str]] = None
    block_vpn: Optional[bool] = None
    custom_short_code: Optional[str] = None  # Allow updating short code
    duplicate_timer_enabled: Optional[bool] = None
    duplicate_timer_seconds: Optional[int] = None
    forced_source: Optional[str] = None  # Force traffic source
    forced_source_name: Optional[str] = None  # Display name for the forced source
    referrer_mode: Optional[str] = None
    url_params: Optional[dict] = None
    simulate_platform: Optional[str] = None

class LinkResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    short_code: str
    offer_url: str
    status: str
    name: Optional[str] = None
    allowed_countries: Optional[List[str]] = None
    allowed_os: Optional[List[str]] = None
    block_vpn: bool = False
    duplicate_timer_enabled: bool = False
    duplicate_timer_seconds: int = 5
    forced_source: Optional[str] = None
    forced_source_name: Optional[str] = None
    referrer_mode: str = "normal"
    url_params: Optional[dict] = None
    simulate_platform: Optional[str] = None
    clicks: int = 0
    conversions: int = 0
    revenue: float = 0.0
    created_at: str

class ClickResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    click_id: str
    link_id: str
    ip_address: str
    ipv4: Optional[str] = None
    all_ips: Optional[List[str]] = None
    proxy_ips: Optional[List[str]] = None
    country: str
    city: Optional[str] = None
    region: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    isp: Optional[str] = None
    is_vpn: bool = False
    is_proxy: bool = False
    vpn_score: Optional[int] = None
    user_agent: str
    user_agent_raw: Optional[str] = None
    referrer: str
    referrer_source: Optional[str] = None
    referrer_source_name: Optional[str] = None
    referrer_detected_from: Optional[str] = None
    device: str
    device_type: Optional[str] = None
    device_brand: Optional[str] = None
    device_model: Optional[str] = None
    device_display: Optional[str] = None
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    browser: Optional[str] = None
    browser_version: Optional[str] = None
    browser_display: Optional[str] = None
    url_params: Optional[dict] = None
    sub1: Optional[str] = None
    sub2: Optional[str] = None
    sub3: Optional[str] = None
    created_at: str

class ConversionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    click_id: str
    link_id: str
    payout: float
    status: str
    ip_address: str
    created_at: str

class ProxyUpload(BaseModel):
    proxy_list: List[str]
    proxy_type: str = "http"

class ProxyResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    proxy_string: str
    proxy_ip: Optional[str] = None
    proxy_type: str
    status: str
    response_time: Optional[float] = None
    detected_ip: Optional[str] = None
    all_detected_ips: Optional[List[str]] = None
    is_duplicate: Optional[bool] = False
    is_duplicate_proxy: Optional[bool] = False
    is_duplicate_click: Optional[bool] = False
    duplicate_matched_ip: Optional[str] = None
    is_vpn: Optional[bool] = False
    vpn_score: Optional[int] = None
    last_checked: str

class OfferCreate(BaseModel):
    link_id: str
    offer_url: str
    weight: int = 50

class DashboardStats(BaseModel):
    total_clicks: int
    unique_clicks: int
    total_conversions: int
    conversion_rate: float
    revenue: float
    epc: float
    clicks_by_country: List[dict]
    clicks_by_device: List[dict]
    clicks_by_date: List[dict]
    revenue_by_date: List[dict]

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(request: Request):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        is_sub_user: bool = payload.get("is_sub_user", False)
        parent_user_id: str = payload.get("parent_user_id")
        if email is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    if is_sub_user:
        # Handle sub-user authentication
        sub_user = await db.sub_users.find_one({"email": email}, {"_id": 0})
        if sub_user is None:
            raise HTTPException(status_code=401, detail="Sub-user not found")
        
        # Get parent user for features
        parent_user = await db.users.find_one({"id": parent_user_id}, {"_id": 0})
        if not parent_user or parent_user.get("status") != "active":
            raise HTTPException(status_code=403, detail="Parent account is not active")
        
        # Return sub-user with mapped features
        return {
            "id": parent_user_id,  # Use parent's ID for database access
            "sub_user_id": sub_user["id"],
            "email": sub_user["email"],
            "name": sub_user["name"],
            "is_sub_user": True,
            "parent_user_id": parent_user_id,
            "status": parent_user.get("status", "active"),
            "permissions": sub_user.get("permissions", {}),
            "features": {
                "links": sub_user.get("permissions", {}).get("view_links", True),
                "clicks": sub_user.get("permissions", {}).get("view_clicks", True),
                "conversions": sub_user.get("permissions", {}).get("view_conversions", False),
                "proxies": sub_user.get("permissions", {}).get("view_proxies", False),
                "import_data": sub_user.get("permissions", {}).get("import_data", False),
                "max_links": parent_user.get("features", {}).get("max_links", 100),
                "max_clicks": parent_user.get("features", {}).get("max_clicks", 100000),
                "max_sub_users": 0
            }
        }
    
    # Handle main user authentication
    user = await db.users.find_one({"email": email}, {"_id": 0})
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user

def generate_short_code():
    return str(uuid.uuid4())[:8]

def validate_short_code(short_code: str) -> bool:
    """Validate custom short code format"""
    import re
    if len(short_code) < 3 or len(short_code) > 50:
        return False
    pattern = re.compile(r'^[a-zA-Z0-9-_]+$')
    return bool(pattern.match(short_code))

def normalize_country(country: str) -> str:
    """Normalize country names and codes"""
    country_map = {
        "USA": "United States",
        "US": "United States",
        "UK": "United Kingdom",
        "UAE": "United Arab Emirates",
        "CA": "Canada",
        "AU": "Australia",
        "NZ": "New Zealand",
        "IN": "India",
        "PK": "Pakistan",
        "BD": "Bangladesh",
        "BR": "Brazil",
        "MX": "Mexico",
        "AR": "Argentina",
        "DE": "Germany",
        "FR": "France",
        "IT": "Italy",
        "ES": "Spain",
        "NL": "Netherlands",
        "BE": "Belgium",
        "CH": "Switzerland",
        "AT": "Austria",
        "SE": "Sweden",
        "NO": "Norway",
        "DK": "Denmark",
        "FI": "Finland",
        "PL": "Poland",
        "RO": "Romania",
        "GR": "Greece",
        "PT": "Portugal",
        "CZ": "Czech Republic",
        "HU": "Hungary",
        "JP": "Japan",
        "CN": "China",
        "KR": "South Korea",
        "TH": "Thailand",
        "VN": "Vietnam",
        "PH": "Philippines",
        "ID": "Indonesia",
        "MY": "Malaysia",
        "SG": "Singapore",
        "ZA": "South Africa",
        "NG": "Nigeria",
        "EG": "Egypt",
        "KE": "Kenya",
        "IL": "Israel",
        "SA": "Saudi Arabia",
        "TR": "Turkey",
        "RU": "Russia"
    }
    
    country = country.strip()
    if country.upper() in country_map:
        return country_map[country.upper()]
    return country

def get_client_ip(request: Request) -> str:
    """Get the real client IP from request headers"""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
        if not ip.startswith("10.") and not ip.startswith("172.") and not ip.startswith("192.168."):
            return ip
    
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()
    
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()
    
    true_client_ip = request.headers.get("True-Client-IP")
    if true_client_ip:
        return true_client_ip.strip()
    
    return request.client.host

def is_ipv6(ip: str) -> bool:
    """Check if IP address is IPv6"""
    return ":" in ip

def is_ipv4(ip: str) -> bool:
    """Check if IP address is IPv4"""
    parts = ip.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)

def normalize_ipv6(ip: str) -> str:
    """Normalize IPv6 address to full format for consistent comparison"""
    if not is_ipv6(ip):
        return ip
    try:
        import ipaddress
        return str(ipaddress.ip_address(ip))
    except:
        return ip

def get_all_client_ips(request: Request) -> dict:
    """Get all possible client IPs (IPv4 ONLY) from request headers.
    
    IMPORTANT: Only returns the REAL client IP, ignores infrastructure/proxy IPs
    to prevent false duplicate detection.
    """
    ips = {"primary": None, "ipv4": None, "all": [], "proxy_ips": []}
    
    # Known infrastructure IP prefixes to IGNORE
    # These are ONLY load balancers/CDN proxies - NOT private network IPs
    # Private IPs (10.x, 172.x, 192.168.x) are ALLOWED for local testing
    INFRA_IP_PREFIXES = (
        "172.69.", "172.70.", "172.71.",  # Cloudflare proxies ONLY
        "34.160.",  # Google Cloud internal load balancers
        "35.191.", "35.186.",  # Google Cloud health checks
        "130.211.",  # Google Cloud
    )
    
    def is_infra_ip(ip: str) -> bool:
        """Check if IP is an infrastructure/proxy IP that should be ignored"""
        if not ip:
            return True
        return ip.startswith(INFRA_IP_PREFIXES)
    
    def is_private_ip(ip: str) -> bool:
        """We ALLOW private IPs for local/Docker testing"""
        # Return False to allow ALL IPs including 172.25.160.1
        return False
    
    # Get all IPs from X-Forwarded-For
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        all_forwarded_ips = [ip.strip() for ip in forwarded.split(",")]
        
        # First IP is the original client - ONLY IPv4, skip private IPs
        if all_forwarded_ips:
            first_ip = all_forwarded_ips[0]
            if first_ip and is_ipv4(first_ip) and not is_private_ip(first_ip):
                ips["all"].append(first_ip)
                ips["ipv4"] = first_ip
        
        # We NO LONGER store proxy/intermediate IPs as they cause false duplicates
    
    # Check CF-Connecting-IP (Cloudflare real IP) - this is more reliable
    cf_ip = request.headers.get("CF-Connecting-IP")
    if cf_ip:
        ip = cf_ip.strip()
        if ip and is_ipv4(ip) and not is_private_ip(ip):
            if not ips["ipv4"]:
                ips["all"].append(ip)
                ips["ipv4"] = ip
            elif ip not in ips["all"]:
                # CF IP might be different, use it as primary if we don't have one
                pass
    
    # Fallback if no client IP found - ONLY IPv4
    if not ips["all"]:
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            ip = real_ip.strip()
            if ip and is_ipv4(ip) and not is_private_ip(ip):
                ips["all"].append(ip)
                ips["ipv4"] = ip
    
    if not ips["all"] and request.client and request.client.host:
        ip = request.client.host
        if is_ipv4(ip) and not is_private_ip(ip):
            ips["all"].append(ip)
            ips["ipv4"] = ip
    
    # Set primary IP - ONLY IPv4
    ips["primary"] = ips["ipv4"] or (ips["all"][0] if ips["all"] else "unknown")
    
    # proxy_ips is now empty - we don't track infrastructure IPs anymore
    ips["proxy_ips"] = []
    
    return ips

# Referrer Source Categorization
REFERRER_PATTERNS = {
    "facebook": ["facebook.com", "fb.com", "fb.me", "m.facebook.com", "l.facebook.com", "lm.facebook.com"],
    "instagram": ["instagram.com", "l.instagram.com"],
    "twitter": ["twitter.com", "t.co", "x.com"],
    "pinterest": ["pinterest.com", "pin.it"],
    "linkedin": ["linkedin.com", "lnkd.in"],
    "youtube": ["youtube.com", "youtu.be"],
    "tiktok": ["tiktok.com", "vm.tiktok.com"],
    "snapchat": ["snapchat.com"],
    "reddit": ["reddit.com", "redd.it"],
    "whatsapp": ["whatsapp.com", "wa.me", "api.whatsapp.com"],
    "telegram": ["telegram.org", "t.me", "telegram.me"],
    "google": ["google.com", "google.co", "www.google"],
    "bing": ["bing.com"],
    "yahoo": ["yahoo.com", "search.yahoo"],
    "duckduckgo": ["duckduckgo.com"],
    "gmail": ["mail.google.com", "gmail.com"],
    "outlook": ["outlook.com", "outlook.live.com", "mail.live.com"],
    "discord": ["discord.com", "discord.gg", "discordapp.com"],
    "twitch": ["twitch.tv"],
    "spotify": ["spotify.com"],
}

def categorize_referrer(referrer: str, url_params: dict = None) -> dict:
    """Categorize referrer URL into source type. Also checks URL parameters for click IDs."""
    
    # Source names mapping
    source_names = {
        "facebook": "Facebook",
        "instagram": "Instagram", 
        "twitter": "Twitter/X",
        "pinterest": "Pinterest",
        "linkedin": "LinkedIn",
        "youtube": "YouTube",
        "tiktok": "TikTok",
        "snapchat": "Snapchat",
        "reddit": "Reddit",
        "whatsapp": "WhatsApp",
        "telegram": "Telegram",
        "google": "Google Search",
        "bing": "Bing Search",
        "yahoo": "Yahoo Search",
        "duckduckgo": "DuckDuckGo",
        "gmail": "Gmail",
        "outlook": "Outlook/Hotmail",
        "discord": "Discord",
        "twitch": "Twitch",
        "spotify": "Spotify"
    }
    
    # First check URL parameters for platform-specific click IDs
    # This is more reliable than referrer header (which apps often strip)
    if url_params:
        # Instagram - igshid parameter
        if url_params.get("igshid") or url_params.get("utm_source", "").lower() == "instagram":
            return {"source": "instagram", "source_name": "Instagram", "domain": "instagram.com", "detected_from": "url_params"}
        
        # Facebook - fbclid parameter
        if url_params.get("fbclid") or url_params.get("utm_source", "").lower() == "facebook":
            return {"source": "facebook", "source_name": "Facebook", "domain": "facebook.com", "detected_from": "url_params"}
        
        # TikTok - ttclid parameter
        if url_params.get("ttclid") or url_params.get("utm_source", "").lower() == "tiktok":
            return {"source": "tiktok", "source_name": "TikTok", "domain": "tiktok.com", "detected_from": "url_params"}
        
        # Twitter/X - twclid parameter
        if url_params.get("twclid") or url_params.get("utm_source", "").lower() in ["twitter", "x"]:
            return {"source": "twitter", "source_name": "Twitter/X", "domain": "twitter.com", "detected_from": "url_params"}
        
        # Google - gclid parameter  
        if url_params.get("gclid") or url_params.get("utm_source", "").lower() == "google":
            return {"source": "google", "source_name": "Google", "domain": "google.com", "detected_from": "url_params"}
        
        # Pinterest - epik parameter
        if url_params.get("epik") or url_params.get("utm_source", "").lower() == "pinterest":
            return {"source": "pinterest", "source_name": "Pinterest", "domain": "pinterest.com", "detected_from": "url_params"}
        
        # LinkedIn - li_fat_id parameter
        if url_params.get("li_fat_id") or url_params.get("utm_source", "").lower() == "linkedin":
            return {"source": "linkedin", "source_name": "LinkedIn", "domain": "linkedin.com", "detected_from": "url_params"}
        
        # Snapchat - sccid parameter
        if url_params.get("sccid") or url_params.get("utm_source", "").lower() == "snapchat":
            return {"source": "snapchat", "source_name": "Snapchat", "domain": "snapchat.com", "detected_from": "url_params"}
        
        # YouTube
        if url_params.get("utm_source", "").lower() == "youtube":
            return {"source": "youtube", "source_name": "YouTube", "domain": "youtube.com", "detected_from": "url_params"}
        
        # WhatsApp
        if url_params.get("utm_source", "").lower() == "whatsapp":
            return {"source": "whatsapp", "source_name": "WhatsApp", "domain": "whatsapp.com", "detected_from": "url_params"}
        
        # Telegram
        if url_params.get("utm_source", "").lower() == "telegram":
            return {"source": "telegram", "source_name": "Telegram", "domain": "telegram.org", "detected_from": "url_params"}
        
        # Generic utm_source fallback
        utm_source = url_params.get("utm_source", "").lower()
        if utm_source and utm_source in source_names:
            return {"source": utm_source, "source_name": source_names[utm_source], "domain": f"{utm_source}.com", "detected_from": "url_params"}
    
    # If no URL params match, check referrer header
    if not referrer or referrer.strip() == "":
        return {"source": "direct", "source_name": "Direct", "domain": None, "detected_from": "none"}
    
    referrer = referrer.lower().strip()
    
    # Extract domain from referrer
    try:
        from urllib.parse import urlparse
        parsed = urlparse(referrer)
        domain = parsed.netloc or parsed.path.split('/')[0]
        domain = domain.replace("www.", "")
    except:
        domain = referrer
    
    # Check against known patterns
    for source, patterns in REFERRER_PATTERNS.items():
        for pattern in patterns:
            if pattern in referrer or pattern in domain:
                return {
                    "source": source,
                    "source_name": source_names.get(source, source.title()),
                    "domain": domain,
                    "detected_from": "referrer"
                }
    
    # If no match, categorize as "other" with the domain
    return {"source": "other", "source_name": "Other", "domain": domain, "detected_from": "referrer"}

def generate_platform_params(platform: str, custom_params: dict = None) -> dict:
    """Generate platform-specific URL parameters to simulate traffic source"""
    import random
    import string
    
    def random_id(length=20):
        return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
    
    def random_numeric(length=15):
        return ''.join(random.choices(string.digits, k=length))
    
    params = {}
    
    if platform == "facebook":
        # Facebook Click ID - looks like: IwAR3xyzabc123...
        params["fbclid"] = f"IwAR{random_id(30)}"
        params["utm_source"] = "facebook"
        params["utm_medium"] = "social"
        params["utm_campaign"] = "fb_ads"
    
    elif platform == "instagram":
        params["igshid"] = random_id(22)
        params["utm_source"] = "instagram"
        params["utm_medium"] = "social"
    
    elif platform == "tiktok":
        # TikTok Click ID
        params["ttclid"] = random_id(32)
        params["utm_source"] = "tiktok"
        params["utm_medium"] = "social"
    
    elif platform == "twitter":
        params["twclid"] = random_id(24)
        params["utm_source"] = "twitter"
        params["utm_medium"] = "social"
    
    elif platform == "google":
        # Google Click ID (gclid)
        params["gclid"] = f"Cj0KCQj{random_id(40)}"
        params["utm_source"] = "google"
        params["utm_medium"] = "cpc"
    
    elif platform == "youtube":
        params["utm_source"] = "youtube"
        params["utm_medium"] = "video"
        params["utm_campaign"] = "youtube_traffic"
    
    elif platform == "pinterest":
        params["epik"] = random_id(30)
        params["utm_source"] = "pinterest"
        params["utm_medium"] = "social"
    
    elif platform == "linkedin":
        params["li_fat_id"] = random_id(36)
        params["utm_source"] = "linkedin"
        params["utm_medium"] = "social"
    
    elif platform == "whatsapp":
        params["utm_source"] = "whatsapp"
        params["utm_medium"] = "social"
        params["utm_campaign"] = "whatsapp_share"
    
    elif platform == "telegram":
        params["utm_source"] = "telegram"
        params["utm_medium"] = "social"
    
    elif platform == "snapchat":
        params["sccid"] = random_id(28)
        params["utm_source"] = "snapchat"
        params["utm_medium"] = "social"
    
    elif platform == "reddit":
        params["utm_source"] = "reddit"
        params["utm_medium"] = "social"
        params["utm_campaign"] = "reddit_post"
    
    elif platform == "email":
        params["utm_source"] = "email"
        params["utm_medium"] = "email"
        params["utm_campaign"] = "newsletter"
    
    elif platform == "sms":
        params["utm_source"] = "sms"
        params["utm_medium"] = "sms"
    
    elif platform == "direct":
        # No params for direct traffic
        pass
    
    else:
        # Custom platform
        params["utm_source"] = platform
        params["utm_medium"] = "referral"
    
    # Add custom params if provided
    if custom_params:
        params.update(custom_params)
    
    return params

def build_redirect_url(base_url: str, params: dict) -> str:
    """Build redirect URL with added parameters"""
    from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
    
    if not params:
        return base_url
    
    parsed = urlparse(base_url)
    existing_params = parse_qs(parsed.query)
    
    # Flatten existing params (parse_qs returns lists)
    flat_params = {k: v[0] if isinstance(v, list) and len(v) == 1 else v for k, v in existing_params.items()}
    
    # Add new params (don't overwrite existing)
    for key, value in params.items():
        if key not in flat_params:
            flat_params[key] = value
    
    # Rebuild URL
    new_query = urlencode(flat_params, doseq=True)
    new_url = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        new_query,
        parsed.fragment
    ))
    
    return new_url

async def check_vpn_scamalytics(ip: str) -> dict:
    """Check IP against multiple services for VPN/proxy detection - with caching"""
    if not ip or ip in ["127.0.0.1", "localhost", "unknown", "Unknown", ""] or ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168."):
        return {"is_vpn": False, "vpn_score": 0, "risk": "low", "source": "local"}
    
    # Fresh VPN check every time - no cache
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://ip-api.com/json/{ip}?fields=proxy,hosting,status",
                timeout=2  # 2 second timeout for speed
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    is_vpn = data.get("proxy", False) or data.get("hosting", False)
                    return {
                        "is_vpn": is_vpn, 
                        "vpn_score": 100 if is_vpn else 0, 
                        "risk": "high" if is_vpn else "low", 
                        "source": "ip-api"
                    }
    except:
        pass
    
    return {"is_vpn": False, "vpn_score": 0, "risk": "unknown", "source": "none"}


# API Usage Tracker - tracks daily usage for each API
_api_usage = {}
_api_usage_date = None

# API Daily Limits (free tier)
API_DAILY_LIMITS = {
    "proxycheck": 1000,      # 1000/day free
    "ipapi": 45 * 60 * 24,   # 45/minute = ~64,800/day but we'll set 10000 as practical limit
    "scamalytics": 5000,     # Varies by plan
    "ipqualityscore": 5000,  # 5000/month free, ~166/day
    "iphub": 1000,           # 1000/day free
}

# Override practical limits
API_DAILY_LIMITS["ipapi"] = 10000  # Practical daily limit for ip-api

def get_today_date():
    """Get today's date string for tracking"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

async def get_api_usage():
    """Get API usage from database"""
    global _api_usage, _api_usage_date
    today = get_today_date()
    
    # Check if we need to load from database or reset for new day
    if _api_usage_date != today:
        # Load from database or reset
        usage_doc = await main_db.settings.find_one({"key": "api_usage"})
        if usage_doc and usage_doc.get("date") == today:
            _api_usage = usage_doc.get("usage", {})
        else:
            _api_usage = {}
            # Save reset to database
            await main_db.settings.update_one(
                {"key": "api_usage"},
                {"$set": {"key": "api_usage", "date": today, "usage": {}}},
                upsert=True
            )
        _api_usage_date = today
    
    return _api_usage

async def increment_api_usage(api_key: str):
    """Increment usage count for an API"""
    global _api_usage
    await get_api_usage()  # Ensure loaded
    
    if api_key not in _api_usage:
        _api_usage[api_key] = 0
    _api_usage[api_key] += 1
    
    # Save to database every 10 requests to reduce writes
    if _api_usage[api_key] % 10 == 0:
        await main_db.settings.update_one(
            {"key": "api_usage"},
            {"$set": {f"usage.{api_key}": _api_usage[api_key]}},
            upsert=True
        )

async def save_api_usage():
    """Force save API usage to database"""
    global _api_usage, _api_usage_date
    if _api_usage:
        await main_db.settings.update_one(
            {"key": "api_usage"},
            {"$set": {"key": "api_usage", "date": _api_usage_date or get_today_date(), "usage": _api_usage}},
            upsert=True
        )

def is_api_limit_reached(api_key: str) -> bool:
    """Check if API has reached its daily limit"""
    limit = API_DAILY_LIMITS.get(api_key, 10000)
    used = _api_usage.get(api_key, 0)
    return used >= limit

def get_api_remaining(api_key: str) -> int:
    """Get remaining requests for an API"""
    limit = API_DAILY_LIMITS.get(api_key, 10000)
    used = _api_usage.get(api_key, 0)
    return max(0, limit - used)

# API Rate Limit Tracker - tracks which APIs have hit their limits (for errors)
_api_rate_limits = {}
_api_rate_limit_reset = 3600  # Reset rate limit flags after 1 hour

async def get_enabled_api_settings():
    """Get API settings from database, sorted by priority"""
    try:
        settings = await main_db.settings.find_one({"key": "api_settings"})
        if settings and "value" in settings:
            api_settings = settings["value"]
        else:
            api_settings = DEFAULT_API_SETTINGS
        
        # Filter enabled APIs and sort by priority
        enabled_apis = [
            (key, config) for key, config in api_settings.items() 
            if config.get("enabled", False)
        ]
        enabled_apis.sort(key=lambda x: x[1].get("priority", 99))
        return enabled_apis
    except Exception as e:
        logger.error(f"Error getting API settings: {e}")
        return []

def is_api_rate_limited(api_key: str) -> bool:
    """Check if an API is currently rate limited"""
    global _api_rate_limits
    if api_key not in _api_rate_limits:
        return False
    
    limit_time = _api_rate_limits[api_key]
    if time.time() - limit_time > _api_rate_limit_reset:
        del _api_rate_limits[api_key]
        return False
    return True

def mark_api_rate_limited(api_key: str):
    """Mark an API as rate limited"""
    global _api_rate_limits
    _api_rate_limits[api_key] = time.time()
    logger.warning(f"API {api_key} marked as rate limited")

async def check_vpn_with_api(ip: str, api_key: str, config: dict) -> dict:
    """Check VPN using a specific API configuration"""
    try:
        async with httpx.AsyncClient() as client:
            if api_key == "ipapi":
                url = f"{config['endpoint']}{ip}?fields=proxy,hosting,status"
                response = await client.get(url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "fail" and "rate limit" in str(data.get("message", "")).lower():
                        mark_api_rate_limited(api_key)
                        return None
                    if data.get("status") == "success":
                        await increment_api_usage(api_key)  # Track usage
                        is_vpn = data.get("proxy", False) or data.get("hosting", False)
                        return {"is_vpn": is_vpn, "vpn_score": 100 if is_vpn else 0, "risk": "high" if is_vpn else "low", "source": api_key}
            
            elif api_key == "proxycheck":
                url = f"{config['endpoint']}{ip}?vpn=1"
                if config.get("api_key"):
                    url += f"&key={config['api_key']}"
                response = await client.get(url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "denied" or data.get("status") == "error":
                        if "limit" in str(data.get("message", "")).lower():
                            mark_api_rate_limited(api_key)
                        return None
                    await increment_api_usage(api_key)  # Track usage
                    ip_data = data.get(ip, {})
                    is_vpn = ip_data.get("proxy") == "yes" or ip_data.get("type") in ["VPN", "Proxy", "Hosting"]
                    return {"is_vpn": is_vpn, "vpn_score": 100 if is_vpn else 0, "risk": "high" if is_vpn else "low", "source": api_key}
            
            elif api_key == "ipqualityscore":
                if not config.get("api_key"):
                    return None
                url = f"{config['endpoint']}{config['api_key']}/{ip}"
                response = await client.get(url, timeout=3)
                if response.status_code == 200:
                    data = response.json()
                    if not data.get("success", True):
                        if "limit" in str(data.get("message", "")).lower():
                            mark_api_rate_limited(api_key)
                        return None
                    await increment_api_usage(api_key)  # Track usage
                    is_vpn = data.get("vpn", False) or data.get("proxy", False) or data.get("tor", False)
                    vpn_score = data.get("fraud_score", 0)
                    return {"is_vpn": is_vpn, "vpn_score": vpn_score, "risk": "high" if vpn_score > 75 else "medium" if vpn_score > 50 else "low", "source": api_key}
            
            elif api_key == "iphub":
                if not config.get("api_key"):
                    return None
                headers = {"X-Key": config["api_key"]}
                url = f"{config['endpoint']}{ip}"
                response = await client.get(url, headers=headers, timeout=3)
                if response.status_code == 429:  # Too many requests
                    mark_api_rate_limited(api_key)
                    return None
                if response.status_code == 200:
                    await increment_api_usage(api_key)  # Track usage
                    data = response.json()
                    block_score = data.get("block", 0)
                    is_vpn = block_score >= 1
                    return {"is_vpn": is_vpn, "vpn_score": block_score * 50, "risk": "high" if block_score >= 2 else "medium" if block_score == 1 else "low", "source": api_key}
            
            elif api_key == "scamalytics":
                # Scamalytics requires special handling
                if not config.get("api_key"):
                    return None
                url = f"{config['endpoint']}{config['api_key']}/{ip}"
                response = await client.get(url, timeout=3)
                if response.status_code == 200:
                    await increment_api_usage(api_key)  # Track usage
                    data = response.json()
                    score = data.get("score", 0)
                    is_vpn = score > 50 or data.get("proxy", "no") == "yes"
                    return {"is_vpn": is_vpn, "vpn_score": score, "risk": "high" if score > 75 else "medium" if score > 50 else "low", "source": api_key}
            
            else:
                # Custom API - generic handling
                url = config['endpoint']
                if "{ip}" in url:
                    url = url.replace("{ip}", ip)
                else:
                    url = f"{url}{ip}"
                
                headers = {}
                if config.get("api_key"):
                    headers["Authorization"] = f"Bearer {config['api_key']}"
                
                response = await client.get(url, headers=headers, timeout=3)
                if response.status_code == 429:
                    mark_api_rate_limited(api_key)
                    return None
                if response.status_code == 200:
                    data = response.json()
                    # Try to find common VPN indicators in response
                    is_vpn = (
                        data.get("vpn", False) or 
                        data.get("proxy", False) or 
                        data.get("is_vpn", False) or 
                        data.get("is_proxy", False) or
                        str(data.get("type", "")).lower() in ["vpn", "proxy", "hosting", "datacenter"]
                    )
                    return {"is_vpn": is_vpn, "vpn_score": 100 if is_vpn else 0, "risk": "high" if is_vpn else "low", "source": api_key}
    
    except httpx.TimeoutException:
        logger.debug(f"API {api_key} timed out for IP {ip}")
        return None
    except Exception as e:
        logger.debug(f"API {api_key} error for IP {ip}: {e}")
        return None
    
    return None

async def check_vpn_detailed(ip: str) -> dict:
    """Detailed VPN check using multiple services with automatic fallback"""
    if not ip or ip in ["127.0.0.1", "localhost", "unknown", "Unknown", ""] or ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168."):
        return {"is_vpn": False, "vpn_score": 0, "risk": "low", "source": "local"}
    
    # Get enabled APIs sorted by priority
    enabled_apis = await get_enabled_api_settings()
    
    # Load current usage
    await get_api_usage()
    
    if not enabled_apis:
        # Fallback to hardcoded behavior if no APIs configured
        logger.warning("No APIs enabled, using default ip-api")
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://ip-api.com/json/{ip}?fields=proxy,hosting,status", timeout=2)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "success":
                        await increment_api_usage("ipapi")
                        is_vpn = data.get("proxy", False) or data.get("hosting", False)
                        return {"is_vpn": is_vpn, "vpn_score": 100 if is_vpn else 0, "risk": "high" if is_vpn else "low", "source": "ip-api-fallback"}
        except:
            pass
        return {"is_vpn": False, "vpn_score": 0, "risk": "unknown", "source": "none"}
    
    # Try each API in priority order
    apis_tried = []
    apis_skipped_limit = []
    for api_key, config in enabled_apis:
        # Skip if daily limit reached
        if is_api_limit_reached(api_key):
            apis_skipped_limit.append(api_key)
            logger.debug(f"Skipping {api_key} - daily limit reached ({_api_usage.get(api_key, 0)}/{API_DAILY_LIMITS.get(api_key, 10000)})")
            continue
        
        # Skip if rate limited (error-based)
        if is_api_rate_limited(api_key):
            logger.debug(f"Skipping {api_key} - rate limited by API response")
            continue
        
        apis_tried.append(api_key)
        result = await check_vpn_with_api(ip, api_key, config)
        
        if result is not None:
            logger.debug(f"VPN check for {ip}: {result['source']} returned is_vpn={result['is_vpn']}")
            return result
    
    # All APIs failed or rate limited
    if apis_skipped_limit:
        logger.warning(f"All VPN APIs at limit for IP {ip}. Skipped: {apis_skipped_limit}, Tried: {apis_tried}")
    else:
        logger.warning(f"All VPN APIs failed for IP {ip}. Tried: {apis_tried}")
    return {"is_vpn": False, "vpn_score": 0, "risk": "unknown", "source": "all_failed", "apis_tried": apis_tried, "apis_at_limit": apis_skipped_limit}

# Geolocation cache - reduces API calls significantly
_geo_cache = {}
_geo_cache_ttl = 3600  # 1 hour cache for geolocation

async def get_country_from_ip(ip: str) -> dict:
    global _geo_cache
    
    if ip in ["127.0.0.1", "localhost"]:
        return {"country": "Local", "city": "", "region": "", "lat": 0, "lon": 0, "isp": "", "is_vpn": False, "is_proxy": False, "vpn_score": 0}
    
    if ip.startswith("10.") or ip.startswith("172.") or ip.startswith("192.168."):
        return {"country": "Local", "city": "", "region": "", "lat": 0, "lon": 0, "isp": "", "is_vpn": False, "is_proxy": False, "vpn_score": 0}
    
    # Check cache first
    current_time = time.time()
    if ip in _geo_cache:
        cached = _geo_cache[ip]
        if current_time - cached["time"] < _geo_cache_ttl:
            return cached["data"]
    
    country = "Unknown"
    city = ""
    region = ""
    lat = 0
    lon = 0
    isp = ""
    is_vpn = False
    is_proxy = False
    vpn_score = 0
    
    # Get full geolocation from ip-api (free, no key needed) - reduced timeout for speed
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,region,regionName,city,lat,lon,isp,proxy,hosting",
                timeout=2  # Reduced from 5 to 2 seconds
            )
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    country = data.get("country", "Unknown")
                    city = data.get("city", "")
                    region = data.get("regionName", "")
                    lat = data.get("lat", 0)
                    lon = data.get("lon", 0)
                    isp = data.get("isp", "")
                    is_proxy = data.get("proxy", False) or data.get("hosting", False)
    except Exception as e:
        pass  # Silently fail - don't block redirect
    
    # Only check VPN if needed (proxy already detected) - skip expensive call if we have answer
    if not is_proxy:
        try:
            vpn_info = await check_vpn_scamalytics(ip)
            is_vpn = vpn_info.get("is_vpn", False)
            vpn_score = vpn_info.get("vpn_score", 0)
        except:
            pass
    else:
        is_vpn = True
        vpn_score = 100
    
    result = {
        "country": country, 
        "city": city, 
        "region": region, 
        "lat": lat, 
        "lon": lon, 
        "isp": isp,
        "is_vpn": is_vpn, 
        "is_proxy": is_vpn, 
        "vpn_score": vpn_score
    }
    
    # Cache the result
    _geo_cache[ip] = {"data": result, "time": current_time}
    
    # Clean old cache entries (keep max 50000)
    if len(_geo_cache) > 50000:
        sorted_keys = sorted(_geo_cache.keys(), key=lambda k: _geo_cache[k]["time"])
        for k in sorted_keys[:25000]:
            del _geo_cache[k]
    
    return result

def detect_device(user_agent_string: str) -> dict:
    """Detect device type, OS, browser, and device brand/model"""
    ua = parse(user_agent_string)
    
    device_type = "desktop"
    if ua.is_mobile:
        device_type = "mobile"
    elif ua.is_tablet:
        device_type = "tablet"
    
    os_name = "Unknown"
    os_version = ""
    browser = ua.browser.family if ua.browser else "Unknown"
    browser_version = ua.browser.version_string if ua.browser and ua.browser.version_string else ""
    
    # Device brand and model
    device_brand = ua.device.brand if ua.device and ua.device.brand else "Unknown"
    device_model = ua.device.model if ua.device and ua.device.model else "Unknown"
    device_family = ua.device.family if ua.device and ua.device.family else "Unknown"
    
    if ua.os.family:
        os_family = ua.os.family.lower()
        
        if "ios" in os_family or "iphone" in os_family or "ipad" in os_family:
            os_name = "iOS"
            os_version = ua.os.version_string if ua.os.version_string else ""
            # For iOS, set brand to Apple if not detected
            if device_brand == "Unknown":
                device_brand = "Apple"
            if "ipad" in os_family.lower() or "ipad" in device_family.lower():
                device_model = device_model if device_model != "Unknown" else "iPad"
            elif "iphone" in os_family.lower() or "iphone" in device_family.lower():
                device_model = device_model if device_model != "Unknown" else "iPhone"
        elif "android" in os_family:
            os_name = "Android"
            os_version = ua.os.version_string if ua.os.version_string else ""
        elif "mac" in os_family or "os x" in os_family:
            os_name = "macOS"
            os_version = ua.os.version_string if ua.os.version_string else ""
            if device_brand == "Unknown":
                device_brand = "Apple"
                device_model = "Mac"
        elif "windows" in os_family:
            os_name = "Windows"
            os_version = ua.os.version_string if ua.os.version_string else ""
            if device_brand == "Unknown":
                device_brand = "PC"
                device_model = "Windows PC"
        elif "linux" in os_family:
            os_name = "Linux"
            os_version = ua.os.version_string if ua.os.version_string else ""
        elif "chrome os" in os_family:
            os_name = "ChromeOS"
        else:
            os_name = ua.os.family
            os_version = ua.os.version_string if ua.os.version_string else ""
    
    # Build device display string
    device_display = ""
    if device_brand != "Unknown" and device_model != "Unknown":
        device_display = f"{device_brand} {device_model}"
    elif device_brand != "Unknown":
        device_display = device_brand
    elif device_model != "Unknown":
        device_display = device_model
    else:
        device_display = device_type.title()
    
    # Build browser display string with version
    browser_display = browser
    if browser_version:
        browser_display = f"{browser} {browser_version}"
    
    return {
        "device_type": device_type,
        "device_brand": device_brand,
        "device_model": device_model,
        "device_display": device_display,
        "os_name": os_name,
        "os_version": os_version,
        "browser": browser,
        "browser_version": browser_version,
        "browser_display": browser_display,
        "full_string": f"{os_name} {os_version}".strip() if os_version else os_name
    }

def check_user_feature(user: dict, feature: str):
    """Check if user has access to a specific feature. Raises HTTPException if not."""
    status = user.get("status", "pending")
    
    if status == "blocked":
        raise HTTPException(status_code=403, detail="Your account has been blocked. Contact admin for support.")
    
    if status != "active":
        raise HTTPException(status_code=403, detail=f"Your account is pending activation. Contact admin at {ADMIN_CONTACT_EMAIL} for access.")
    
    features = user.get("features", {})
    # Backward compat: new granular features (email_checker, separate_data, import_traffic,
    # real_traffic, ua_generator) fall back to the legacy "import_data" flag when not set
    # explicitly. That way users created before these features existed keep access.
    LEGACY_IMPORT_GROUP = {"email_checker", "separate_data", "import_traffic", "real_traffic", "ua_generator"}
    if feature not in features and feature in LEGACY_IMPORT_GROUP:
        if features.get("import_data", False):
            return True
    if not features.get(feature, False):
        raise HTTPException(status_code=403, detail=f"Feature '{feature}' is not enabled for your account. Contact admin for access.")
    
    return True

async def get_current_user_with_fresh_data(request: Request) -> dict:
    """Get current user with fresh data from database (for feature checks)"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        is_sub_user = payload.get("is_sub_user", False)
        parent_user_id = payload.get("parent_user_id")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    
    # If sub-user, get parent user data
    if is_sub_user and parent_user_id:
        sub_user = await main_db.sub_users.find_one({"email": email}, {"_id": 0, "password_hash": 0})
        if not sub_user:
            raise HTTPException(status_code=401, detail="Sub-user not found")
        if not sub_user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Sub-user account is deactivated")
        
        parent_user = await main_db.users.find_one({"id": parent_user_id}, {"_id": 0, "password_hash": 0})
        if not parent_user:
            raise HTTPException(status_code=401, detail="Parent user not found")
        if parent_user.get("status") == "blocked":
            raise HTTPException(status_code=403, detail="Parent account has been blocked")
        if parent_user.get("status") != "active":
            raise HTTPException(status_code=403, detail="Parent account is not active")
        
        # Return parent user with sub-user info and mapped features
        parent_user["is_sub_user"] = True
        parent_user["sub_user_id"] = sub_user["id"]
        parent_user["sub_user_email"] = sub_user["email"]
        parent_user["sub_user_permissions"] = sub_user.get("permissions", {})
        
        # Map sub-user permissions to features
        parent_user["features"] = {
            "links": sub_user.get("permissions", {}).get("view_links", True),
            "clicks": sub_user.get("permissions", {}).get("view_clicks", True),
            "conversions": sub_user.get("permissions", {}).get("view_conversions", False),
            "proxies": sub_user.get("permissions", {}).get("view_proxies", False),
            "import_data": sub_user.get("permissions", {}).get("import_data", False),
            "max_links": parent_user.get("features", {}).get("max_links", 100),
            "max_clicks": parent_user.get("features", {}).get("max_clicks", 100000),
            "max_sub_users": 0
        }
        return parent_user
    
    user = await main_db.users.find_one({"email": email}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    
    # Check if blocked
    if user.get("status") == "blocked":
        raise HTTPException(status_code=403, detail="Your account has been blocked. Contact admin for support.")
    
    user["is_sub_user"] = False
    return user

def check_sub_user_permission(user: dict, permission: str):
    """Check if sub-user has specific permission"""
    if user.get("is_sub_user"):
        permissions = user.get("sub_user_permissions", {})
        if not permissions.get(permission, False):
            raise HTTPException(status_code=403, detail=f"You don't have permission to {permission}")
    return True

async def setup_user_database(user_id: str):
    """Create indexes for user-specific database"""
    user_db = get_user_db(user_id)
    try:
        await user_db.clicks.create_index([("link_id", 1), ("created_at", -1)])
        await user_db.clicks.create_index([("created_at", -1)])
        await user_db.clicks.create_index([("ip_address", 1)])
        await user_db.clicks.create_index([("ipv4", 1)])  # Fast IPv4 lookup
        await user_db.clicks.create_index([("ipv6", 1)])  # Fast IPv6 lookup
        await user_db.clicks.create_index([("detected_ip", 1)])  # Fast detected IP lookup
        await user_db.links.create_index([("short_code", 1)], unique=True)
        await user_db.proxies.create_index([("status", 1)])
        await user_db.proxies.create_index([("proxy_ip", 1)])
    except Exception as e:
        print(f"Error setting up user database: {e}")

@api_router.post("/auth/register", response_model=Token)
async def register(user: UserCreate):
    existing = await main_db.users.find_one({"email": user.email})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = str(uuid.uuid4())
    user_doc = {
        "id": user_id,
        "email": user.email,
        "name": user.name,
        "password_hash": get_password_hash(user.password),
        "status": "pending",  # pending, active, blocked
        "features": DEFAULT_FEATURES.copy(),
        "subscription_note": "",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await main_db.users.insert_one(user_doc)
    
    # Setup user-specific database
    await setup_user_database(user_id)
    
    access_token = create_access_token(data={"sub": user.email})
    
    user_response = {
        "id": user_doc["id"], 
        "email": user_doc["email"], 
        "name": user_doc["name"],
        "status": user_doc["status"],
        "features": user_doc["features"]
    }
    return {"access_token": access_token, "token_type": "bearer", "user": user_response}

@api_router.post("/auth/login", response_model=Token)
async def login(user: UserLogin):
    # Check main users first
    db_user = await main_db.users.find_one({"email": user.email}, {"_id": 0})
    
    if db_user:
        if not verify_password(user.password, db_user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if db_user.get("status") == "blocked":
            raise HTTPException(status_code=403, detail="Your account has been blocked. Contact admin for support.")
        
        access_token = create_access_token(data={"sub": user.email, "is_sub_user": False})
        user_response = {
            "id": db_user["id"], 
            "email": db_user["email"], 
            "name": db_user["name"],
            "status": db_user.get("status", "pending"),
            "features": db_user.get("features", DEFAULT_FEATURES),
            "is_sub_user": False
        }
        return {"access_token": access_token, "token_type": "bearer", "user": user_response}
    
    # Check sub-users
    sub_user = await main_db.sub_users.find_one({"email": user.email}, {"_id": 0})
    if sub_user:
        if not verify_password(user.password, sub_user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        if not sub_user.get("is_active", True):
            raise HTTPException(status_code=403, detail="Sub-user account is deactivated")
        
        # Get parent user
        parent_user = await main_db.users.find_one({"id": sub_user["parent_user_id"]}, {"_id": 0})
        if not parent_user or parent_user.get("status") != "active":
            raise HTTPException(status_code=403, detail="Parent account is not active")
        
        # Update last active
        await main_db.sub_users.update_one(
            {"id": sub_user["id"]},
            {"$set": {"last_active": datetime.now(timezone.utc).isoformat()}}
        )
        
        access_token = create_access_token(data={
            "sub": user.email, 
            "is_sub_user": True,
            "parent_user_id": sub_user["parent_user_id"]
        })
        
        user_response = {
            "id": sub_user["id"],
            "email": sub_user["email"],
            "name": sub_user["name"],
            "permissions": sub_user.get("permissions", {}),
            "is_sub_user": True,
            "parent_user_id": sub_user["parent_user_id"],
            "parent_name": parent_user["name"],
            "status": parent_user.get("status", "active"),
            # Map sub-user permissions to features for frontend compatibility
            "features": {
                "links": sub_user.get("permissions", {}).get("view_links", True),
                "clicks": sub_user.get("permissions", {}).get("view_clicks", True),
                "conversions": sub_user.get("permissions", {}).get("view_conversions", False),
                "proxies": sub_user.get("permissions", {}).get("view_proxies", False),
                "import_data": sub_user.get("permissions", {}).get("import_data", False),
                "max_links": parent_user.get("features", {}).get("max_links", 100),
                "max_clicks": parent_user.get("features", {}).get("max_clicks", 100000),
                "max_sub_users": 0  # Sub-users can't create sub-users
            },
            "subscription_type": parent_user.get("subscription_type", "free")
        }
        return {"access_token": access_token, "token_type": "bearer", "user": user_response}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

# ==================== FORGOT PASSWORD ====================
class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

@api_router.post("/auth/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Generate password reset token and send email for all user types"""
    user = None
    user_type = "user"
    user_name = "User"
    
    # Check if it's an admin
    if request.email == ADMIN_EMAIL:
        user = {"id": "admin", "email": ADMIN_EMAIL, "name": "Admin"}
        user_type = "admin"
        user_name = "Admin"
    
    # Check main users
    if not user:
        user = await main_db.users.find_one({"email": request.email})
        if user:
            user_type = "main user"
            user_name = user.get("name", "User")
    
    # Check sub-users
    if not user:
        sub_user = await main_db.sub_users.find_one({"email": request.email})
        if sub_user:
            user = sub_user
            user_type = "sub-user"
            user_name = sub_user.get("name", "User")
    
    if not user:
        # Don't reveal if email exists - still return success message
        return {"message": "If email exists, reset instructions will be sent", "email_sent": False}
    
    # Generate reset token (valid for 1 hour)
    reset_token = str(uuid.uuid4())
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    
    await main_db.password_resets.insert_one({
        "token": reset_token,
        "user_id": user["id"],
        "user_type": user_type,
        "email": request.email,
        "expires": expires.isoformat(),
        "used": False,
        "created_at": datetime.now(timezone.utc).isoformat()
    })
    
    # Send password reset email
    email_result = await send_password_reset_email(
        to_email=request.email,
        user_name=user_name,
        reset_token=reset_token,
        user_type=user_type
    )
    
    response = {
        "message": "Password reset instructions sent to your email",
        "email_sent": email_result.get("status") == "sent",
        "expires_in": "1 hour"
    }
    
    # Log demo mode info but don't expose reset URL to frontend
    if email_result.get("status") == "demo":
        logger.info(f"[DEMO MODE] Reset URL for {request.email}: {email_result.get('reset_url')}")
    
    return response

@api_router.post("/auth/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password using token - works for all user types"""
    reset_doc = await main_db.password_resets.find_one({
        "token": request.token,
        "used": False
    })
    
    if not reset_doc:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Check expiration
    expires = datetime.fromisoformat(reset_doc["expires"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Reset token has expired")
    
    # Update password based on user type
    new_hash = get_password_hash(request.new_password)
    user_type = reset_doc.get("user_type", "main user")
    user_id = reset_doc["user_id"]
    
    if user_type == "admin":
        # Admin password is in env, but we can update it in a config collection
        await main_db.admin_config.update_one(
            {"key": "admin_password"},
            {"$set": {"value": new_hash, "updated_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
        logger.info(f"Admin password updated via reset token")
    elif user_type == "sub-user":
        # Update sub-user password
        await main_db.sub_users.update_one(
            {"id": user_id},
            {"$set": {"password_hash": new_hash}}
        )
        logger.info(f"Sub-user password reset for user_id: {user_id}")
    else:
        # Update main user password
        await main_db.users.update_one(
            {"id": user_id},
            {"$set": {"password_hash": new_hash}}
        )
        logger.info(f"Main user password reset for user_id: {user_id}")
    
    # Mark token as used
    await main_db.password_resets.update_one(
        {"token": request.token},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc).isoformat()}}
    )
    
    return {"message": "Password reset successfully"}

@api_router.get("/auth/verify-reset-token/{token}")
async def verify_reset_token(token: str):
    """Verify if reset token is valid"""
    reset_doc = await main_db.password_resets.find_one({
        "token": token,
        "used": False
    })
    
    if not reset_doc:
        raise HTTPException(status_code=400, detail="Invalid token")
    
    expires = datetime.fromisoformat(reset_doc["expires"])
    if datetime.now(timezone.utc) > expires:
        raise HTTPException(status_code=400, detail="Token expired")
    
    return {"valid": True, "email": reset_doc["email"]}

@api_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    # Handle sub-user
    if user.get("is_sub_user"):
        return {
            "id": user.get("sub_user_id"),
            "email": user["email"],
            "name": user["name"],
            "status": user.get("status", "active"),
            "features": user.get("features", {}),
            "is_sub_user": True,
            "parent_user_id": user.get("parent_user_id"),
            "permissions": user.get("permissions", {}),
            "admin_contact": ADMIN_CONTACT_EMAIL
        }
    
    # Handle main user
    sub_user_count = await db.sub_users.count_documents({"parent_user_id": user["id"]})
    features = user.get("features", DEFAULT_FEATURES)
    max_sub_users = features.get("max_sub_users", 0)
    return {
        "id": user["id"], 
        "email": user["email"], 
        "name": user["name"],
        "status": user.get("status", "pending"),
        "features": features,
        "subscription_type": user.get("subscription_type", "free"),
        "subscription_expires": user.get("subscription_expires"),
        "sub_user_count": sub_user_count,
        "max_sub_users": max_sub_users,
        "is_sub_user": False,
        "admin_contact": ADMIN_CONTACT_EMAIL
    }

@api_router.put("/auth/profile")
async def update_profile(update: UserProfileUpdate, user: dict = Depends(get_current_user_with_fresh_data)):
    """Update user's own profile (name, password)"""
    update_data = {}
    
    if update.name:
        update_data["name"] = update.name
    
    if update.new_password:
        if not update.current_password:
            raise HTTPException(status_code=400, detail="Current password required to change password")
        
        # Verify current password
        db_user = await db.users.find_one({"id": user["id"]})
        if not verify_password(update.current_password, db_user["password_hash"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
        
        update_data["password_hash"] = get_password_hash(update.new_password)
    
    if update_data:
        await db.users.update_one({"id": user["id"]}, {"$set": update_data})
    
    updated_user = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return {"message": "Profile updated successfully", "user": updated_user}

# ==================== SUB-USER MANAGEMENT ====================

@api_router.post("/sub-users")
async def create_sub_user(sub_user: SubUserCreate, user: dict = Depends(get_current_user_with_fresh_data)):
    """Create a sub-user for the current user"""
    # Check if user has active status
    if user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Only active users can create sub-users")
    
    # Check max_sub_users limit
    max_sub_users = user.get("features", {}).get("max_sub_users", 0)
    current_sub_user_count = await db.sub_users.count_documents({"parent_user_id": user["id"]})
    if max_sub_users > 0 and current_sub_user_count >= max_sub_users:
        raise HTTPException(status_code=403, detail=f"You have reached your sub-user limit ({max_sub_users}). Contact admin to increase your limit.")
    
    # Check if email already exists
    existing = await db.users.find_one({"email": sub_user.email})
    existing_sub = await db.sub_users.find_one({"email": sub_user.email})
    if existing or existing_sub:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    sub_user_doc = {
        "id": str(uuid.uuid4()),
        "parent_user_id": user["id"],
        "email": sub_user.email,
        "name": sub_user.name,
        "password_hash": get_password_hash(sub_user.password),
        "permissions": sub_user.permissions or {
            "view_clicks": True,
            "view_links": True,
            "view_proxies": False,
            "edit": False
        },
        "is_active": True,
        "last_active": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.sub_users.insert_one(sub_user_doc)
    sub_user_doc.pop("_id", None)
    sub_user_doc.pop("password_hash", None)
    return {"message": "Sub-user created successfully", "sub_user": sub_user_doc}

@api_router.get("/sub-users")
async def get_sub_users(user: dict = Depends(get_current_user_with_fresh_data)):
    """Get all sub-users for the current user"""
    sub_users = await db.sub_users.find(
        {"parent_user_id": user["id"]}, 
        {"_id": 0, "password_hash": 0}
    ).to_list(100)
    return sub_users

@api_router.put("/sub-users/{sub_user_id}")
async def update_sub_user(sub_user_id: str, update: SubUserUpdate, user: dict = Depends(get_current_user_with_fresh_data)):
    """Update a sub-user"""
    sub_user = await db.sub_users.find_one({"id": sub_user_id, "parent_user_id": user["id"]})
    if not sub_user:
        raise HTTPException(status_code=404, detail="Sub-user not found")
    
    update_data = {}
    if update.name:
        update_data["name"] = update.name
    if update.password:
        update_data["password_hash"] = get_password_hash(update.password)
    if update.permissions is not None:
        update_data["permissions"] = update.permissions
    if update.is_active is not None:
        update_data["is_active"] = update.is_active
    
    if update_data:
        await db.sub_users.update_one({"id": sub_user_id}, {"$set": update_data})
    
    updated = await db.sub_users.find_one({"id": sub_user_id}, {"_id": 0, "password_hash": 0})
    return {"message": "Sub-user updated successfully", "sub_user": updated}

@api_router.delete("/sub-users/{sub_user_id}")
async def delete_sub_user(sub_user_id: str, user: dict = Depends(get_current_user_with_fresh_data)):
    """Delete a sub-user"""
    result = await db.sub_users.delete_one({"id": sub_user_id, "parent_user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Sub-user not found")
    return {"message": "Sub-user deleted successfully"}

@api_router.post("/sub-users/login", response_model=Token)
async def sub_user_login(credentials: UserLogin):
    """Login as a sub-user"""
    sub_user = await db.sub_users.find_one({"email": credentials.email}, {"_id": 0})
    if not sub_user or not verify_password(credentials.password, sub_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if not sub_user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Sub-user account is deactivated")
    
    # Get parent user to check if they're still active
    parent_user = await db.users.find_one({"id": sub_user["parent_user_id"]}, {"_id": 0})
    if not parent_user or parent_user.get("status") != "active":
        raise HTTPException(status_code=403, detail="Parent account is not active")
    
    # Update last active
    await db.sub_users.update_one(
        {"id": sub_user["id"]},
        {"$set": {"last_active": datetime.now(timezone.utc).isoformat()}}
    )
    
    access_token = create_access_token(data={
        "sub": credentials.email, 
        "is_sub_user": True,
        "parent_user_id": sub_user["parent_user_id"]
    })
    
    return {
        "access_token": access_token, 
        "token_type": "bearer", 
        "user": {
            "id": sub_user["id"],
            "email": sub_user["email"],
            "name": sub_user["name"],
            "permissions": sub_user.get("permissions", {}),
            "is_sub_user": True,
            "parent_user_id": sub_user["parent_user_id"]
        }
    }

@api_router.get("/sub-users/stats")
async def get_sub_users_stats(user: dict = Depends(get_current_user_with_fresh_data)):
    """Get statistics (click/link counts) for all sub-users of the current main user"""
    if user.get("is_sub_user"):
        raise HTTPException(status_code=403, detail="Only main users can view sub-user statistics")
    
    # Get user's database for links/clicks
    user_db = get_db_for_user(user)
    
    # Get all sub-users for this main user
    sub_users = await db.sub_users.find(
        {"parent_user_id": user["id"]}, 
        {"_id": 0, "password_hash": 0}
    ).to_list(100)
    
    stats = []
    for sub_user in sub_users:
        sub_user_id = sub_user["id"]
        
        # Count links created by this sub-user
        link_count = await user_db.links.count_documents({"created_by": sub_user_id})
        
        # Count clicks created by this sub-user
        click_count = await user_db.clicks.count_documents({"created_by": sub_user_id})
        
        # Count proxies uploaded by this sub-user
        proxy_count = await user_db.proxies.count_documents({"created_by": sub_user_id})
        
        stats.append({
            "id": sub_user["id"],
            "email": sub_user["email"],
            "name": sub_user["name"],
            "permissions": sub_user.get("permissions", {}),
            "is_active": sub_user.get("is_active", True),
            "last_active": sub_user.get("last_active"),
            "created_at": sub_user.get("created_at"),
            "link_count": link_count,
            "click_count": click_count,
            "proxy_count": proxy_count
        })
    
    return {"sub_users": stats, "total": len(stats)}

# ==================== ADMIN ROUTES ====================

async def get_current_admin(request: Request):
    """Verify admin token"""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        is_admin = payload.get("is_admin", False)
        if not is_admin or email != ADMIN_EMAIL:
            raise HTTPException(status_code=403, detail="Admin access required")
        return {"email": email, "is_admin": True}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@api_router.post("/admin/login", response_model=AdminToken)
async def admin_login(credentials: AdminLogin):
    logger.info(f"Admin login attempt for: {credentials.email}")
    logger.info(f"Expected admin email: {ADMIN_EMAIL}")
    
    if credentials.email != ADMIN_EMAIL or credentials.password != ADMIN_PASSWORD:
        logger.warning(f"Admin login failed - email match: {credentials.email == ADMIN_EMAIL}, password match: {credentials.password == ADMIN_PASSWORD}")
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    
    access_token = create_access_token(data={"sub": credentials.email, "is_admin": True})
    return {"access_token": access_token, "token_type": "bearer", "is_admin": True}

@api_router.get("/admin/users", response_model=List[UserResponse])
async def get_all_users(admin: dict = Depends(get_current_admin)):
    """Get all registered users with sub-user count"""
    users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(100000)
    
    result = []
    for user in users:
        sub_count = await db.sub_users.count_documents({"parent_user_id": user["id"]})
        result.append(UserResponse(**{
            **user,
            "status": user.get("status", "pending"),
            "features": user.get("features", DEFAULT_FEATURES),
            "subscription_type": user.get("subscription_type"),
            "subscription_expires": user.get("subscription_expires"),
            "sub_user_count": sub_count
        }))
    
    return result

@api_router.get("/admin/users/stats/all")
async def get_all_users_stats(admin: dict = Depends(get_current_admin)):
    """Get statistics (links, clicks, proxies) for all users - optimized version"""
    try:
        users = await db.users.find({}, {"_id": 0, "password_hash": 0}).to_list(1000)
        
        result = []
        for user in users:
            try:
                user_id = user["id"]
                
                # Count stats from main database only (faster, more reliable)
                link_count = await db.links.count_documents({"user_id": user_id})
                proxy_count = await db.proxies.count_documents({"user_id": user_id})
                
                # Get links for click counting
                user_links = await db.links.find({"user_id": user_id}, {"_id": 0, "id": 1}).to_list(1000)
                link_ids = [l["id"] for l in user_links]
                
                # Count clicks
                click_count = 0
                if link_ids:
                    click_count = await db.clicks.count_documents({"link_id": {"$in": link_ids}})
                
                sub_user_count = await db.sub_users.count_documents({"parent_user_id": user_id})
                
                result.append({
                    "id": user_id,
                    "email": user["email"],
                    "name": user["name"],
                    "status": user.get("status", "pending"),
                    "link_count": link_count,
                    "click_count": click_count,
                    "proxy_count": proxy_count,
                    "sub_user_count": sub_user_count
                })
            except Exception as user_error:
                logger.error(f"Error getting stats for user {user.get('id', 'unknown')}: {user_error}")
                result.append({
                    "id": user.get("id", "unknown"),
                    "email": user.get("email", "unknown"),
                    "name": user.get("name", "unknown"),
                    "status": user.get("status", "pending"),
                    "link_count": 0,
                    "click_count": 0,
                    "proxy_count": 0,
                    "sub_user_count": 0
                })
        
        return result
    except Exception as e:
        logger.error(f"Error in get_all_users_stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch user stats: {str(e)}")


@api_router.get("/admin/system-check")
async def admin_system_check(admin: dict = Depends(get_current_admin)):
    """Return green/red health status for every dependency the app relies on.
    Admins can check here before a deploy to confirm the runtime is healthy.
    """
    import shutil
    import importlib
    checks: List[Dict[str, Any]] = []

    # ── Python dependencies ─────────────────────────────────────────
    # optional=True items are notices only — a missing optional package does
    # not turn the overall badge red (e.g. the Emergent AI add-on is only
    # needed for the AI Automation Generator feature; self-hosted local
    # Docker deployments work perfectly fine without it).
    deps = [
        ("pandas", "pandas", False),
        ("openpyxl", "openpyxl (xlsx parser)", False),
        ("xlrd", "xlrd (legacy xls parser)", False),
        ("playwright", "playwright (browser automation)", False),
        ("user_agents", "user-agents (UA parser)", False),
        ("faker", "Faker (fake data)", False),
        ("fake_useragent", "fake-useragent", False),
        ("aiofiles", "aiofiles", False),
        ("resend", "resend (email)", False),
        ("motor", "motor (Mongo client)", False),
        ("emergentintegrations", "emergentintegrations (LLM / AI) — optional", True),
    ]
    for modname, label, is_optional in deps:
        try:
            m = importlib.import_module(modname)
            ver = getattr(m, "__version__", "")
            checks.append({"group": "Python deps", "name": label, "ok": True, "detail": ver or "installed"})
        except Exception as e:
            # Optional packages: report as "soft" (ok=True visually, but with
            # a warning detail so the admin still knows it's not installed).
            if is_optional:
                checks.append({
                    "group": "Python deps",
                    "name": label,
                    "ok": True,
                    "detail": "not installed (optional — AI feature disabled)",
                })
            else:
                checks.append({"group": "Python deps", "name": label, "ok": False, "detail": str(e)})

    # ── Playwright Chromium browser binary ─────────────────────────
    try:
        pw_paths = [
            Path("/pw-browsers"),
            Path.home() / ".cache" / "ms-playwright",
            Path("/ms-playwright"),
            Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")),
        ]
        chromium_found = None
        for base in pw_paths:
            if base and base.exists():
                hits = list(base.glob("chromium-*/chrome-linux/chrome")) + list(base.glob("chromium-*/chrome-linux/headless_shell"))
                if hits:
                    chromium_found = str(hits[0])
                    break
        if chromium_found:
            checks.append({"group": "Browser", "name": "Playwright Chromium", "ok": True, "detail": chromium_found})
        else:
            checks.append({"group": "Browser", "name": "Playwright Chromium",
                           "ok": False,
                           "detail": "No chromium binary found. Run: playwright install chromium --with-deps"})
    except Exception as e:
        checks.append({"group": "Browser", "name": "Playwright Chromium", "ok": False, "detail": str(e)})

    # ── MongoDB ────────────────────────────────────────────────────
    try:
        await client.admin.command("ping")
        collections = await main_db.list_collection_names()
        checks.append({"group": "Database", "name": "MongoDB connection", "ok": True,
                       "detail": f"{len(collections)} collections in {db_name}"})
        users_count = await main_db.users.count_documents({})
        checks.append({"group": "Database", "name": "users collection", "ok": True, "detail": f"{users_count} users"})
        all_dbs = await client.list_database_names()
        per_user_dbs = [d for d in all_dbs if d.startswith("trackmaster_user_")]
        checks.append({"group": "Database", "name": "per-user databases", "ok": True, "detail": f"{len(per_user_dbs)} user DB(s)"})
    except Exception as e:
        checks.append({"group": "Database", "name": "MongoDB connection", "ok": False, "detail": str(e)})

    # ── Email / SMTP ───────────────────────────────────────────────
    if SMTP_USER and SMTP_PASSWORD:
        checks.append({"group": "Email", "name": "Gmail SMTP", "ok": True, "detail": f"configured ({SMTP_USER})"})
    elif RESEND_API_KEY:
        checks.append({"group": "Email", "name": "Resend", "ok": True, "detail": "configured"})
    else:
        checks.append({"group": "Email", "name": "Email service", "ok": False,
                       "detail": "No SMTP / Resend configured — password-reset emails will be logged only"})

    # ── Disk space ─────────────────────────────────────────────────
    try:
        total, used, free = shutil.disk_usage("/app")
        free_gb = free / (1024 ** 3)
        used_pct = (used / total) * 100
        ok = free_gb > 1.0  # require at least 1 GB free
        checks.append({
            "group": "System",
            "name": "Disk space (/app)",
            "ok": ok,
            "detail": f"{free_gb:.1f} GB free · {used_pct:.0f}% used",
        })
    except Exception as e:
        checks.append({"group": "System", "name": "Disk space", "ok": False, "detail": str(e)})

    # ── RUT / Form-Filler result folders writable ──────────────────
    for label, p in [
        ("RUT results folder", "/app/backend/real_user_traffic_results"),
        ("Form-Filler results folder", "/app/backend/form_filler_results"),
    ]:
        try:
            path = Path(p)
            path.mkdir(parents=True, exist_ok=True)
            test = path / ".probe"
            test.write_text("ok")
            test.unlink()
            checks.append({"group": "Storage", "name": label, "ok": True, "detail": "writable"})
        except Exception as e:
            checks.append({"group": "Storage", "name": label, "ok": False, "detail": str(e)})

    # ── Admin + Postback tokens ────────────────────────────────────
    checks.append({
        "group": "Config",
        "name": "JWT secret",
        "ok": SECRET_KEY != "your-secret-key-change-in-production",
        "detail": "custom secret" if SECRET_KEY != "your-secret-key-change-in-production"
                  else "using built-in default (change in production!)",
    })
    checks.append({
        "group": "Config",
        "name": "Postback token",
        "ok": POSTBACK_TOKEN != "secure-postback-token-123",
        "detail": "custom token" if POSTBACK_TOKEN != "secure-postback-token-123"
                  else "using built-in default (change in production!)",
    })

    # ── Summary counters ───────────────────────────────────────────
    # Only HARD infrastructure failures count against the overall badge:
    # missing Python deps, missing browser, DB unreachable, folder not writable.
    # Soft items (no email configured, default JWT / default postback token)
    # are security notices — they should NOT turn a fresh deploy "red".
    HARD_GROUPS = {"Python deps", "Browser", "Database", "Storage"}
    hard_failed = [c for c in checks if not c["ok"] and c["group"] in HARD_GROUPS]
    soft_failed = [c for c in checks if not c["ok"] and c["group"] not in HARD_GROUPS]

    total = len(checks)
    passed = sum(1 for c in checks if c["ok"])
    failed = total - passed
    if hard_failed:
        overall = "critical" if len(hard_failed) >= 3 else "degraded"
    elif soft_failed:
        overall = "healthy"  # soft warnings don't flip the badge
    else:
        overall = "healthy"

    return {
        "overall": overall,
        "total": total,
        "passed": passed,
        "failed": failed,
        "hard_failed": len(hard_failed),
        "soft_failed": len(soft_failed),
        "checks": checks,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@api_router.get("/admin/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, admin: dict = Depends(get_current_admin)):
    """Get single user details"""
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**{
        **user,
        "status": user.get("status", "pending"),
        "features": user.get("features", DEFAULT_FEATURES)
    })

@api_router.put("/admin/users/{user_id}")
async def update_user(user_id: str, update: UserUpdate, admin: dict = Depends(get_current_admin)):
    """Update user status, features, credentials, and subscription"""
    user = await db.users.find_one({"id": user_id})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    update_data = {}
    if update.status:
        update_data["status"] = update.status
    if update.features:
        update_data["features"] = update.features.model_dump()
    if update.subscription_note is not None:
        update_data["subscription_note"] = update.subscription_note
    if update.subscription_type:
        update_data["subscription_type"] = update.subscription_type
    if update.subscription_expires:
        update_data["subscription_expires"] = update.subscription_expires
    
    # Admin can update email
    if update.email and update.email != user["email"]:
        existing = await db.users.find_one({"email": update.email})
        if existing:
            raise HTTPException(status_code=400, detail="Email already in use")
        update_data["email"] = update.email
    
    # Admin can update password
    if update.password:
        update_data["password_hash"] = get_password_hash(update.password)
    
    if update_data:
        await db.users.update_one({"id": user_id}, {"$set": update_data})
    
    updated_user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return {"message": "User updated successfully", "user": updated_user}

@api_router.get("/admin/sub-users")
async def get_all_sub_users(admin: dict = Depends(get_current_admin)):
    """Get all sub-users across all users (admin only)"""
    sub_users = await db.sub_users.find({}, {"_id": 0, "password_hash": 0}).to_list(10000)
    
    # Get parent user info for each sub-user
    for sub_user in sub_users:
        parent = await db.users.find_one({"id": sub_user["parent_user_id"]}, {"_id": 0, "email": 1, "name": 1})
        sub_user["parent_email"] = parent["email"] if parent else "Unknown"
        sub_user["parent_name"] = parent["name"] if parent else "Unknown"
    
    return sub_users

@api_router.put("/admin/sub-users/{sub_user_id}")
async def admin_update_sub_user(sub_user_id: str, update: SubUserUpdate, admin: dict = Depends(get_current_admin)):
    """Admin endpoint to update any sub-user"""
    sub_user = await db.sub_users.find_one({"id": sub_user_id})
    if not sub_user:
        raise HTTPException(status_code=404, detail="Sub-user not found")
    
    update_data = {}
    if update.name:
        update_data["name"] = update.name
    if update.password:
        update_data["password_hash"] = get_password_hash(update.password)
    if update.permissions is not None:
        update_data["permissions"] = update.permissions
    if update.is_active is not None:
        update_data["is_active"] = update.is_active
    
    if update_data:
        await db.sub_users.update_one({"id": sub_user_id}, {"$set": update_data})
    
    updated = await db.sub_users.find_one({"id": sub_user_id}, {"_id": 0, "password_hash": 0})
    return {"message": "Sub-user updated successfully", "sub_user": updated}

@api_router.delete("/admin/sub-users/{sub_user_id}")
async def admin_delete_sub_user(sub_user_id: str, admin: dict = Depends(get_current_admin)):
    """Admin endpoint to delete any sub-user"""
    result = await db.sub_users.delete_one({"id": sub_user_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Sub-user not found")
    return {"message": "Sub-user deleted successfully"}

@api_router.get("/admin/users-with-subusers")
async def get_users_with_subusers(admin: dict = Depends(get_current_admin)):
    """Get users that have sub-users"""
    # Get all parent_user_ids from sub_users
    parent_ids = await db.sub_users.distinct("parent_user_id")
    users_with_subs = await db.users.find(
        {"id": {"$in": parent_ids}}, 
        {"_id": 0, "password_hash": 0}
    ).to_list(1000)
    
    # Add sub-user count to each user
    for user in users_with_subs:
        count = await db.sub_users.count_documents({"parent_user_id": user["id"]})
        user["sub_user_count"] = count
    
    return users_with_subs

@api_router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_current_admin)):
    """Delete a user and all their data"""
    try:
        user = await db.users.find_one({"id": user_id})
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Delete user's data - with error handling for each step
        try:
            # Get user's links
            user_links = await db.links.find({"user_id": user_id}, {"_id": 0, "id": 1}).to_list(10000)
            link_ids = [link["id"] for link in user_links]
            
            # Delete clicks and conversions for user's links
            if link_ids:
                await db.clicks.delete_many({"link_id": {"$in": link_ids}})
                await db.conversions.delete_many({"link_id": {"$in": link_ids}})
            
            # Delete user's links and proxies
            await db.links.delete_many({"user_id": user_id})
            await db.proxies.delete_many({"user_id": user_id})
            
            # Delete sub-users created by this user
            await db.sub_users.delete_many({"parent_user_id": user_id})
            
            # Also try to clean up user-specific database if it exists
            try:
                user_db_name = f"trackmaster_user_{user_id}"
                await client.drop_database(user_db_name)
                logger.info(f"Dropped user database: {user_db_name}")
            except Exception as db_drop_error:
                logger.warning(f"Could not drop user database (may not exist): {db_drop_error}")
            
        except Exception as data_error:
            logger.error(f"Error deleting user data: {data_error}")
            # Continue to delete the user even if some data cleanup fails
        
        # Finally delete the user
        await db.users.delete_one({"id": user_id})
        
        return {"message": "User and all associated data deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")

@api_router.get("/admin/stats")
async def get_admin_stats(admin: dict = Depends(get_current_admin)):
    """Get overall system statistics"""
    try:
        total_users = await db.users.count_documents({})
        active_users = await db.users.count_documents({"status": "active"})
        pending_users = await db.users.count_documents({"status": "pending"})
        blocked_users = await db.users.count_documents({"status": "blocked"})
        total_links = await db.links.count_documents({})
        total_clicks = await db.clicks.count_documents({})
        total_conversions = await db.conversions.count_documents({})
        total_sub_users = await db.sub_users.count_documents({})
        users_with_sub_users = len(await db.sub_users.distinct("parent_user_id"))
        
        return {
            "total_users": total_users,
            "active_users": active_users,
            "pending_users": pending_users,
            "blocked_users": blocked_users,
            "total_links": total_links,
            "total_clicks": total_clicks,
            "total_conversions": total_conversions,
            "total_sub_users": total_sub_users,
            "users_with_sub_users": users_with_sub_users
        }
    except Exception as e:
        logger.error(f"Error in get_admin_stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch admin stats: {str(e)}")

# ==================== BRANDING SETTINGS ====================

@api_router.get("/branding")
async def get_branding():
    """Get branding settings (public endpoint)"""
    branding = await main_db.settings.find_one({"key": "branding"}, {"_id": 0})
    if branding and "value" in branding:
        return branding["value"]
    return DEFAULT_BRANDING

@api_router.get("/admin/branding")
async def get_admin_branding(admin: dict = Depends(get_current_admin)):
    """Get branding settings for admin"""
    branding = await main_db.settings.find_one({"key": "branding"}, {"_id": 0})
    if branding and "value" in branding:
        return branding["value"]
    return DEFAULT_BRANDING

@api_router.put("/admin/branding")
async def update_branding(branding_update: BrandingUpdate, admin: dict = Depends(get_current_admin)):
    """Update branding settings"""
    # Get current branding or default
    current = await main_db.settings.find_one({"key": "branding"})
    if current and "value" in current:
        current_branding = current["value"]
    else:
        current_branding = DEFAULT_BRANDING.copy()
    
    # Update only provided fields
    update_data = branding_update.dict(exclude_none=True)
    for key, value in update_data.items():
        current_branding[key] = value
    
    current_branding["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Save to database
    await main_db.settings.update_one(
        {"key": "branding"},
        {"$set": {"key": "branding", "value": current_branding}},
        upsert=True
    )
    
    logger.info(f"Branding settings updated by admin")
    return {"message": "Branding updated successfully", "branding": current_branding}

@api_router.post("/admin/branding/reset")
async def reset_branding(admin: dict = Depends(get_current_admin)):
    """Reset branding to default settings"""
    default = DEFAULT_BRANDING.copy()
    default["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await main_db.settings.update_one(
        {"key": "branding"},
        {"$set": {"key": "branding", "value": default}},
        upsert=True
    )
    
    logger.info(f"Branding settings reset to default by admin")
    return {"message": "Branding reset to default", "branding": default}


# ==================== UA VERSIONS — admin view / refresh ====================

@api_router.get("/admin/ua-versions")
async def admin_get_ua_versions(admin: dict = Depends(get_current_admin)):
    """View the currently-loaded UA version lists + last refresh metadata."""
    return {
        "app_versions": _APP_VERSIONS,
        "ios_os_versions": [v.replace("_", ".") for v in _IOS_OS_VERSIONS],
        "android_os_versions": [v["version"] for v in _ANDROID_OS_VERSIONS],
        "chrome_versions": list(_CHROME_VERSIONS),
        "firefox_versions": list(_FIREFOX_VERSIONS),
        "meta": _UA_VERSIONS_META,
    }


@api_router.post("/admin/ua-versions/refresh")
async def admin_refresh_ua_versions(admin: dict = Depends(get_current_admin)):
    """Force-refresh UA app versions from the iTunes Lookup API right now."""
    result = await refresh_ua_versions()
    return {
        "message": "UA versions refreshed" if result["ok"] else "Refreshed with some failures",
        "updated": result["updated"],
        "failures": result["failures"],
        "meta": result["meta"],
        "app_versions": _APP_VERSIONS,
    }


# ==================== FORM FILLER / SURVEY BOT ====================

from form_filler import (
    load_rows_from_excel,
    load_rows_from_google_sheet,
    run_form_filler_job,
    create_job_record,
    cleanup_old_job,
    RESULTS_ROOT as _FF_RESULTS_ROOT,
    JOBS as _FF_JOBS,
)


@api_router.post("/form-filler/jobs")
async def form_filler_create_job(
    background: BackgroundTasks,
    target_link_id: Optional[str] = Form(None),
    target_url: Optional[str] = Form(None),
    data_source: str = Form("excel"),              # "excel" or "gsheet"
    gsheet_url: Optional[str] = Form(None),
    count: int = Form(10),
    duration_minutes: float = Form(5.0),
    skip_captcha: bool = Form(True),
    use_user_agents: bool = Form(True),
    use_proxies: bool = Form(False),
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user),
):
    """
    Create a Form Filler job. The request is multipart/form-data.
    EITHER `target_link_id` (to reuse a link from the user's Links panel)
    OR `target_url` must be provided.
    `data_source` = "excel" requires `file`; `data_source` = "gsheet" requires `gsheet_url`.
    """
    # Resolve target URL
    final_url = (target_url or "").strip()
    if target_link_id and not final_url:
        link = await db.links.find_one({"id": target_link_id, "user_id": user["id"]}, {"_id": 0})
        if not link:
            raise HTTPException(status_code=404, detail="Link not found in your panel")
        final_url = link.get("destination_url") or link.get("target_url") or link.get("url", "")
    if not final_url or not final_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="Provide a valid target URL or pick a link from your panel")

    # Load rows
    if data_source == "gsheet":
        if not gsheet_url:
            raise HTTPException(status_code=400, detail="gsheet_url is required when data_source='gsheet'")
        try:
            rows = await load_rows_from_google_sheet(gsheet_url)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not load Google Sheet: {e}")
    else:
        if not file:
            raise HTTPException(status_code=400, detail="Excel/CSV file is required when data_source='excel'")
        content = await file.read()
        try:
            rows = load_rows_from_excel(content, file.filename or "data.xlsx")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Could not parse file: {e}")

    if not rows:
        raise HTTPException(status_code=400, detail="Uploaded data has no rows")
    if count < 1 or count > 5000:
        raise HTTPException(status_code=400, detail="Count must be between 1 and 5000")
    if duration_minutes < 0 or duration_minutes > 1440:
        raise HTTPException(status_code=400, detail="Duration must be between 0 and 1440 minutes")

    # Optional: gather user's stored UAs + proxies
    ua_list = None
    if use_user_agents:
        # Use the master pool from the UA generator as a simple source
        try:
            from server import _IOS_DEVICES, _ANDROID_DEVICES, _ua_chrome_android, _ua_safari_ios, _CHROME_VERSIONS  # self-import, safe
        except Exception:
            pass
        # Generate 10 realistic UAs ad-hoc
        uas = []
        for _ in range(min(count, 20)):
            d = random.choice(_ANDROID_DEVICES + _IOS_DEVICES)
            if "and_ver" in d:
                uas.append(_ua_chrome_android(d, random.choice(_CHROME_VERSIONS)))
            else:
                uas.append(_ua_safari_ios(d))
        ua_list = uas

    proxy_list = None
    if use_proxies:
        proxies = await db.proxies.find(
            {"user_id": user["id"], "status": {"$in": ["active", "online", None]}},
            {"_id": 0, "proxy_ip": 1, "proxy_port": 1, "username": 1, "password": 1},
        ).to_list(500)
        proxy_list = []
        for p in proxies:
            ip = p.get("proxy_ip")
            port = p.get("proxy_port")
            if not ip or not port:
                continue
            if p.get("username") and p.get("password"):
                proxy_list.append(f"{ip}:{port}:{p['username']}:{p['password']}")
            else:
                proxy_list.append(f"{ip}:{port}")
        if not proxy_list:
            proxy_list = None  # fall through to no-proxy mode

    # Create job record & kick off background task
    job_id = str(uuid.uuid4())
    create_job_record(
        job_id=job_id,
        user_id=user["id"],
        target_url=final_url,
        total_rows=len(rows),
        count=count,
        duration_minutes=duration_minutes,
        data_source=data_source,
    )
    background.add_task(
        run_form_filler_job,
        job_id=job_id,
        target_url=final_url,
        rows=rows,
        count=count,
        duration_minutes=duration_minutes,
        user_agents=ua_list,
        proxies=proxy_list,
        skip_captcha=skip_captcha,
        db=db,
    )
    return {
        "job_id": job_id,
        "status": "queued",
        "total": min(count, len(rows)),
        "target_url": final_url,
        "rows_loaded": len(rows),
    }


@api_router.get("/form-filler/jobs")
async def form_filler_list_jobs(user: dict = Depends(get_current_user)):
    """List this user's form-filler jobs (hot cache + persisted)."""
    # Merge in-memory + persisted
    persisted = await db.form_filler_jobs.find(
        {"user_id": user["id"]}, {"_id": 0, "report": 0}
    ).sort("created_at", -1).to_list(200)
    hot = [j for j in _FF_JOBS.values() if j.get("user_id") == user["id"]]
    seen, out = set(), []
    for j in sorted(hot + persisted, key=lambda x: x.get("created_at", ""), reverse=True):
        jid = j.get("job_id")
        if jid in seen:
            continue
        seen.add(jid)
        out.append(j)
    return {"jobs": out}


@api_router.get("/form-filler/jobs/{job_id}")
async def form_filler_get_job(job_id: str, user: dict = Depends(get_current_user)):
    """Progress + report for one job."""
    j = _FF_JOBS.get(job_id)
    if not j:
        j = await db.form_filler_jobs.find_one({"job_id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.get("user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return j


@api_router.get("/form-filler/jobs/{job_id}/download")
async def form_filler_download(job_id: str, user: dict = Depends(get_current_user)):
    """Download the ZIP (screenshots + report.csv)."""
    j = _FF_JOBS.get(job_id) or await db.form_filler_jobs.find_one({"job_id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    if j.get("status") != "completed":
        raise HTTPException(status_code=400, detail=f"Job is {j.get('status')} — not ready yet")
    zip_path = Path(_FF_RESULTS_ROOT) / job_id / "results.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="Results archive not found on disk")
    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"form-filler-{job_id[:8]}.zip",
    )


@api_router.delete("/form-filler/jobs/{job_id}")
async def form_filler_delete(job_id: str, user: dict = Depends(get_current_user)):
    j = _FF_JOBS.get(job_id) or await db.form_filler_jobs.find_one({"job_id": job_id, "user_id": user["id"]}, {"_id": 0})
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    cleanup_old_job(job_id)
    await db.form_filler_jobs.delete_one({"job_id": job_id, "user_id": user["id"]})
    return {"message": "Deleted"}


# ==================== REAL USER TRAFFIC (anti-detect) ====================

from real_user_traffic import (
    run_real_user_traffic_job,
    create_rut_job,
    cleanup_rut_job,
    request_job_cancel,
    get_live_steps as _rut_get_live_steps,
    RUT_JOBS as _RUT_JOBS,
)


def _is_local_or_private_host(url: str) -> bool:
    """True if url's host is not reachable through a public proxy —
    localhost / 127.x / 0.0.0.0 / 10.x / 172.16-31.x / 192.168.x /
    Docker service names ('backend', 'frontend', 'mongo', etc.).
    Used to detect when the user pasted a local-only tracker URL that
    can't be opened through a real-user-traffic proxy."""
    try:
        from urllib.parse import urlparse
        import ipaddress
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return False
        # Common local / Docker service names
        if host in ("localhost", "backend", "frontend", "mongo", "host.docker.internal"):
            return True
        if host.endswith(".local") or host.endswith(".internal"):
            return True
        try:
            ip = ipaddress.ip_address(host)
            return ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
        except ValueError:
            return False
    except Exception:
        return False


def _rut_build_target_url(request: Request, link: dict, explicit_target: Optional[str]) -> str:
    sc = link["short_code"]
    if explicit_target and explicit_target.strip():
        tu = explicit_target.strip().rstrip("/")
        # If user already provided a complete URL (starts with http/https),
        # use it AS-IS — supports both tracker URLs ("…/t/abc") and direct
        # offer URLs (bypass tracker for form-fill-only testing).
        if tu.lower().startswith(("http://", "https://")):
            # Local host detection — if the target is localhost / private IP
            # (unreachable through a public proxy), auto-swap to the link's
            # offer_url so the browser can actually reach the landing page.
            if _is_local_or_private_host(tu):
                offer = link.get("offer_url") or link.get("destination_url")
                if offer and offer.strip().lower().startswith(("http://", "https://")) \
                        and not _is_local_or_private_host(offer):
                    return offer.strip()
            return tu
        # Bare host like "yourdomain.com" → append tracker path
        return f"{tu}/api/t/{sc}"
    public_base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL") or ""
    if public_base and public_base.startswith("http"):
        candidate = f"{public_base.rstrip('/')}/api/t/{sc}"
        if _is_local_or_private_host(candidate):
            offer = link.get("offer_url") or link.get("destination_url")
            if offer and offer.strip().lower().startswith(("http://", "https://")) \
                    and not _is_local_or_private_host(offer):
                return offer.strip()
        return candidate
    try:
        fwd_proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if fwd_host:
            scheme = fwd_proto.split(",")[0].strip()
            host = fwd_host.split(",")[0].strip()
            candidate = f"{scheme}://{host}/api/t/{sc}"
            if _is_local_or_private_host(candidate):
                offer = link.get("offer_url") or link.get("destination_url")
                if offer and offer.strip().lower().startswith(("http://", "https://")) \
                        and not _is_local_or_private_host(offer):
                    return offer.strip()
            return candidate
    except Exception:
        pass
    raise HTTPException(
        status_code=400,
        detail=("Could not determine a PUBLIC short-link URL. Paste it in the "
                "'Target URL' field or set PUBLIC_BASE_URL in backend .env."),
    )


@api_router.post("/real-user-traffic/jobs")
async def rut_create_job(
    background: BackgroundTasks,
    request: Request,
    link_id: str = Form(...),
    target_url: Optional[str] = Form(None),
    # Traffic source
    proxies: str = Form(""),                          # newline-separated
    user_agents: str = Form(...),                     # newline-separated
    use_stored_proxies: bool = Form(False),
    # Run settings
    total_clicks: int = Form(10),
    concurrency: int = Form(3),
    duration_minutes: float = Form(0),
    # Target mode — "clicks" = run N visits; "conversions" = keep running
    # until X conversions OR max_attempts reached (whichever comes first)
    target_mode: str = Form("clicks"),
    target_conversions: int = Form(0),
    max_attempts: int = Form(0),
    # Filters
    allowed_countries: str = Form(""),                # comma-separated country NAMES
    allowed_os: str = Form(""),                       # comma-separated os keys (android,ios,windows,macos,linux)
    skip_duplicate_ip: bool = Form(True),
    skip_vpn: bool = Form(True),
    follow_redirect: bool = Form(False),
    no_repeated_proxy: bool = Form(False),
    # Form filler
    form_fill_enabled: bool = Form(False),
    data_source: str = Form("excel"),                 # "excel" | "gsheet" | "pending_from_job"
    gsheet_url: Optional[str] = Form(None),
    import_pending_from_job_id: Optional[str] = Form(None),
    state_match_enabled: bool = Form(False),
    invalid_detection_enabled: bool = Form(False),    # OFF by default — landing
                                                      # pages with consent banners
                                                      # trigger false positives
    skip_captcha: bool = Form(True),
    post_submit_wait: int = Form(6),                  # seconds 3..15
    automation_json: Optional[str] = Form(None),      # custom step-list JSON
    self_heal: bool = Form(True),                     # AI fallback for unexpected popups
    file: Optional[UploadFile] = File(None),
    user: dict = Depends(get_current_user_with_fresh_data),
):
    """Kick off a real-user-traffic run. Combines real-traffic + optional form-fill."""
    check_user_feature(user, "real_user_traffic")

    # 1. Link ownership
    link = await db.links.find_one({"id": link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    target = _rut_build_target_url(request, link, target_url)

    # 2. Validate numbers
    if total_clicks < 1 or total_clicks > 100000:
        raise HTTPException(status_code=400, detail="total_clicks must be 1..100000")
    if concurrency < 1 or concurrency > 20:
        raise HTTPException(status_code=400, detail="concurrency must be 1..20")
    if duration_minutes < 0 or duration_minutes > 1440:
        raise HTTPException(status_code=400, detail="duration_minutes must be 0..1440")

    # 2b. Target-mode validation
    target_mode = (target_mode or "clicks").strip().lower()
    if target_mode not in ("clicks", "conversions"):
        raise HTTPException(status_code=400, detail="target_mode must be 'clicks' or 'conversions'")
    if target_mode == "conversions":
        if target_conversions < 1 or target_conversions > 10000:
            raise HTTPException(status_code=400, detail="target_conversions must be 1..10000 when target_mode='conversions'")
        if max_attempts < 0 or max_attempts > 100000:
            raise HTTPException(status_code=400, detail="max_attempts must be 0..100000")
        if max_attempts and max_attempts < target_conversions:
            raise HTTPException(status_code=400, detail="max_attempts must be >= target_conversions")

    # 3. Proxies — either paste or stored
    if use_stored_proxies:
        stored = await db.proxies.find(
            {"user_id": user["id"], "status": {"$in": ["working", "active", None]}},
            {"_id": 0, "proxy_string": 1},
        ).to_list(length=5000)
        proxy_lines = [p["proxy_string"] for p in stored if p.get("proxy_string")]
        if not proxy_lines:
            raise HTTPException(status_code=400, detail="No stored proxies found. Add some in the Proxies page or paste manually.")
    else:
        proxy_lines = [ln for ln in (proxies or "").splitlines() if ln.strip()]
        if not proxy_lines:
            raise HTTPException(status_code=400, detail="At least one proxy required")

    # 4. User agents
    ua_lines = [ln for ln in (user_agents or "").splitlines() if ln.strip()]
    if not ua_lines:
        raise HTTPException(status_code=400, detail="At least one User Agent required")

    # 5. Form fill leads (only if enabled)
    rows: Optional[List[Dict[str, Any]]] = None
    if form_fill_enabled:
        if data_source == "pending_from_job" or (import_pending_from_job_id and not file and data_source != "gsheet"):
            # Load rows from a previous job's pending_leads.xlsx
            if not import_pending_from_job_id:
                raise HTTPException(status_code=400, detail="import_pending_from_job_id required for data_source=pending_from_job")
            # Verify the source job belongs to the same user
            src_job = await db.real_user_traffic_jobs.find_one(
                {"job_id": import_pending_from_job_id, "user_id": user["id"]}, {"_id": 0}
            )
            if not src_job:
                raise HTTPException(status_code=404, detail="Source job not found")
            from real_user_traffic import RESULTS_ROOT
            pending_path = Path(src_job.get("pending_leads_path") or (RESULTS_ROOT / import_pending_from_job_id / "pending_leads.xlsx"))
            if not pending_path.exists():
                raise HTTPException(status_code=404, detail="Previous job's pending_leads.xlsx not found (it may have been deleted or that job had no leads)")
            try:
                with open(pending_path, "rb") as fp:
                    content = fp.read()
                rows = load_rows_from_excel(content, pending_path.name)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Pending leads file parse failed: {e}")
        elif data_source == "gsheet":
            if not gsheet_url:
                raise HTTPException(status_code=400, detail="gsheet_url required when form fill is enabled")
            try:
                rows = await load_rows_from_google_sheet(gsheet_url)
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"Google Sheet load failed: {e}")
        else:
            if not file:
                raise HTTPException(status_code=400, detail="Excel/CSV file required when form fill is enabled")
            content = await file.read()
            try:
                rows = load_rows_from_excel(content, file.filename or "data.xlsx")
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"File parse failed: {e}")
        if not rows:
            raise HTTPException(status_code=400, detail="No rows in uploaded file")

    # 6. Duplicate-IP blocklist (global, prefetched once for speed)
    dup_ip_set = None
    if skip_duplicate_ip:
        try:
            dup_ip_set = await get_all_click_ips_from_entire_database()
        except Exception as e:
            logger.warning(f"Could not load duplicate IP set: {e}")
            dup_ip_set = set()

    # 7. Normalise filter lists
    allowed_countries_lc = [c.strip().lower() for c in (allowed_countries or "").split(",") if c.strip()]
    allowed_os_list = [o.strip().lower() for o in (allowed_os or "").split(",") if o.strip()]

    # 7b. Parse custom Automation JSON (if provided)
    automation_steps = None
    if automation_json and automation_json.strip():
        try:
            import json as _json
            parsed = _json.loads(automation_json)
            if isinstance(parsed, list):
                automation_steps = parsed
            elif isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
                automation_steps = parsed["steps"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail='automation_json must be a list of steps or {"steps":[...]}'
                )
            if not automation_steps:
                raise HTTPException(status_code=400, detail="automation_json has no steps")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid automation_json: {e}")

    # 7c. Validate post_submit_wait range
    post_submit_wait = max(3, min(15, int(post_submit_wait)))

    # 8. Create job record + schedule
    job_id = str(uuid.uuid4())
    job = create_rut_job(
        job_id=job_id,
        user_id=user["id"],
        target_url=target,
        total=total_clicks,
        form_fill_enabled=form_fill_enabled,
    )
    await db.real_user_traffic_jobs.update_one(
        {"job_id": job_id}, {"$set": {**job, "user_id": user["id"]}}, upsert=True
    )

    background.add_task(
        run_real_user_traffic_job,
        job_id=job_id,
        target_url=target,
        proxies_raw=proxy_lines,
        user_agents=ua_lines,
        total_clicks=total_clicks,
        concurrency=concurrency,
        duration_minutes=duration_minutes,
        allowed_os=allowed_os_list,
        allowed_countries_lc=allowed_countries_lc,
        skip_duplicate_ip=skip_duplicate_ip,
        skip_vpn=skip_vpn,
        follow_redirect=follow_redirect,
        no_repeated_proxy=no_repeated_proxy,
        form_fill_enabled=form_fill_enabled,
        rows=rows,
        skip_captcha=skip_captcha,
        duplicate_ip_set=dup_ip_set,
        post_submit_wait=post_submit_wait,
        automation_steps=automation_steps,
        self_heal=self_heal,
        state_match_enabled=state_match_enabled,
        target_mode=target_mode,
        target_conversions=target_conversions,
        max_attempts=max_attempts,
        invalid_detection_enabled=invalid_detection_enabled,
        db=db,
        link_id=link.get("id") if link else None,
        link_owner_id=(link or {}).get("user_id") or user["id"],
        link_short_code=(link or {}).get("short_code"),
    )
    return {
        "job_id": job_id,
        "total": total_clicks if target_mode == "clicks" else (max_attempts or target_conversions * 20),
        "target_url": target,
        "proxies": len(proxy_lines),
        "user_agents": len(ua_lines),
        "form_fill_enabled": form_fill_enabled,
        "state_match_enabled": state_match_enabled,
        "target_mode": target_mode,
        "target_conversions": target_conversions if target_mode == "conversions" else 0,
        "max_attempts": max_attempts if target_mode == "conversions" else 0,
        "imported_from_job": import_pending_from_job_id or "",
        "rows_loaded": len(rows) if rows else 0,
        "custom_automation": bool(automation_steps),
        "post_submit_wait": post_submit_wait,
        "concurrency": concurrency,
        "duration_minutes": duration_minutes,
    }


@api_router.get("/real-user-traffic/jobs")
async def rut_list_jobs(user: dict = Depends(get_current_user)):
    check_user_feature(user, "real_user_traffic")
    persisted = await db.real_user_traffic_jobs.find(
        {"user_id": user["id"]}, {"_id": 0}
    ).sort("created_at", -1).limit(50).to_list(length=50)
    return {"jobs": persisted}


# NOTE: /jobs/pending-candidates MUST be declared before /jobs/{job_id}
# because FastAPI matches routes in declaration order.
@api_router.get("/real-user-traffic/jobs/pending-candidates")
async def rut_pending_candidates_v2(user: dict = Depends(get_current_user)):
    """Return user's past completed / stopped jobs that still have UNUSED
    leads (pending_leads_count > 0). Used by the frontend dropdown for the
    'Import from previous run' data source."""
    check_user_feature(user, "real_user_traffic")
    cursor = db.real_user_traffic_jobs.find(
        {
            "user_id": user["id"],
            "status": {"$in": ["completed", "stopped"]},
            "pending_leads_count": {"$gt": 0},
        },
        {
            "_id": 0, "job_id": 1, "target_url": 1, "created_at": 1,
            "finished_at": 1, "total": 1, "succeeded": 1, "invalid_data": 1,
            "pending_leads_count": 1, "form_fill_enabled": 1,
            "state_match_enabled": 1, "link_short_code": 1,
        },
    ).sort("created_at", -1).limit(25)
    items = []
    async for j in cursor:
        items.append(j)
    return {"items": items, "count": len(items)}


@api_router.get("/real-user-traffic/jobs/{job_id}")
async def rut_get_job(job_id: str, user: dict = Depends(get_current_user)):
    check_user_feature(user, "real_user_traffic")
    j = _RUT_JOBS.get(job_id)
    if not j:
        j = await db.real_user_traffic_jobs.find_one(
            {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
        )
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return j


@api_router.get("/real-user-traffic/jobs/{job_id}/live-log")
async def rut_live_log(
    job_id: str,
    since: int = 0,
    user: dict = Depends(get_current_user),
):
    """Return live step-by-step activity log for a running job. Polled by
    the 'Show live activity' modal in the UI. Only returns new steps after
    the given cursor so traffic stays tiny. If the job is not in memory,
    returns running=False so the UI can stop polling."""
    check_user_feature(user, "real_user_traffic")
    # Ownership check — either via in-memory dict or DB
    j = _RUT_JOBS.get(job_id)
    if j is None:
        db_job = await db.real_user_traffic_jobs.find_one(
            {"job_id": job_id, "user_id": user["id"]}, {"_id": 0, "user_id": 1}
        )
        if not db_job:
            raise HTTPException(status_code=404, detail="Job not found")
    elif j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    return _rut_get_live_steps(job_id, since=int(since or 0))


@api_router.get("/real-user-traffic/jobs/{job_id}/screenshot/{filename}")
async def rut_screenshot(
    job_id: str,
    filename: str,
    request: Request,
    t: Optional[str] = None,
):
    """Serve a single visit screenshot (PNG) from the RUT results folder.
    Used by the Live Activity modal to show proof thumbnails next to each
    step. Auth is accepted via EITHER the standard Authorization header
    (for API clients) OR a ?t=<jwt> query param (so <img> tags can embed
    the URL without needing a header). Ownership is enforced against the
    in-memory job OR the DB doc. Only plain basenames are allowed — no
    path traversal."""
    # Manual auth — support both header and query-param token
    token_value = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token_value = auth_header.split(" ", 1)[1]
    elif t:
        token_value = t
    if not token_value:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        is_sub_user = payload.get("is_sub_user", False)
        parent_user_id = payload.get("parent_user_id")
        if not email:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Resolve user id (main or sub-user)
    user_id = None
    if is_sub_user and parent_user_id:
        user_id = parent_user_id
    else:
        u = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "status": 1, "features": 1})
        if not u or u.get("status") != "active" or not (u.get("features") or {}).get("real_user_traffic"):
            raise HTTPException(status_code=403, detail="Forbidden")
        user_id = u["id"]

    # Ownership
    j = _RUT_JOBS.get(job_id)
    if j is None:
        db_job = await db.real_user_traffic_jobs.find_one(
            {"job_id": job_id, "user_id": user_id}, {"_id": 0, "user_id": 1}
        )
        if not db_job:
            raise HTTPException(status_code=404, detail="Job not found")
    elif j.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Job not found")

    # Basename-only — defence against "../" path traversal
    safe = os.path.basename(filename)
    if not safe.endswith(".png") or "/" in filename or "\\" in filename or safe != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    from real_user_traffic import RESULTS_ROOT
    path = RESULTS_ROOT / job_id / "screenshots" / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Screenshot not found")
    return FileResponse(path, media_type="image/png")


@api_router.get("/real-user-traffic/jobs/{job_id}/download")
async def rut_download(job_id: str, user: dict = Depends(get_current_user)):
    check_user_feature(user, "real_user_traffic")
    j = _RUT_JOBS.get(job_id) or await db.real_user_traffic_jobs.find_one(
        {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    zip_path = j.get("zip_path")
    if not zip_path or not os.path.exists(zip_path):
        raise HTTPException(status_code=404, detail="Results not ready")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"real-user-traffic-{job_id[:8]}.zip",
    )


@api_router.get("/real-user-traffic/jobs/{job_id}/pending-leads")
async def rut_pending_leads(job_id: str, user: dict = Depends(get_current_user)):
    """Download ONLY the pending-leads Excel (used + invalid rows removed).
    This file uses the exact same schema as the originally-uploaded lead
    file so the user can upload it directly as the next run's data."""
    check_user_feature(user, "real_user_traffic")
    j = _RUT_JOBS.get(job_id) or await db.real_user_traffic_jobs.find_one(
        {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")

    from real_user_traffic import RESULTS_ROOT
    pending_path = j.get("pending_leads_path") or str(RESULTS_ROOT / job_id / "pending_leads.xlsx")
    if not os.path.exists(pending_path):
        raise HTTPException(
            status_code=404,
            detail="Pending leads file not found — this job may not have used a lead file, or it's still running",
        )
    return FileResponse(
        pending_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"pending_leads_{job_id[:8]}.xlsx",
    )


async def _package_partial_results(job_id: str, job_dir_path=None):
    """Best-effort: build results.zip from any screenshots / reports that
    already exist on disk for a job whose worker is dead / gone. Returns
    the zip path or None."""
    from real_user_traffic import RESULTS_ROOT
    import zipfile
    job_dir = job_dir_path or (RESULTS_ROOT / job_id)
    if not job_dir.exists():
        return None
    zip_path = job_dir / "results.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            shots_dir = job_dir / "screenshots"
            if shots_dir.exists():
                for p in shots_dir.glob("*.png"):
                    zf.write(p, arcname=f"screenshots/{p.name}")
            if (job_dir / "report.xlsx").exists():
                zf.write(job_dir / "report.xlsx", arcname="report.xlsx")
            if (job_dir / "leads_with_status.xlsx").exists():
                zf.write(job_dir / "leads_with_status.xlsx", arcname="leads_with_status.xlsx")
            if (job_dir / "pending_leads.xlsx").exists():
                zf.write(job_dir / "pending_leads.xlsx", arcname="pending_leads.xlsx")
        return str(zip_path)
    except Exception as e:
        logger.warning(f"Partial zip build failed for {job_id}: {e}")
        return None


@api_router.post("/real-user-traffic/jobs/{job_id}/stop")
async def rut_stop_job(job_id: str, user: dict = Depends(get_current_user)):
    """Signal a running job to stop. In-flight visits finish their current
    step then exit; remaining visits are skipped. Partial ZIP + Excel are
    built automatically at the end. Idempotent — safe to call twice."""
    check_user_feature(user, "real_user_traffic")
    j = _RUT_JOBS.get(job_id)
    j_db = await db.real_user_traffic_jobs.find_one(
        {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not j and not j_db:
        raise HTTPException(status_code=404, detail="Job not found")
    if j_db and j_db.get("user_id") not in (None, user["id"]):
        raise HTTPException(status_code=404, detail="Job not found")

    # Case 1: Job entry exists in this worker → normal cooperative cancel
    if j:
        if j.get("user_id") != user["id"]:
            raise HTTPException(status_code=404, detail="Job not found")
        if j.get("status") in ("completed", "failed", "stopped"):
            return {"stopped": False, "message": "Job already finished", "status": j.get("status")}
        ok = request_job_cancel(job_id)
        return {
            "stopped": ok,
            "message": "Stop signal sent — partial results will be packaged shortly"
                       if ok else "Could not signal (job may have just finished)",
        }

    # Case 2: Only DB knows about the job (worker reloaded / task died).
    if j_db.get("status") in ("completed", "failed", "stopped"):
        return {"stopped": False, "message": "Job already finished", "status": j_db.get("status")}

    # Try to package whatever partial output exists on disk.
    zip_path = await _package_partial_results(job_id)

    updates = {
        "status": "stopped",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "stop_reason": "Worker died; partial results packaged on stop.",
    }
    if zip_path:
        updates["zip_path"] = zip_path

    await db.real_user_traffic_jobs.update_one(
        {"job_id": job_id, "user_id": user["id"]},
        {"$set": updates},
    )
    return {
        "stopped": True,
        "status": "stopped",
        "message": "Job was not running in this worker; marked stopped and partial results packaged"
                   if zip_path else "Job was not running in this worker; marked stopped (no partial results on disk)",
        "has_results": bool(zip_path),
    }


@api_router.delete("/real-user-traffic/jobs/{job_id}")
async def rut_delete(job_id: str, user: dict = Depends(get_current_user)):
    check_user_feature(user, "real_user_traffic")
    j = _RUT_JOBS.get(job_id) or await db.real_user_traffic_jobs.find_one(
        {"job_id": job_id, "user_id": user["id"]}, {"_id": 0}
    )
    if not j or j.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Job not found")
    cleanup_rut_job(job_id)
    await db.real_user_traffic_jobs.delete_one(
        {"job_id": job_id, "user_id": user["id"]}
    )
    return {"message": "Deleted"}


@api_router.post("/real-user-traffic/jobs/bulk-delete")
async def rut_bulk_delete(
    payload: dict = Body(...),
    user: dict = Depends(get_current_user),
):
    """Delete many jobs at once — `{"job_ids": ["id1","id2",...]}`."""
    check_user_feature(user, "real_user_traffic")
    job_ids = payload.get("job_ids") or []
    if not isinstance(job_ids, list) or not job_ids:
        raise HTTPException(status_code=400, detail="job_ids must be a non-empty list")
    deleted = 0
    for jid in job_ids:
        if not isinstance(jid, str):
            continue
        j = _RUT_JOBS.get(jid) or await db.real_user_traffic_jobs.find_one(
            {"job_id": jid, "user_id": user["id"]}, {"_id": 0}
        )
        if j and j.get("user_id") == user["id"]:
            cleanup_rut_job(jid)
            await db.real_user_traffic_jobs.delete_one({"job_id": jid, "user_id": user["id"]})
            deleted += 1
    return {"deleted": deleted, "requested": len(job_ids)}


# ── AI Automation Generator ─────────────────────────────────────────
import tempfile

@api_router.post("/real-user-traffic/ai-generate-automation")
async def rut_ai_generate_automation(
    target_url: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    excel_columns: Optional[str] = Form(None),  # comma-separated
    files: List[UploadFile] = File(...),
    user: dict = Depends(get_current_user),
):
    """
    Upload 1-15 screenshots and/or 1 short video (mp4/mov/webm).
    Gemini 2.5 Pro analyses the flow and returns a Custom Automation JSON
    step-list compatible with the Real User Traffic runner.

    Response: {"status":"ok","steps":[...],"raw":"<model text>"} or
              {"status":"failed","error":"..."}.
    """
    check_user_feature(user, "real_user_traffic")

    from ai_automation_generator import (
        generate_automation_from_media,
        classify_upload,
        MAX_IMAGES,
        MAX_VIDEO_BYTES,
    )

    if not files:
        raise HTTPException(status_code=400, detail="At least one screenshot or video is required")

    workdir = Path(tempfile.mkdtemp(prefix="rut_ai_"))
    image_paths: List[str] = []
    video_path: Optional[str] = None
    try:
        for up in files:
            kind = classify_upload(up.filename or "")
            if kind is None:
                continue
            data = await up.read()
            if kind == "video":
                if len(data) > MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=400,
                        detail=f"Video exceeds {MAX_VIDEO_BYTES // (1024*1024)} MB limit")
                if video_path is not None:
                    raise HTTPException(status_code=400, detail="Only one video per request")
                dest = workdir / (up.filename or f"video_{uuid.uuid4().hex[:6]}.mp4")
                dest.write_bytes(data)
                video_path = str(dest)
            else:  # image
                if len(image_paths) >= MAX_IMAGES:
                    continue
                dest = workdir / (up.filename or f"img_{uuid.uuid4().hex[:6]}.png")
                dest.write_bytes(data)
                image_paths.append(str(dest))

        if not image_paths and not video_path:
            raise HTTPException(status_code=400,
                detail="No valid image/video files (accepted: png, jpg, jpeg, webp, mp4, mov, webm, mpeg, avi)")

        cols: Optional[List[str]] = None
        if excel_columns:
            cols = [c.strip() for c in excel_columns.split(",") if c.strip()]

        result = await generate_automation_from_media(
            image_paths=image_paths,
            video_path=video_path,
            target_url=(target_url or None),
            description=(description or None),
            excel_columns=cols,
        )
        return result
    finally:
        # Clean temp files
        try:
            for p in image_paths:
                try: os.remove(p)
                except Exception: pass
            if video_path:
                try: os.remove(video_path)
                except Exception: pass
            try: workdir.rmdir()
            except Exception: pass
        except Exception:
            pass


# ==================== API SETTINGS MANAGEMENT ====================

@api_router.get("/admin/api-settings")
async def get_api_settings(admin: dict = Depends(get_current_admin)):
    """Get all API settings for VPN detection services"""
    settings = await main_db.settings.find_one({"key": "api_settings"}, {"_id": 0})
    if settings and "value" in settings:
        return settings["value"]
    return DEFAULT_API_SETTINGS

@api_router.put("/admin/api-settings/{api_key}")
async def update_api_setting(api_key: str, update: APISettingUpdate, admin: dict = Depends(get_current_admin)):
    """Update a specific API setting"""
    # Get current settings
    settings = await main_db.settings.find_one({"key": "api_settings"})
    if settings and "value" in settings:
        current_settings = settings["value"]
    else:
        current_settings = DEFAULT_API_SETTINGS.copy()
    
    # Check if API key exists
    if api_key not in current_settings:
        raise HTTPException(status_code=404, detail=f"API setting '{api_key}' not found")
    
    # Update only provided fields
    update_data = update.dict(exclude_none=True)
    for key, value in update_data.items():
        current_settings[api_key][key] = value
    
    current_settings[api_key]["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    # Save to database
    await main_db.settings.update_one(
        {"key": "api_settings"},
        {"$set": {"key": "api_settings", "value": current_settings}},
        upsert=True
    )
    
    logger.info(f"API setting '{api_key}' updated by admin")
    return {"message": f"API setting '{api_key}' updated successfully", "setting": current_settings[api_key]}

@api_router.post("/admin/api-settings")
async def create_custom_api(api_data: CustomAPICreate, admin: dict = Depends(get_current_admin)):
    """Create a new custom API setting"""
    # Get current settings
    settings = await main_db.settings.find_one({"key": "api_settings"})
    if settings and "value" in settings:
        current_settings = settings["value"]
    else:
        current_settings = DEFAULT_API_SETTINGS.copy()
    
    # Check if key already exists
    if api_data.key in current_settings:
        raise HTTPException(status_code=400, detail=f"API setting '{api_data.key}' already exists")
    
    # Add new API setting
    current_settings[api_data.key] = {
        "name": api_data.name,
        "enabled": api_data.enabled,
        "api_key": api_data.api_key,
        "endpoint": api_data.endpoint,
        "priority": api_data.priority,
        "description": api_data.description,
        "is_custom": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Save to database
    await main_db.settings.update_one(
        {"key": "api_settings"},
        {"$set": {"key": "api_settings", "value": current_settings}},
        upsert=True
    )
    
    logger.info(f"Custom API setting '{api_data.key}' created by admin")
    return {"message": f"API setting '{api_data.key}' created successfully", "setting": current_settings[api_data.key]}

@api_router.delete("/admin/api-settings/{api_key}")
async def delete_api_setting(api_key: str, admin: dict = Depends(get_current_admin)):
    """Delete a custom API setting (only custom APIs can be deleted)"""
    # Get current settings
    settings = await main_db.settings.find_one({"key": "api_settings"})
    if not settings or "value" not in settings:
        raise HTTPException(status_code=404, detail="No API settings found")
    
    current_settings = settings["value"]
    
    if api_key not in current_settings:
        raise HTTPException(status_code=404, detail=f"API setting '{api_key}' not found")
    
    # Only allow deleting custom APIs
    if not current_settings[api_key].get("is_custom", False):
        raise HTTPException(status_code=400, detail="Cannot delete built-in API settings. You can disable them instead.")
    
    del current_settings[api_key]
    
    # Save to database
    await main_db.settings.update_one(
        {"key": "api_settings"},
        {"$set": {"key": "api_settings", "value": current_settings}},
        upsert=True
    )
    
    logger.info(f"Custom API setting '{api_key}' deleted by admin")
    return {"message": f"API setting '{api_key}' deleted successfully"}

@api_router.post("/admin/api-settings/reset")
async def reset_api_settings(admin: dict = Depends(get_current_admin)):
    """Reset API settings to default (keeps custom APIs)"""
    # Get current settings to preserve custom APIs
    settings = await main_db.settings.find_one({"key": "api_settings"})
    custom_apis = {}
    if settings and "value" in settings:
        for key, value in settings["value"].items():
            if value.get("is_custom", False):
                custom_apis[key] = value
    
    # Reset to default and add back custom APIs
    reset_settings = DEFAULT_API_SETTINGS.copy()
    reset_settings.update(custom_apis)
    
    await main_db.settings.update_one(
        {"key": "api_settings"},
        {"$set": {"key": "api_settings", "value": reset_settings}},
        upsert=True
    )
    
    logger.info(f"API settings reset to default by admin")
    return {"message": "API settings reset to default", "settings": reset_settings}

@api_router.post("/admin/api-settings/test/{api_key}")
async def test_api_setting(api_key: str, admin: dict = Depends(get_current_admin)):
    """Test an API setting with a sample IP"""
    # Get current settings
    settings = await main_db.settings.find_one({"key": "api_settings"})
    if not settings or "value" not in settings:
        current_settings = DEFAULT_API_SETTINGS
    else:
        current_settings = settings["value"]
    
    if api_key not in current_settings:
        raise HTTPException(status_code=404, detail=f"API setting '{api_key}' not found")
    
    api_config = current_settings[api_key]
    test_ip = "8.8.8.8"  # Google DNS - known clean IP
    
    try:
        async with httpx.AsyncClient() as client:
            if api_key == "proxycheck":
                url = f"{api_config['endpoint']}{test_ip}?vpn=1"
                if api_config.get("api_key"):
                    url += f"&key={api_config['api_key']}"
                response = await client.get(url, timeout=10)
                data = response.json()
                return {"success": True, "response": data, "message": "API is working"}
            
            elif api_key == "ipapi":
                url = f"{api_config['endpoint']}{test_ip}?fields=status,country,proxy,hosting"
                response = await client.get(url, timeout=10)
                data = response.json()
                return {"success": True, "response": data, "message": "API is working"}
            
            elif api_key == "ipqualityscore":
                if not api_config.get("api_key"):
                    return {"success": False, "message": "API key required for IPQualityScore"}
                url = f"{api_config['endpoint']}{api_config['api_key']}/{test_ip}"
                response = await client.get(url, timeout=10)
                data = response.json()
                return {"success": True, "response": data, "message": "API is working"}
            
            elif api_key == "iphub":
                if not api_config.get("api_key"):
                    return {"success": False, "message": "API key required for IPHub"}
                headers = {"X-Key": api_config["api_key"]}
                url = f"{api_config['endpoint']}{test_ip}"
                response = await client.get(url, headers=headers, timeout=10)
                data = response.json()
                return {"success": True, "response": data, "message": "API is working"}
            
            else:
                # Generic test for custom APIs
                url = api_config['endpoint']
                if "{ip}" in url:
                    url = url.replace("{ip}", test_ip)
                else:
                    url = f"{url}{test_ip}"
                response = await client.get(url, timeout=10)
                return {"success": True, "status_code": response.status_code, "message": "API responded"}
                
    except Exception as e:
        return {"success": False, "message": f"API test failed: {str(e)}"}

@api_router.get("/admin/api-settings/status")
async def get_api_status(admin: dict = Depends(get_current_admin)):
    """Get current status of all APIs including rate limit status and usage"""
    global _api_rate_limits
    
    # Get API settings
    settings = await main_db.settings.find_one({"key": "api_settings"})
    if settings and "value" in settings:
        api_settings = settings["value"]
    else:
        api_settings = DEFAULT_API_SETTINGS
    
    # Load current usage
    usage = await get_api_usage()
    
    current_time = time.time()
    status_list = []
    total_used_today = 0
    total_limit_today = 0
    
    for api_key, config in sorted(api_settings.items(), key=lambda x: x[1].get("priority", 99)):
        rate_limited = False
        rate_limit_remaining = 0
        
        if api_key in _api_rate_limits:
            elapsed = current_time - _api_rate_limits[api_key]
            if elapsed < _api_rate_limit_reset:
                rate_limited = True
                rate_limit_remaining = int(_api_rate_limit_reset - elapsed)
            else:
                del _api_rate_limits[api_key]
        
        # Get usage stats
        daily_limit = API_DAILY_LIMITS.get(api_key, 10000)
        used_today = usage.get(api_key, 0)
        remaining = max(0, daily_limit - used_today)
        limit_reached = used_today >= daily_limit
        
        if config.get("enabled", False):
            total_used_today += used_today
            total_limit_today += daily_limit
        
        status_list.append({
            "key": api_key,
            "name": config.get("name", api_key),
            "enabled": config.get("enabled", False),
            "priority": config.get("priority", 99),
            "rate_limited": rate_limited,
            "rate_limit_resets_in": rate_limit_remaining,
            "has_api_key": bool(config.get("api_key")),
            # Usage stats
            "daily_limit": daily_limit,
            "used_today": used_today,
            "remaining": remaining,
            "limit_reached": limit_reached,
            "usage_percent": round((used_today / daily_limit) * 100, 1) if daily_limit > 0 else 0
        })
    
    return {
        "apis": status_list,
        "total_enabled": sum(1 for s in status_list if s["enabled"]),
        "total_rate_limited": sum(1 for s in status_list if s["rate_limited"]),
        "total_limit_reached": sum(1 for s in status_list if s["limit_reached"] and s["enabled"]),
        "total_used_today": total_used_today,
        "total_limit_today": total_limit_today,
        "date": get_today_date()
    }

@api_router.post("/admin/api-settings/reset-usage")
async def reset_api_usage(admin: dict = Depends(get_current_admin)):
    """Reset daily API usage counters (useful for testing)"""
    global _api_usage, _api_usage_date
    _api_usage = {}
    _api_usage_date = get_today_date()
    await main_db.settings.update_one(
        {"key": "api_usage"},
        {"$set": {"key": "api_usage", "date": _api_usage_date, "usage": {}}},
        upsert=True
    )
    logger.info("API usage counters reset by admin")
    return {"message": "API usage counters reset successfully"}

@api_router.post("/admin/api-settings/clear-rate-limits")
async def clear_api_rate_limits(admin: dict = Depends(get_current_admin)):
    """Clear all rate limit flags (useful after waiting period)"""
    global _api_rate_limits
    cleared_count = len(_api_rate_limits)
    _api_rate_limits = {}
    logger.info(f"Cleared {cleared_count} API rate limits")
    return {"message": f"Cleared rate limits for {cleared_count} APIs"}

# ==================== IP LIST IMPORT ====================

@api_router.post("/clicks/import-ips")
async def import_clicks_from_ips(data: IPListImport, user: dict = Depends(get_current_user_with_fresh_data)):
    """Import clicks from a list of IP addresses. Link is optional. Supports unlimited IPs."""
    check_user_feature(user, "import_traffic")
    
    try:
        link_id = None
        link = None
        
        # If link_id provided, verify it belongs to user
        if data.link_id:
            link_query = {"id": data.link_id, "user_id": user["id"]}
            # Sub-users can only use their own links
            if user.get("is_sub_user"):
                link_query["created_by"] = user.get("sub_user_id")
            link = await db.links.find_one(link_query)
            if not link:
                raise HTTPException(status_code=404, detail="Link not found")
            link_id = data.link_id
        else:
            # Create or get a "general" tracking link for IP-only imports
            general_query = {"user_id": user["id"], "name": "_IP_TRACKING_"}
            if user.get("is_sub_user"):
                general_query["created_by"] = user.get("sub_user_id")
            
            general_link = await db.links.find_one(general_query)
            if not general_link:
                general_link = {
                    "id": str(uuid.uuid4()),
                    "short_code": f"ip-{str(uuid.uuid4())[:8]}",
                    "offer_url": "",
                    "name": "_IP_TRACKING_",
                    "status": "active",
                    "user_id": user["id"],
                    "created_by": user.get("sub_user_id") if user.get("is_sub_user") else None,
                    "clicks": 0,
                    "conversions": 0,
                    "revenue": 0.0,
                    "allowed_countries": [],
                    "block_vpn": False,
                    "prevent_duplicates": False,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await db.links.insert_one(general_link)
            link_id = general_link["id"]
        
        # Bulk insert for better performance
        click_docs = []
        now = datetime.now(timezone.utc).isoformat()
        
        for ip in data.ip_list:
            ip = ip.strip()
            if not ip:
                continue
            
            click_docs.append({
                "id": str(uuid.uuid4()),
                "click_id": str(uuid.uuid4()),
                "link_id": link_id,
                "ip_address": ip,
                "country": data.country,
                "is_vpn": False,
                "is_proxy": False,
                "user_agent": "Imported",
                "referrer": "",
                "device": "Unknown",
                "device_type": "Unknown",
                "os_name": "Unknown",
                "os_version": "",
                "browser": "Unknown",
                "sub1": None,
                "sub2": None,
                "sub3": None,
                "created_at": now
            })
        
        imported_count = 0
        if click_docs:
            # Bulk insert in batches of 5000 for optimal performance (reduced batch size)
            batch_size = 5000
            for i in range(0, len(click_docs), batch_size):
                batch = click_docs[i:i + batch_size]
                try:
                    await db.clicks.insert_many(batch, ordered=False)
                    imported_count += len(batch)
                except Exception as batch_error:
                    logger.error(f"Error inserting batch {i}-{i+batch_size}: {batch_error}")
                    # Continue with next batch
        
        # Update link click count
        if imported_count > 0:
            await db.links.update_one({"id": link_id}, {"$inc": {"clicks": imported_count}})
        
        return {"message": f"Successfully imported {imported_count} clicks", "imported": imported_count}
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing clicks from IPs: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

# ==================== BULK TRAFFIC IMPORT WITH USER AGENTS ====================

# Sample Instagram User Agents for random selection
INSTAGRAM_USER_AGENTS = [
    # iPhone Instagram
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 302.0.0.34.111", "device": "iPhone", "brand": "Apple", "os": "iOS", "os_version": "17.0", "browser": "Instagram", "browser_version": "302.0.0"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 298.0.0.31.115", "device": "iPhone", "brand": "Apple", "os": "iOS", "os_version": "16.6", "browser": "Instagram", "browser_version": "298.0.0"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 305.0.0.36.109", "device": "iPhone", "brand": "Apple", "os": "iOS", "os_version": "17.1", "browser": "Instagram", "browser_version": "305.0.0"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 295.0.0.28.106", "device": "iPhone 14 Pro", "brand": "Apple", "os": "iOS", "os_version": "16.5", "browser": "Instagram", "browser_version": "295.0.0"},
    {"ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 310.0.0.38.112", "device": "iPhone 15", "brand": "Apple", "os": "iOS", "os_version": "17.2", "browser": "Instagram", "browser_version": "310.0.0"},
    # iPad Instagram
    {"ua": "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram 302.0.0.34.111", "device": "iPad", "brand": "Apple", "os": "iOS", "os_version": "17.0", "browser": "Instagram", "browser_version": "302.0.0"},
    # Android Instagram - Samsung
    {"ua": "Mozilla/5.0 (Linux; Android 14; Samsung Galaxy S24) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111", "device": "Galaxy S24", "brand": "Samsung", "os": "Android", "os_version": "14", "browser": "Instagram", "browser_version": "302.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Samsung Galaxy S23 Ultra) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36 Instagram 298.0.0.31.115", "device": "Galaxy S23 Ultra", "brand": "Samsung", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "298.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Samsung Galaxy A54) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36 Instagram 295.0.0.28.106", "device": "Galaxy A54", "brand": "Samsung", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "295.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 12; Samsung Galaxy A52) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36 Instagram 290.0.0.25.102", "device": "Galaxy A52", "brand": "Samsung", "os": "Android", "os_version": "12", "browser": "Instagram", "browser_version": "290.0.0"},
    # Android Instagram - Google Pixel
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111", "device": "Pixel 8 Pro", "brand": "Google", "os": "Android", "os_version": "14", "browser": "Instagram", "browser_version": "302.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 300.0.0.32.108", "device": "Pixel 8", "brand": "Google", "os": "Android", "os_version": "14", "browser": "Instagram", "browser_version": "300.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36 Instagram 298.0.0.31.115", "device": "Pixel 7", "brand": "Google", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "298.0.0"},
    # Android Instagram - OnePlus
    {"ua": "Mozilla/5.0 (Linux; Android 14; OnePlus 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111", "device": "OnePlus 12", "brand": "OnePlus", "os": "Android", "os_version": "14", "browser": "Instagram", "browser_version": "302.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; OnePlus 11) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36 Instagram 295.0.0.28.106", "device": "OnePlus 11", "brand": "OnePlus", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "295.0.0"},
    # Android Instagram - Xiaomi
    {"ua": "Mozilla/5.0 (Linux; Android 14; Xiaomi 14 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 Instagram 302.0.0.34.111", "device": "Xiaomi 14 Pro", "brand": "Xiaomi", "os": "Android", "os_version": "14", "browser": "Instagram", "browser_version": "302.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Mobile Safari/537.36 Instagram 290.0.0.25.102", "device": "Redmi Note 12", "brand": "Xiaomi", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "290.0.0"},
    # Android Instagram - Oppo/Vivo
    {"ua": "Mozilla/5.0 (Linux; Android 13; OPPO Find X6 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36 Instagram 298.0.0.31.115", "device": "Find X6 Pro", "brand": "OPPO", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "298.0.0"},
    {"ua": "Mozilla/5.0 (Linux; Android 13; vivo X90 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Mobile Safari/537.36 Instagram 295.0.0.28.106", "device": "X90 Pro", "brand": "Vivo", "os": "Android", "os_version": "13", "browser": "Instagram", "browser_version": "295.0.0"},
    # Android Instagram - Huawei
    {"ua": "Mozilla/5.0 (Linux; Android 12; HUAWEI P50 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36 Instagram 285.0.0.22.99", "device": "P50 Pro", "brand": "Huawei", "os": "Android", "os_version": "12", "browser": "Instagram", "browser_version": "285.0.0"},
]

# Sample countries with realistic distribution
SAMPLE_COUNTRIES = [
    "United States", "United States", "United States",  # Higher weight
    "United Kingdom", "United Kingdom",
    "Canada", "Canada",
    "Australia",
    "Germany", "France", "Italy", "Spain", "Netherlands",
    "India", "India", "Pakistan", "Bangladesh",
    "Brazil", "Mexico", "Argentina",
    "Japan", "South Korea", "Indonesia", "Philippines", "Thailand", "Vietnam",
    "United Arab Emirates", "Saudi Arabia", "Turkey",
    "Nigeria", "South Africa", "Egypt", "Kenya"
]

class BulkClickImport(BaseModel):
    link_id: str
    clicks: List[dict]  # [{"ip": "1.2.3.4", "user_agent": "...", "country": "US"}, ...]

class BulkTrafficGenerate(BaseModel):
    link_id: str
    count: int = 10  # Number of clicks to generate
    ip_list: Optional[List[str]] = None  # Optional: provide your own IPs
    countries: Optional[List[str]] = None  # Optional: specific countries

@api_router.post("/clicks/import-bulk")
async def import_bulk_clicks(data: BulkClickImport, user: dict = Depends(get_current_user_with_fresh_data)):
    """
    Import bulk clicks with full details: IP, User Agent, Country.
    Each click will have proper device/browser detection from user agent.
    """
    check_user_feature(user, "import_traffic")
    
    try:
        # Verify link belongs to user
        link_query = {"id": data.link_id, "user_id": user["id"]}
        if user.get("is_sub_user"):
            link_query["created_by"] = user.get("sub_user_id")
        link = await db.links.find_one(link_query)
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Get user's database
        main_user_id = user.get("parent_user_id") if user.get("is_sub_user") else user["id"]
        user_db = get_user_db(main_user_id)
        
        # Get forced source from link
        forced_source = link.get("forced_source", "instagram")
        forced_source_name = link.get("forced_source_name", "Instagram")
        
        click_docs = []
        now = datetime.now(timezone.utc)
        
        for i, click_data in enumerate(data.clicks):
            ip = click_data.get("ip", "").strip()
            if not ip:
                continue
            
            user_agent = click_data.get("user_agent", "")
            country = click_data.get("country", "Unknown")
            
            # Parse user agent for device info
            device_info = detect_device(user_agent)
            
            # Create click document
            click_doc = {
                "id": str(uuid.uuid4()),
                "click_id": str(uuid.uuid4()),
                "link_id": data.link_id,
                "user_id": main_user_id,
                "created_by": link.get("created_by"),
                "ip_address": ip,
                "ipv4": ip if is_ipv4(ip) else None,
                "all_ips": [ip],
                "proxy_ips": [],
                "country": normalize_country(country),
                "city": click_data.get("city", ""),
                "region": click_data.get("region", ""),
                "lat": click_data.get("lat", 0),
                "lon": click_data.get("lon", 0),
                "isp": click_data.get("isp", ""),
                "is_vpn": False,
                "is_proxy": False,
                "is_duplicate_proxy": False,
                "vpn_score": 0,
                "user_agent": user_agent,
                "user_agent_raw": user_agent,
                "referrer": "",
                "referrer_source": forced_source or "instagram",
                "referrer_source_name": forced_source_name or "Instagram",
                "referrer_domain": "instagram.com",
                "referrer_detected_from": "imported",
                "forced_source": forced_source,
                "device": device_info["device_type"],
                "device_type": device_info["device_type"],
                "device_brand": device_info.get("device_brand", "Unknown"),
                "device_model": device_info.get("device_model", "Unknown"),
                "device_display": device_info.get("device_display", device_info["device_type"]),
                "os_name": device_info["os_name"],
                "os_version": device_info["os_version"],
                "browser": device_info["browser"],
                "browser_version": device_info.get("browser_version", ""),
                "browser_display": device_info.get("browser_display", device_info["browser"]),
                "sub1": click_data.get("sub1"),
                "sub2": click_data.get("sub2"),
                "sub3": click_data.get("sub3"),
                # Spread timestamps across last hour for realistic distribution
                "created_at": (now - timedelta(seconds=i * 30)).isoformat()
            }
            click_docs.append(click_doc)
        
        imported_count = 0
        if click_docs:
            # Insert in batches
            batch_size = 1000
            for i in range(0, len(click_docs), batch_size):
                batch = click_docs[i:i + batch_size]
                try:
                    await user_db.clicks.insert_many(batch, ordered=False)
                    imported_count += len(batch)
                except Exception as e:
                    logger.error(f"Batch insert error: {e}")
        
        # Update link click count
        if imported_count > 0:
            await db.links.update_one({"id": data.link_id}, {"$inc": {"clicks": imported_count}})
        
        return {
            "message": f"Successfully imported {imported_count} clicks",
            "imported": imported_count,
            "link_id": data.link_id
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk import error: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@api_router.post("/clicks/generate-traffic")
async def generate_traffic(data: BulkTrafficGenerate, user: dict = Depends(get_current_user_with_fresh_data)):
    """
    Generate realistic Instagram traffic with random user agents and devices.
    Provide your own IP list or let the system generate random IPs.
    """
    check_user_feature(user, "import_traffic")
    
    import random
    
    try:
        # Verify link
        link_query = {"id": data.link_id, "user_id": user["id"]}
        if user.get("is_sub_user"):
            link_query["created_by"] = user.get("sub_user_id")
        link = await db.links.find_one(link_query)
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        
        # Get user's database
        main_user_id = user.get("parent_user_id") if user.get("is_sub_user") else user["id"]
        user_db = get_user_db(main_user_id)
        
        # Get forced source
        forced_source = link.get("forced_source", "instagram")
        forced_source_name = link.get("forced_source_name", "Instagram")
        
        # Prepare IPs
        if data.ip_list and len(data.ip_list) > 0:
            ips = data.ip_list[:data.count]  # Use provided IPs
            # If not enough IPs, cycle through them
            while len(ips) < data.count:
                ips.extend(data.ip_list[:min(data.count - len(ips), len(data.ip_list))])
        else:
            # Generate random IPs
            ips = [f"{random.randint(1,223)}.{random.randint(0,255)}.{random.randint(0,255)}.{random.randint(1,254)}" 
                   for _ in range(data.count)]
        
        # Countries to use
        countries = data.countries if data.countries else SAMPLE_COUNTRIES
        
        click_docs = []
        now = datetime.now(timezone.utc)
        
        for i in range(min(data.count, len(ips))):
            ip = ips[i].strip()
            
            # Pick random user agent
            ua_data = random.choice(INSTAGRAM_USER_AGENTS)
            user_agent = ua_data["ua"]
            
            # Pick random country
            country = random.choice(countries)
            
            click_doc = {
                "id": str(uuid.uuid4()),
                "click_id": str(uuid.uuid4()),
                "link_id": data.link_id,
                "user_id": main_user_id,
                "created_by": link.get("created_by"),
                "ip_address": ip,
                "ipv4": ip,
                "all_ips": [ip],
                "proxy_ips": [],
                "country": normalize_country(country),
                "city": "",
                "region": "",
                "lat": 0,
                "lon": 0,
                "isp": "",
                "is_vpn": False,
                "is_proxy": False,
                "is_duplicate_proxy": False,
                "vpn_score": 0,
                "user_agent": user_agent,
                "user_agent_raw": user_agent,
                "referrer": "",
                "referrer_source": forced_source or "instagram",
                "referrer_source_name": forced_source_name or "Instagram",
                "referrer_domain": "instagram.com",
                "referrer_detected_from": "generated",
                "forced_source": forced_source,
                "device": "mobile",
                "device_type": "mobile",
                "device_brand": ua_data.get("brand", "Unknown"),
                "device_model": ua_data.get("device", "Unknown"),
                "device_display": f"{ua_data.get('brand', '')} {ua_data.get('device', '')}".strip(),
                "os_name": ua_data.get("os", "Unknown"),
                "os_version": ua_data.get("os_version", ""),
                "browser": ua_data.get("browser", "Instagram"),
                "browser_version": ua_data.get("browser_version", ""),
                "browser_display": f"{ua_data.get('browser', 'Instagram')} {ua_data.get('browser_version', '')}".strip(),
                "sub1": None,
                "sub2": None,
                "sub3": None,
                # Random timestamps in last 24 hours
                "created_at": (now - timedelta(seconds=random.randint(0, 86400))).isoformat()
            }
            click_docs.append(click_doc)
        
        generated_count = 0
        if click_docs:
            batch_size = 1000
            for i in range(0, len(click_docs), batch_size):
                batch = click_docs[i:i + batch_size]
                try:
                    await user_db.clicks.insert_many(batch, ordered=False)
                    generated_count += len(batch)
                except Exception as e:
                    logger.error(f"Batch insert error: {e}")
        
        # Update link click count
        if generated_count > 0:
            await db.links.update_one({"id": data.link_id}, {"$inc": {"clicks": generated_count}})
        
        return {
            "message": f"Successfully generated {generated_count} clicks",
            "generated": generated_count,
            "link_id": data.link_id,
            "sample_devices": list(set([c["device_display"] for c in click_docs[:10]]))
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Traffic generation error: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")

@api_router.get("/clicks/sample-user-agents")
async def get_sample_user_agents(user: dict = Depends(get_current_user)):
    """Get list of sample Instagram user agents for reference"""
    return {
        "user_agents": INSTAGRAM_USER_AGENTS,
        "total": len(INSTAGRAM_USER_AGENTS),
        "countries": list(set(SAMPLE_COUNTRIES))
    }

# ==================== EMAIL PROFILE CHECKER ====================

from starlette.responses import StreamingResponse
import hashlib

class EmailCheckRequest(BaseModel):
    emails: List[str]
    check_mode: Optional[str] = "all"  # "contacts_only" = Google People API only | "all" = Google + free fallbacks


class EmailDownloadRequest(BaseModel):
    rows: Optional[List[Dict[str, Any]]] = None     # original uploaded rows (preserved)
    columns: Optional[List[str]] = None             # original column order
    email_column: Optional[str] = None              # which column holds the email
    results: Dict[str, Dict[str, Any]]              # { email_lower: {has_pic, pic_url, method} }

# Google OAuth for Profile Picture Checking
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "")

# Store Google OAuth tokens in memory (in production, use database)
google_oauth_tokens = {}

@api_router.get("/google/auth-url")
async def get_google_auth_url(user: dict = Depends(get_current_user)):
    """Get Google OAuth URL for profile picture checking"""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Google OAuth not configured. Please set GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, and GOOGLE_REDIRECT_URI in environment variables.")
    
    # Scopes needed for People API
    scopes = [
        "https://www.googleapis.com/auth/contacts.readonly",
        "https://www.googleapis.com/auth/directory.readonly",
        "https://www.googleapis.com/auth/userinfo.email"
    ]
    
    state = user["id"]  # Use user ID as state to link back
    
    auth_url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={GOOGLE_CLIENT_ID}&"
        f"redirect_uri={GOOGLE_REDIRECT_URI}&"
        f"response_type=code&"
        f"scope={'+'.join(scopes)}&"
        f"access_type=offline&"
        f"state={state}&"
        f"prompt=consent"
    )
    
    return {"auth_url": auth_url}

@api_router.get("/google/callback")
async def google_oauth_callback(code: str, state: str):
    """Handle Google OAuth callback"""
    import aiohttp
    
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=400, detail="Google OAuth not configured")
    
    # Exchange code for tokens
    token_url = "https://oauth2.googleapis.com/token"
    
    async with aiohttp.ClientSession() as session:
        async with session.post(token_url, data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code"
        }) as resp:
            if resp.status != 200:
                error = await resp.text()
                raise HTTPException(status_code=400, detail=f"Failed to get tokens: {error}")
            
            tokens = await resp.json()
    
    # Store tokens for this user
    user_id = state
    google_email = None
    try:
        # Fetch the Google user's email using the access token
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {tokens.get('access_token')}"},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as uresp:
                if uresp.status == 200:
                    udata = await uresp.json()
                    google_email = udata.get("email")
    except Exception as e:
        logger.debug(f"Failed to fetch google userinfo: {e}")

    google_oauth_tokens[user_id] = {
        "access_token": tokens.get("access_token"),
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": datetime.now(timezone.utc).timestamp() + tokens.get("expires_in", 3600),
        "google_email": google_email,
    }
    
    # Return HTML that closes the popup and notifies parent
    return Response(
        content="""
        <html>
        <body>
        <script>
            window.opener.postMessage({type: 'google_auth_success'}, '*');
            window.close();
        </script>
        <p>Google account connected! You can close this window.</p>
        </body>
        </html>
        """,
        media_type="text/html"
    )

@api_router.get("/google/status")
async def google_auth_status(user: dict = Depends(get_current_user)):
    """Check if user has connected Google account (and which one)."""
    user_id = user["id"]
    token_data = google_oauth_tokens.get(user_id)
    
    if not token_data:
        return {"connected": False, "email": None}
    
    # Check if token is expired
    if token_data.get("expires_at", 0) < datetime.now(timezone.utc).timestamp():
        # Try to refresh
        if token_data.get("refresh_token"):
            try:
                await refresh_google_token(user_id)
                token_data = google_oauth_tokens.get(user_id)
            except Exception:
                return {"connected": False, "email": None}
        else:
            return {"connected": False, "email": None}
    
    return {
        "connected": True,
        "email": token_data.get("google_email") if token_data else None,
    }


@api_router.post("/google/disconnect")
async def google_auth_disconnect(user: dict = Depends(get_current_user)):
    """Disconnect/forget the connected Google account for this user."""
    import aiohttp
    user_id = user["id"]
    token_data = google_oauth_tokens.pop(user_id, None)

    # Best-effort revoke at Google (non-fatal if it fails)
    if token_data and token_data.get("access_token"):
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    "https://oauth2.googleapis.com/revoke",
                    data={"token": token_data["access_token"]},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    timeout=aiohttp.ClientTimeout(total=5),
                )
        except Exception as e:
            logger.debug(f"Google token revoke failed: {e}")

    return {"disconnected": True}

async def refresh_google_token(user_id: str):
    """Refresh Google OAuth token"""
    import aiohttp
    
    token_data = google_oauth_tokens.get(user_id)
    if not token_data or not token_data.get("refresh_token"):
        raise Exception("No refresh token")
    
    async with aiohttp.ClientSession() as session:
        async with session.post("https://oauth2.googleapis.com/token", data={
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": token_data["refresh_token"],
            "grant_type": "refresh_token"
        }) as resp:
            if resp.status != 200:
                raise Exception("Failed to refresh token")
            
            tokens = await resp.json()
    
    google_oauth_tokens[user_id]["access_token"] = tokens.get("access_token")
    google_oauth_tokens[user_id]["expires_at"] = datetime.now(timezone.utc).timestamp() + tokens.get("expires_in", 3600)
    # google_email stays the same across refreshes

async def check_profile_with_google_api(email: str, access_token: str) -> dict:
    """Check profile picture using Google People API"""
    import aiohttp
    
    result = {
        "email": email,
        "has_pic": False,
        "pic_url": None,
        "method": None
    }
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    async with aiohttp.ClientSession() as session:
        # Method 1: Search in contacts
        search_url = f"https://people.googleapis.com/v1/people:searchContacts?query={email}&readMask=photos,emailAddresses"
        
        try:
            async with session.get(search_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("results", [])
                    for r in results:
                        person = r.get("person", {})
                        photos = person.get("photos", [])
                        for photo in photos:
                            url = photo.get("url")
                            if url and "default" not in url.lower():
                                result["has_pic"] = True
                                result["pic_url"] = url
                                result["method"] = "google_people_api"
                                return result
        except Exception as e:
            logger.debug(f"Google People API search failed: {e}")
        
        # Method 2: Search in directory (for Google Workspace)
        directory_url = f"https://people.googleapis.com/v1/people:searchDirectoryPeople?query={email}&readMask=photos,emailAddresses&sources=DIRECTORY_SOURCE_TYPE_DOMAIN_PROFILE"
        
        try:
            async with session.get(directory_url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    people = data.get("people", [])
                    for person in people:
                        photos = person.get("photos", [])
                        for photo in photos:
                            url = photo.get("url")
                            if url and "default" not in url.lower():
                                result["has_pic"] = True
                                result["pic_url"] = url
                                result["method"] = "google_directory"
                                return result
        except Exception as e:
            logger.debug(f"Google Directory search failed: {e}")
        
        # Method 3: Try to get profile by resource name pattern
        # This works for profiles you've interacted with
        try:
            # Get all contacts and check emails
            contacts_url = "https://people.googleapis.com/v1/people/me/connections?pageSize=1000&personFields=emailAddresses,photos"
            
            async with session.get(contacts_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    connections = data.get("connections", [])
                    
                    for person in connections:
                        emails_list = person.get("emailAddresses", [])
                        for e in emails_list:
                            if e.get("value", "").lower() == email.lower():
                                photos = person.get("photos", [])
                                for photo in photos:
                                    url = photo.get("url")
                                    if url and "default" not in url.lower():
                                        result["has_pic"] = True
                                        result["pic_url"] = url
                                        result["method"] = "google_contacts"
                                        return result
        except Exception as e:
            logger.debug(f"Google Contacts check failed: {e}")
    
    return result

async def check_google_profile_pic(email: str, google_access_token: str = None) -> dict:
    """
    Check if an email has a profile picture using FREE methods:
    1. Unavatar.io (FREE - aggregates Google, Gravatar, GitHub, Twitter, etc.)
    2. Gravatar (FREE)
    3. Google's public endpoint (FREE but limited)
    """
    import aiohttp
    
    result = {
        "email": email,
        "has_pic": False,
        "pic_url": None,
        "method": None
    }
    
    email = email.lower().strip()
    
    # If Google access token is available, use People API first
    if google_access_token:
        try:
            google_result = await check_profile_with_google_api(email, google_access_token)
            if google_result["has_pic"]:
                return google_result
        except Exception as e:
            logger.debug(f"Google API check failed for {email}: {e}")
    
    try:
        async with aiohttp.ClientSession() as session:
            
            # Method 1: Unavatar.io - FREE aggregator service
            # Checks: Google, Gravatar, GitHub, Twitter, Facebook, Instagram, YouTube, etc.
            unavatar_url = f"https://unavatar.io/{email}?fallback=false"
            
            try:
                async with session.get(
                    unavatar_url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    allow_redirects=True,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    }
                ) as resp:
                    if resp.status == 200:
                        content_type = resp.headers.get("content-type", "")
                        if "image" in content_type:
                            # Read the image to check size
                            content = await resp.read()
                            # Unavatar returns a small placeholder if no image found
                            # Real profile pics are typically > 1KB
                            if len(content) > 1000:
                                # Check if it's not a default/placeholder by checking URL
                                final_url = str(resp.url)
                                # Unavatar redirects to the actual image source
                                if "unavatar.io/fallback" not in final_url:
                                    result["has_pic"] = True
                                    result["pic_url"] = f"https://unavatar.io/{email}"
                                    result["method"] = "unavatar"
                                    return result
            except Exception as e:
                logger.debug(f"Unavatar check failed for {email}: {e}")
            
            # Method 2: Direct Gravatar check (FREE)
            email_hash = hashlib.md5(email.encode()).hexdigest()
            gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=200"
            
            try:
                async with session.get(
                    gravatar_url, 
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    if resp.status == 200:
                        result["has_pic"] = True
                        result["pic_url"] = f"https://www.gravatar.com/avatar/{email_hash}?s=200"
                        result["method"] = "gravatar"
                        return result
            except Exception as e:
                logger.debug(f"Gravatar check failed for {email}: {e}")
            
            # Method 3: Google's public s2 endpoint (FREE but limited)
            if email.endswith("@gmail.com"):
                s2_url = f"https://www.google.com/s2/photos/public/{email}"
                
                try:
                    async with session.get(
                        s2_url,
                        timeout=aiohttp.ClientTimeout(total=10),
                        allow_redirects=True,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        }
                    ) as resp:
                        if resp.status == 200:
                            content_type = resp.headers.get("content-type", "")
                            if "image" in content_type:
                                content = await resp.read()
                                # Custom profile pics are typically > 5KB
                                if len(content) > 5000:
                                    result["has_pic"] = True
                                    result["pic_url"] = str(resp.url)
                                    result["method"] = "google_s2"
                                    return result
                except Exception as e:
                    logger.debug(f"Google s2 check failed for {email}: {e}")
            
            # Method 4: Try Libravatar (FREE alternative to Gravatar)
            try:
                libravatar_url = f"https://seccdn.libravatar.org/avatar/{email_hash}?d=404&s=200"
                async with session.get(
                    libravatar_url, 
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        result["has_pic"] = True
                        result["pic_url"] = f"https://seccdn.libravatar.org/avatar/{email_hash}?s=200"
                        result["method"] = "libravatar"
                        return result
            except:
                pass
                
    except Exception as e:
        logger.error(f"Error checking profile for {email}: {e}")
    
    return result

@api_router.post("/emails/check-profile-pics")
async def check_email_profile_pics(request: EmailCheckRequest, user: dict = Depends(get_current_user)):
    """
    Check which emails have profile pictures.
    * check_mode="contacts_only" -> use Google People API ONLY (fast, finds only
      contacts you have in your connected Google account).
    * check_mode="all" (default)  -> use Google + free fallbacks (Unavatar,
      Gravatar, Libravatar, Google s2). Higher hit rate but not 100% accurate.
    Returns results as a stream for real-time updates.
    """
    emails = list(dict.fromkeys([e.lower().strip() for e in request.emails if e and "@" in e]))

    if len(emails) == 0:
        raise HTTPException(status_code=400, detail="No valid emails provided")

    if len(emails) > 5000:
        raise HTTPException(status_code=400, detail="Maximum 5000 emails per request")

    check_mode = (request.check_mode or "all").lower()
    if check_mode not in ("contacts_only", "all"):
        check_mode = "all"

    # Get Google access token if available
    user_id = user["id"]
    google_access_token = None
    token_data = google_oauth_tokens.get(user_id)

    if token_data:
        # Check if token needs refresh
        if token_data.get("expires_at", 0) < datetime.now(timezone.utc).timestamp():
            try:
                await refresh_google_token(user_id)
                token_data = google_oauth_tokens.get(user_id)
            except Exception:
                pass

        google_access_token = token_data.get("access_token") if token_data else None

    if check_mode == "contacts_only" and not google_access_token:
        raise HTTPException(
            status_code=400,
            detail="'Contacts only' mode requires a connected Google account. Please connect Google first.",
        )

    async def generate():
        with_pic = 0
        without_pic = 0

        for i, email in enumerate(emails):
            if check_mode == "contacts_only":
                # Only Google People API (contacts + directory)
                try:
                    result = await check_profile_with_google_api(email, google_access_token)
                except Exception as e:
                    logger.debug(f"Google-only check failed for {email}: {e}")
                    result = {"email": email, "has_pic": False, "pic_url": None, "method": None}
                # Ensure the email key is present
                result["email"] = email
            else:
                result = await check_google_profile_pic(email, google_access_token)

            if result["has_pic"]:
                with_pic += 1
            else:
                without_pic += 1

            yield json.dumps({
                "type": "result",
                "email": result["email"],
                "has_pic": result["has_pic"],
                "pic_url": result["pic_url"],
                "method": result.get("method"),
            }) + "\n"

            if (i + 1) % 5 == 0 or i == len(emails) - 1:
                yield json.dumps({
                    "type": "progress",
                    "processed": i + 1,
                    "total": len(emails),
                }) + "\n"

        yield json.dumps({
            "type": "complete",
            "total": len(emails),
            "with_pic": with_pic,
            "without_pic": without_pic,
            "used_google_api": google_access_token is not None,
            "check_mode": check_mode,
        }) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
    )

@api_router.post("/emails/upload-file")
async def upload_email_file(file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    """
    Upload Excel or CSV file and extract emails.
    Also returns the ORIGINAL rows and columns so the export can preserve the
    user's full data (all columns/rows), just appended with check results.
    Supports .xlsx, .xls, .csv, .txt files with any column headers.
    """
    import pandas as pd
    import io
    import re

    # Check file extension
    filename = file.filename.lower()
    if not any(filename.endswith(ext) for ext in ['.xlsx', '.xls', '.csv', '.txt']):
        raise HTTPException(status_code=400, detail="Supported formats: .xlsx, .xls, .csv, .txt")

    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    try:
        contents = await file.read()

        emails: List[str] = []
        rows: List[Dict[str, Any]] = []
        columns: List[str] = []
        email_column: Optional[str] = None

        def _df_to_rows(df):
            """Convert a pandas DataFrame to (rows, columns), coercing NaN -> ''."""
            # Force every column name to string so JSON is clean
            df = df.copy()
            df.columns = [str(c) for c in df.columns]
            df = df.fillna("")
            cols = list(df.columns)
            out = []
            for _, row in df.iterrows():
                row_dict = {}
                for c in cols:
                    v = row[c]
                    # Make sure every value is JSON-serialisable
                    try:
                        if hasattr(v, "isoformat"):
                            row_dict[c] = v.isoformat()
                        else:
                            row_dict[c] = str(v) if v != "" else ""
                    except Exception:
                        row_dict[c] = ""
                out.append(row_dict)
            return out, cols

        def _pick_email_column(cols, rows_list):
            """Find the column most likely to contain emails."""
            best_col = None
            best_count = 0
            for c in cols:
                count = 0
                for r in rows_list[:200]:  # sample
                    val = str(r.get(c, ""))
                    if email_pattern.search(val):
                        count += 1
                if count > best_count:
                    best_count = count
                    best_col = c
            return best_col if best_count > 0 else None

        if filename.endswith('.csv') or filename.endswith('.txt'):
            # Try to parse as a structured CSV first so we keep columns/rows
            try:
                df = pd.read_csv(io.BytesIO(contents), dtype=str, keep_default_na=False)
                rows, columns = _df_to_rows(df)
                email_column = _pick_email_column(columns, rows)
                # Extract emails from the detected column (or scan all if not found)
                if email_column:
                    for r in rows:
                        found = email_pattern.findall(str(r.get(email_column, "")))
                        emails.extend(found)
                else:
                    for r in rows:
                        for v in r.values():
                            emails.extend(email_pattern.findall(str(v)))
            except Exception:
                # Fall back to raw text extraction
                text = contents.decode('utf-8', errors='ignore')
                emails = email_pattern.findall(text)
                rows, columns, email_column = [], [], None

        elif filename.endswith('.xlsx') or filename.endswith('.xls'):
            engine = 'openpyxl' if filename.endswith('.xlsx') else 'xlrd'
            df = pd.read_excel(io.BytesIO(contents), engine=engine, dtype=str)
            # keep_default_na not supported on read_excel in all versions; manual fillna below
            rows, columns = _df_to_rows(df)
            email_column = _pick_email_column(columns, rows)
            if email_column:
                for r in rows:
                    found = email_pattern.findall(str(r.get(email_column, "")))
                    emails.extend(found)
            else:
                # Fallback: scan every column
                for r in rows:
                    for v in r.values():
                        emails.extend(email_pattern.findall(str(v)))

        # Deduplicate emails (preserve order)
        seen = set()
        unique_emails = []
        for e in emails:
            el = e.lower().strip()
            if el and "@" in el and el not in seen:
                seen.add(el)
                unique_emails.append(el)

        if len(unique_emails) == 0:
            raise HTTPException(status_code=400, detail="No valid emails found in the file")

        return {
            "message": f"Found {len(unique_emails)} emails",
            "emails": unique_emails,
            "count": len(unique_emails),
            "rows": rows,               # original data (all columns)
            "columns": columns,         # original column order
            "email_column": email_column,  # detected email column (can be null)
            "filename": file.filename,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error parsing file: {e}")
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")

@api_router.post("/emails/download-results")
async def download_email_results(
    payload: EmailDownloadRequest,
    user: dict = Depends(get_current_user),
):
    """
    Generate Excel file with email check results.
    * If `rows` + `email_column` are provided, the user's ORIGINAL uploaded data
      is preserved (every column, every row, in order) and two columns are
      appended: "Has Profile Pic" and "Profile Pic URL".
    * If `rows` is empty (user pasted emails directly), the export falls back to
      a simple three-column format.
    """
    import pandas as pd
    import io
    import re

    results = payload.results or {}
    # Normalise result keys to lowercase emails
    norm_results: Dict[str, Dict[str, Any]] = {
        (k or "").lower().strip(): v for k, v in results.items()
    }

    email_re = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    try:
        rows = payload.rows or []
        columns = payload.columns or []
        email_col = payload.email_column

        if rows and columns:
            # Preserve original file shape
            extended_cols = list(columns)
            if "Has Profile Pic" not in extended_cols:
                extended_cols.append("Has Profile Pic")
            if "Profile Pic URL" not in extended_cols:
                extended_cols.append("Profile Pic URL")

            enriched_rows = []
            for r in rows:
                new_row = {c: r.get(c, "") for c in columns}
                # Figure out email for this row
                email_val = None
                if email_col and r.get(email_col):
                    m = email_re.search(str(r.get(email_col, "")))
                    if m:
                        email_val = m.group(0).lower().strip()
                if not email_val:
                    # Fallback: scan every cell in the row
                    for v in r.values():
                        m = email_re.search(str(v))
                        if m:
                            email_val = m.group(0).lower().strip()
                            break

                res = norm_results.get(email_val) if email_val else None
                if res and res.get("has_pic"):
                    new_row["Has Profile Pic"] = "Yes"
                    new_row["Profile Pic URL"] = res.get("pic_url") or ""
                elif res is not None:
                    new_row["Has Profile Pic"] = "No"
                    new_row["Profile Pic URL"] = ""
                else:
                    new_row["Has Profile Pic"] = ""  # not checked
                    new_row["Profile Pic URL"] = ""
                enriched_rows.append(new_row)

            df_all = pd.DataFrame(enriched_rows, columns=extended_cols)
            df_with = df_all[df_all["Has Profile Pic"] == "Yes"]
            df_without = df_all[df_all["Has Profile Pic"] == "No"]
        else:
            # No rows sent -> simple 3-column export from results dict
            data_all = []
            for email, res in norm_results.items():
                data_all.append({
                    "Email": email,
                    "Has Profile Pic": "Yes" if res.get("has_pic") else "No",
                    "Profile Pic URL": res.get("pic_url") or "",
                })
            df_all = pd.DataFrame(data_all, columns=["Email", "Has Profile Pic", "Profile Pic URL"])
            df_with = df_all[df_all["Has Profile Pic"] == "Yes"]
            df_without = df_all[df_all["Has Profile Pic"] == "No"]

        # Build the multi-sheet Excel file
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_all.to_excel(writer, sheet_name='All Results', index=False)
            if len(df_with) > 0:
                df_with.to_excel(writer, sheet_name='Has Profile Pic', index=False)
            if len(df_without) > 0:
                df_without.to_excel(writer, sheet_name='No Profile Pic', index=False)
        output.seek(0)

        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=email_check_results.xlsx"
            }
        )

    except Exception as e:
        logger.error(f"Error generating Excel: {e}")
        raise HTTPException(status_code=500, detail=f"Error generating file: {str(e)}")

# ==================== SEPARATE DATA (EMAIL ROW FILTER) ====================

@api_router.post("/emails/preview-file")
async def preview_email_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    """
    Preview an uploaded spreadsheet without filtering.
    Returns columns, total row count, detected email column, and the first
    few rows so the UI can show a preview.
    """
    import pandas as pd
    import io
    import re

    filename = file.filename.lower()
    if not any(filename.endswith(ext) for ext in ['.xlsx', '.xls', '.csv', '.txt']):
        raise HTTPException(status_code=400, detail="Supported formats: .xlsx, .xls, .csv, .txt")

    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    try:
        contents = await file.read()

        if filename.endswith('.csv') or filename.endswith('.txt'):
            df = pd.read_csv(io.BytesIO(contents), dtype=str, keep_default_na=False)
        else:
            engine = 'openpyxl' if filename.endswith('.xlsx') else 'xlrd'
            df = pd.read_excel(io.BytesIO(contents), engine=engine, dtype=str)

        df = df.fillna("")
        df.columns = [str(c) for c in df.columns]
        columns = list(df.columns)

        # Build rows
        rows = df.to_dict(orient="records")
        # Ensure all values are strings
        rows = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in rows]

        # Detect email column (column with most email matches in first 200 rows)
        best_col = None
        best_count = 0
        for c in columns:
            count = 0
            for r in rows[:200]:
                if email_pattern.search(str(r.get(c, ""))):
                    count += 1
            if count > best_count:
                best_count = count
                best_col = c

        email_column = best_col if best_count > 0 else None

        return {
            "filename": file.filename,
            "columns": columns,
            "total_rows": len(rows),
            "email_column": email_column,
            "preview_rows": rows[:10],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Preview error: {e}")
        raise HTTPException(status_code=400, detail=f"Error parsing file: {str(e)}")


@api_router.post("/emails/filter-rows")
async def filter_rows_by_emails(
    file: UploadFile = File(...),
    emails: str = Form(...),
    email_column: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    """
    SEPARATE DATA feature.
    * Accepts a master spreadsheet (`file`) + a list of emails (`emails` — newline,
      comma, or semicolon separated).
    * Finds every row in the master whose email matches any of the provided
      emails (case-insensitive, all whitespace trimmed).
    * Returns an Excel file with:
        - Sheet "Matched Rows": only the matched rows, ALL original columns preserved.
        - Sheet "Not Found":    the emails from the list that did NOT appear in the file.
        - Sheet "Summary":      counts.
    * `email_column` is optional — if not provided, it is auto-detected.
    """
    import pandas as pd
    import io
    import re

    filename = file.filename.lower()
    if not any(filename.endswith(ext) for ext in ['.xlsx', '.xls', '.csv', '.txt']):
        raise HTTPException(status_code=400, detail="Supported formats: .xlsx, .xls, .csv, .txt")

    # Parse the pasted email list
    raw_emails = re.split(r'[\n,;]+', emails or "")
    target_emails = []
    seen = set()
    for e in raw_emails:
        el = (e or "").strip().lower()
        if el and "@" in el and el not in seen:
            seen.add(el)
            target_emails.append(el)

    if not target_emails:
        raise HTTPException(status_code=400, detail="No valid emails provided in the list")

    email_pattern = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    try:
        contents = await file.read()

        if filename.endswith('.csv') or filename.endswith('.txt'):
            df = pd.read_csv(io.BytesIO(contents), dtype=str, keep_default_na=False)
        else:
            engine = 'openpyxl' if filename.endswith('.xlsx') else 'xlrd'
            df = pd.read_excel(io.BytesIO(contents), engine=engine, dtype=str)

        df = df.fillna("")
        df.columns = [str(c) for c in df.columns]
        columns = list(df.columns)

        if not columns:
            raise HTTPException(status_code=400, detail="Uploaded file has no columns")

        # Determine which column to match on
        chosen_col = email_column if email_column and email_column in columns else None
        if not chosen_col:
            # Auto-detect: the column with the most email-like cells
            best_col = None
            best_count = 0
            sample = df.head(300)
            for c in columns:
                count = sum(1 for v in sample[c].tolist() if email_pattern.search(str(v)))
                if count > best_count:
                    best_count = count
                    best_col = c
            chosen_col = best_col

        if not chosen_col:
            raise HTTPException(status_code=400, detail="Could not detect an email column in the file")

        target_set = set(target_emails)

        def _extract_email(cell_value: str) -> Optional[str]:
            """Pull the first email-looking substring from a cell and normalise it."""
            if cell_value is None:
                return None
            m = email_pattern.search(str(cell_value))
            if m:
                return m.group(0).strip().lower()
            return None

        # Filter
        matched_mask = df[chosen_col].apply(
            lambda v: (_extract_email(v) in target_set) if _extract_email(v) else False
        )
        matched_df = df[matched_mask].copy()

        # Emails that were found (from the target list) - for "Not Found" sheet
        found_emails = set()
        for v in matched_df[chosen_col].tolist():
            e = _extract_email(v)
            if e:
                found_emails.add(e)

        not_found = [e for e in target_emails if e not in found_emails]
        not_found_df = pd.DataFrame({"Email (not found in file)": not_found}) if not_found else None

        summary_df = pd.DataFrame([
            {"Metric": "Total emails in your list", "Value": len(target_emails)},
            {"Metric": "Rows in uploaded file",      "Value": int(len(df))},
            {"Metric": "Matched rows returned",      "Value": int(len(matched_df))},
            {"Metric": "Emails not found",           "Value": len(not_found)},
            {"Metric": "Email column used",          "Value": chosen_col},
            {"Metric": "Source filename",            "Value": file.filename},
        ])

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Matched rows keep ALL original columns, in original order.
            if len(matched_df) > 0:
                matched_df.to_excel(writer, sheet_name='Matched Rows', index=False)
            else:
                # Always write an empty sheet with headers so the user sees the columns
                empty = pd.DataFrame(columns=columns)
                empty.to_excel(writer, sheet_name='Matched Rows', index=False)

            summary_df.to_excel(writer, sheet_name='Summary', index=False)

            if not_found_df is not None:
                not_found_df.to_excel(writer, sheet_name='Not Found', index=False)

        output.seek(0)

        base_name = re.sub(r'\.[^.]+$', '', file.filename or 'filtered')
        download_name = f"{base_name}_filtered.xlsx"

        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{download_name}"',
                "X-Matched-Count": str(len(matched_df)),
                "X-Not-Found-Count": str(len(not_found)),
                "X-Email-Column": str(chosen_col),
                "Access-Control-Expose-Headers": "X-Matched-Count, X-Not-Found-Count, X-Email-Column, Content-Disposition",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Filter-rows error: {e}")
        raise HTTPException(status_code=500, detail=f"Error filtering rows: {str(e)}")




# ==================== USER AGENT GENERATOR ====================

class UAGenerateRequest(BaseModel):
    app: str = "instagram"           # instagram, facebook, tiktok, pinterest, snapchat, chrome
    platform: str = "any"            # android, ios, desktop, any
    brand: Optional[str] = None      # samsung, google, motorola, xiaomi, oneplus, realme, iphone, ipad, windows, mac, linux, any
    # Single-value pickers (kept for back-compat)
    device_id: Optional[str] = None
    app_version: Optional[str] = None
    os_version: Optional[str] = None
    # Multi-select pools — if any are given, generator picks randomly per UA from this pool only
    device_ids: Optional[List[str]] = None      # 2–N exact device ids to cycle through
    app_versions: Optional[List[str]] = None    # 2–N exact app versions to cycle through
    os_versions: Optional[List[str]] = None     # 2–N exact OS versions to cycle through
    region: Optional[str] = None
    regions: Optional[List[str]] = None         # 2–N region codes to cycle through
    resolution: Optional[str] = None
    resolutions: Optional[List[str]] = None     # 2–N resolutions to cycle through
    count: int = 10                  # up to 50,000
    format: Optional[str] = "json"   # "json" or "xlsx"

# Realistic Android device pool — each entry has everything Instagram/FB templates need.
_ANDROID_DEVICES = [
    {"brand":"Motorola","model":"moto g 5G - 2024","vendor":"motorola","chipset":"qcom","soc":"fogo","res":"720x1612","dpi":"306dpi","and_ver":"14","sdk":"34","build":"U1UFNS34.41-98-10-5-4"},
    {"brand":"Motorola","model":"moto g power (2024)","vendor":"motorola","chipset":"mt6789","soc":"penang","res":"1080x2400","dpi":"420dpi","and_ver":"14","sdk":"34","build":"U1UHNS34.41-13-8-4"},
    {"brand":"Samsung","model":"SM-S918B","vendor":"samsung","chipset":"qcom","soc":"kalama","res":"1080x2340","dpi":"420dpi","and_ver":"14","sdk":"34","build":"UP1A.231005.007"},
    {"brand":"Samsung","model":"SM-S928B","vendor":"samsung","chipset":"qcom","soc":"pineapple","res":"1440x3120","dpi":"505dpi","and_ver":"14","sdk":"34","build":"UP1A.231005.007"},
    {"brand":"Samsung","model":"SM-A546B","vendor":"samsung","chipset":"mt6833","soc":"a54x","res":"1080x2340","dpi":"420dpi","and_ver":"13","sdk":"33","build":"TP1A.220624.014"},
    {"brand":"Samsung","model":"SM-G991B","vendor":"samsung","chipset":"qcom","soc":"exynos2100","res":"1080x2400","dpi":"420dpi","and_ver":"13","sdk":"33","build":"TP1A.220624.014"},
    {"brand":"Google","model":"Pixel 8 Pro","vendor":"google","chipset":"tensor","soc":"husky","res":"1344x2992","dpi":"490dpi","and_ver":"14","sdk":"34","build":"UP1A.231105.003"},
    {"brand":"Google","model":"Pixel 8","vendor":"google","chipset":"tensor","soc":"shiba","res":"1080x2400","dpi":"420dpi","and_ver":"14","sdk":"34","build":"UP1A.231105.003"},
    {"brand":"Google","model":"Pixel 7","vendor":"google","chipset":"tensor","soc":"panther","res":"1080x2400","dpi":"420dpi","and_ver":"14","sdk":"34","build":"UP1A.231105.003"},
    {"brand":"OnePlus","model":"CPH2449","vendor":"OnePlus","chipset":"qcom","soc":"waffle","res":"1240x2772","dpi":"450dpi","and_ver":"14","sdk":"34","build":"UKQ1.230924.001"},
    {"brand":"OnePlus","model":"CPH2581","vendor":"OnePlus","chipset":"qcom","soc":"corvette","res":"1080x2412","dpi":"405dpi","and_ver":"14","sdk":"34","build":"UKQ1.230924.001"},
    {"brand":"Xiaomi","model":"23049PCD8G","vendor":"Xiaomi","chipset":"qcom","soc":"renoir","res":"1080x2400","dpi":"440dpi","and_ver":"13","sdk":"33","build":"TKQ1.221114.001"},
    {"brand":"Xiaomi","model":"2311DRK48G","vendor":"Xiaomi","chipset":"qcom","soc":"pineapple","res":"1440x3200","dpi":"522dpi","and_ver":"14","sdk":"34","build":"UKQ1.230917.001"},
    {"brand":"Realme","model":"RMX3834","vendor":"realme","chipset":"qcom","soc":"giza","res":"1080x2400","dpi":"480dpi","and_ver":"14","sdk":"34","build":"SP2A.220405.004"},
    {"brand":"Realme","model":"RMX3710","vendor":"realme","chipset":"mt6877v","soc":"pike","res":"1080x2412","dpi":"400dpi","and_ver":"13","sdk":"33","build":"SP1A.210812.016"},
    {"brand":"Oppo","model":"CPH2423","vendor":"OPPO","chipset":"mt6983","soc":"redwood","res":"1240x2772","dpi":"450dpi","and_ver":"13","sdk":"33","build":"SP1A.210812.016"},
    {"brand":"Vivo","model":"V2312A","vendor":"vivo","chipset":"mt6896","soc":"pyrite","res":"1260x2800","dpi":"453dpi","and_ver":"14","sdk":"34","build":"UP1A.231005.007"},
]

# Realistic iOS device pool — all modern iPhones on current iOS builds
# (April 2026). Every device runs iOS 26.x (the current series) so every
# generated UA matches what a real user's device sends right now.
_IOS_DEVICES = [
    {"brand":"iPhone","model":"iPhone12,1","name":"iPhone 11","ios":"26_1","res":"828x1792","scale":"2.00"},
    {"brand":"iPhone","model":"iPhone12,3","name":"iPhone 11 Pro","ios":"26_2","res":"1125x2436","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone12,5","name":"iPhone 11 Pro Max","ios":"26_2_1","res":"1242x2688","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone13,1","name":"iPhone 12 mini","ios":"26_2","res":"1080x2340","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone13,2","name":"iPhone 12","ios":"26_3","res":"1170x2532","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone13,3","name":"iPhone 12 Pro","ios":"26_3","res":"1170x2532","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone13,4","name":"iPhone 12 Pro Max","ios":"26_2_1","res":"1284x2778","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,4","name":"iPhone 13 mini","ios":"26_3","res":"1080x2340","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,5","name":"iPhone 13","ios":"26_3_1","res":"1170x2532","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,2","name":"iPhone 13 Pro","ios":"26_3","res":"1170x2532","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,3","name":"iPhone 13 Pro Max","ios":"26_4","res":"1284x2778","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,7","name":"iPhone 14","ios":"26_3_1","res":"1170x2532","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone14,8","name":"iPhone 14 Plus","ios":"26_3","res":"1284x2778","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone15,2","name":"iPhone 14 Pro","ios":"26_4","res":"1179x2556","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone15,3","name":"iPhone 14 Pro Max","ios":"26_4","res":"1290x2796","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone15,4","name":"iPhone 15","ios":"26_3_1","res":"1179x2556","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone15,5","name":"iPhone 15 Plus","ios":"26_4","res":"1290x2796","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone16,1","name":"iPhone 15 Pro","ios":"26_4","res":"1179x2556","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone16,2","name":"iPhone 15 Pro Max","ios":"26_4_1","res":"1290x2796","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone17,3","name":"iPhone 16","ios":"26_4","res":"1179x2556","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone17,4","name":"iPhone 16 Plus","ios":"26_4_1","res":"1290x2796","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone17,1","name":"iPhone 16 Pro","ios":"26_4_1","res":"1206x2622","scale":"3.00"},
    {"brand":"iPhone","model":"iPhone17,2","name":"iPhone 16 Pro Max","ios":"26_4_1","res":"1320x2868","scale":"3.00"},
    {"brand":"iPad","model":"iPad13,1","name":"iPad Air (5th gen)","ios":"26_3","res":"1640x2360","scale":"2.00"},
    {"brand":"iPad","model":"iPad14,3","name":"iPad Pro 11\"","ios":"26_4","res":"1668x2388","scale":"2.00"},
    {"brand":"iPad","model":"iPad14,5","name":"iPad Pro 12.9\"","ios":"26_4_1","res":"2048x2732","scale":"2.00"},
]

# Backwards-compat alias — some older code paths reference this name.
_IOS_DEVICES_MODERN = [d for d in _IOS_DEVICES if d["brand"] == "iPhone"]

_APP_VERSIONS = {
    # ─────────────────────────────────────────────────────────────────
    # Keep only the latest ~7 versions of each app.
    # These lists are auto-refreshed on startup (and every 24h) from the
    # iTunes Lookup API — see `_auto_refresh_ua_versions_task()` below.
    # Admin can also force a refresh via POST /api/admin/ua-versions/refresh
    # ─────────────────────────────────────────────────────────────────
    "instagram": ["425.0.0", "422.0.0", "420.0.0.35.87", "418.0.0", "415.0.0.36.111", "412.0.0.35.87", "410.0.0.36.111"],
    "facebook":  ["557.0", "555.0", "553.0", "551.0", "550.0.0.45.102", "549.0", "547.0"],
    "tiktok":    ["44.7.0", "44.3.0", "43.9.0", "43.5.0", "43.1.0", "42.7.0", "42.3.0"],
    "pinterest": ["14.14", "14.10", "14.5", "14.1", "13.8", "13.5", "13.2"],
    "snapchat":  ["13.88.0.56", "13.85.0.51", "13.80.0.48", "13.75.0.45", "13.70.0.41", "13.65.0.38", "13.60.0.35"],
    "youtube":   ["20.15.3", "20.14.2", "20.13.0", "20.12.3", "20.11.4", "20.10.2", "20.09.3"],
    "whatsapp":  ["25.4.82", "25.4.78", "25.3.75", "25.3.70", "25.2.73", "25.2.68", "25.1.72"],
    "gsearch":   ["332.0.755318947", "331.0.754842390", "330.0.752551382", "329.0.750019021", "328.0.747855320", "327.0.745210445", "326.0.742180108"],
    "gchrome":   ["147.0.7727.102", "146.0.7680.177", "145.0.7600.130", "144.0.7559.63", "143.0.7637.60", "142.0.7835.13", "141.0.7390.72"],
}

# iTunes app-store IDs for pulling the *current* live version of each app.
# iTunes Lookup API is free, unauthenticated, and extremely stable.
_ITUNES_APP_IDS = {
    "instagram": 389801252,
    "tiktok":    835599320,
    "facebook":  284882215,
    "pinterest": 429047995,
    "snapchat":  447188370,
    "youtube":   544007664,
    "whatsapp":  310633997,
    "gsearch":   284815942,   # Google Search app (GSA)
    "gchrome":   535886823,   # Google Chrome for iOS ("Google Native" browser)
}

# Metadata used by the admin-facing UA versions endpoint.
_UA_VERSIONS_META = {
    "last_refreshed_at": None,   # ISO8601 str when last refreshed
    "last_refresh_ok":   None,   # bool
    "last_refresh_note": "",     # e.g. "Refreshed 3 apps"
    "sources": {},               # {"tiktok": "iTunes Lookup", ...}
}

# Supported regions for UA generation. Each entry maps a region code to a
# realistic ByteLocale (used by TikTok iOS) and a POSIX locale (used by
# Instagram / Facebook Android UAs). Picking a region here drives all three
# tokens consistently.
_REGIONS = [
    {"code": "US", "country": "United States",    "byte_locale": "en",    "posix_locale": "en_US", "lang_tag": "en-US"},
    {"code": "GB", "country": "United Kingdom",   "byte_locale": "en-GB", "posix_locale": "en_GB", "lang_tag": "en-GB"},
    {"code": "CA", "country": "Canada",           "byte_locale": "en-CA", "posix_locale": "en_CA", "lang_tag": "en-CA"},
    {"code": "AU", "country": "Australia",        "byte_locale": "en-AU", "posix_locale": "en_AU", "lang_tag": "en-AU"},
    {"code": "IE", "country": "Ireland",          "byte_locale": "en-IE", "posix_locale": "en_IE", "lang_tag": "en-IE"},
    {"code": "NZ", "country": "New Zealand",      "byte_locale": "en-NZ", "posix_locale": "en_NZ", "lang_tag": "en-NZ"},
    {"code": "IN", "country": "India",            "byte_locale": "en-IN", "posix_locale": "en_IN", "lang_tag": "en-IN"},
    {"code": "ZA", "country": "South Africa",     "byte_locale": "en-ZA", "posix_locale": "en_ZA", "lang_tag": "en-ZA"},
    {"code": "DE", "country": "Germany",          "byte_locale": "de-DE", "posix_locale": "de_DE", "lang_tag": "de-DE"},
    {"code": "AT", "country": "Austria",          "byte_locale": "de-AT", "posix_locale": "de_AT", "lang_tag": "de-AT"},
    {"code": "CH", "country": "Switzerland",      "byte_locale": "de-CH", "posix_locale": "de_CH", "lang_tag": "de-CH"},
    {"code": "FR", "country": "France",           "byte_locale": "fr-FR", "posix_locale": "fr_FR", "lang_tag": "fr-FR"},
    {"code": "BE", "country": "Belgium",          "byte_locale": "fr-BE", "posix_locale": "fr_BE", "lang_tag": "fr-BE"},
    {"code": "ES", "country": "Spain",            "byte_locale": "es-ES", "posix_locale": "es_ES", "lang_tag": "es-ES"},
    {"code": "MX", "country": "Mexico",           "byte_locale": "es-MX", "posix_locale": "es_MX", "lang_tag": "es-MX"},
    {"code": "AR", "country": "Argentina",        "byte_locale": "es-AR", "posix_locale": "es_AR", "lang_tag": "es-AR"},
    {"code": "CO", "country": "Colombia",         "byte_locale": "es-CO", "posix_locale": "es_CO", "lang_tag": "es-CO"},
    {"code": "CL", "country": "Chile",            "byte_locale": "es-CL", "posix_locale": "es_CL", "lang_tag": "es-CL"},
    {"code": "PE", "country": "Peru",             "byte_locale": "es-PE", "posix_locale": "es_PE", "lang_tag": "es-PE"},
    {"code": "BR", "country": "Brazil",           "byte_locale": "pt-BR", "posix_locale": "pt_BR", "lang_tag": "pt-BR"},
    {"code": "PT", "country": "Portugal",         "byte_locale": "pt-PT", "posix_locale": "pt_PT", "lang_tag": "pt-PT"},
    {"code": "IT", "country": "Italy",            "byte_locale": "it-IT", "posix_locale": "it_IT", "lang_tag": "it-IT"},
    {"code": "NL", "country": "Netherlands",      "byte_locale": "nl-NL", "posix_locale": "nl_NL", "lang_tag": "nl-NL"},
    {"code": "PL", "country": "Poland",           "byte_locale": "pl-PL", "posix_locale": "pl_PL", "lang_tag": "pl-PL"},
    {"code": "SE", "country": "Sweden",           "byte_locale": "sv-SE", "posix_locale": "sv_SE", "lang_tag": "sv-SE"},
    {"code": "NO", "country": "Norway",           "byte_locale": "nb-NO", "posix_locale": "nb_NO", "lang_tag": "nb-NO"},
    {"code": "DK", "country": "Denmark",          "byte_locale": "da-DK", "posix_locale": "da_DK", "lang_tag": "da-DK"},
    {"code": "FI", "country": "Finland",          "byte_locale": "fi-FI", "posix_locale": "fi_FI", "lang_tag": "fi-FI"},
    {"code": "RU", "country": "Russia",           "byte_locale": "ru-RU", "posix_locale": "ru_RU", "lang_tag": "ru-RU"},
    {"code": "UA", "country": "Ukraine",          "byte_locale": "uk-UA", "posix_locale": "uk_UA", "lang_tag": "uk-UA"},
    {"code": "TR", "country": "Turkey",           "byte_locale": "tr-TR", "posix_locale": "tr_TR", "lang_tag": "tr-TR"},
    {"code": "GR", "country": "Greece",           "byte_locale": "el-GR", "posix_locale": "el_GR", "lang_tag": "el-GR"},
    {"code": "SA", "country": "Saudi Arabia",     "byte_locale": "ar-SA", "posix_locale": "ar_SA", "lang_tag": "ar-SA"},
    {"code": "AE", "country": "UAE",              "byte_locale": "ar-AE", "posix_locale": "ar_AE", "lang_tag": "ar-AE"},
    {"code": "EG", "country": "Egypt",            "byte_locale": "ar-EG", "posix_locale": "ar_EG", "lang_tag": "ar-EG"},
    {"code": "IL", "country": "Israel",           "byte_locale": "he-IL", "posix_locale": "he_IL", "lang_tag": "he-IL"},
    {"code": "JP", "country": "Japan",            "byte_locale": "ja-JP", "posix_locale": "ja_JP", "lang_tag": "ja-JP"},
    {"code": "KR", "country": "South Korea",      "byte_locale": "ko-KR", "posix_locale": "ko_KR", "lang_tag": "ko-KR"},
    {"code": "TW", "country": "Taiwan",           "byte_locale": "zh-TW", "posix_locale": "zh_TW", "lang_tag": "zh-TW"},
    {"code": "HK", "country": "Hong Kong",        "byte_locale": "zh-HK", "posix_locale": "zh_HK", "lang_tag": "zh-HK"},
    {"code": "SG", "country": "Singapore",        "byte_locale": "en-SG", "posix_locale": "en_SG", "lang_tag": "en-SG"},
    {"code": "MY", "country": "Malaysia",         "byte_locale": "ms-MY", "posix_locale": "ms_MY", "lang_tag": "ms-MY"},
    {"code": "ID", "country": "Indonesia",        "byte_locale": "id-ID", "posix_locale": "id_ID", "lang_tag": "id-ID"},
    {"code": "TH", "country": "Thailand",         "byte_locale": "th-TH", "posix_locale": "th_TH", "lang_tag": "th-TH"},
    {"code": "VN", "country": "Vietnam",          "byte_locale": "vi-VN", "posix_locale": "vi_VN", "lang_tag": "vi-VN"},
    {"code": "PH", "country": "Philippines",      "byte_locale": "en-PH", "posix_locale": "en_PH", "lang_tag": "en-PH"},
    {"code": "PK", "country": "Pakistan",         "byte_locale": "en-PK", "posix_locale": "en_PK", "lang_tag": "en-PK"},
    {"code": "BD", "country": "Bangladesh",       "byte_locale": "bn-BD", "posix_locale": "bn_BD", "lang_tag": "bn-BD"},
    {"code": "NG", "country": "Nigeria",          "byte_locale": "en-NG", "posix_locale": "en_NG", "lang_tag": "en-NG"},
    {"code": "KE", "country": "Kenya",            "byte_locale": "en-KE", "posix_locale": "en_KE", "lang_tag": "en-KE"},
]

# TikTok's top-traffic regions — weight toward these when "random" is picked.
_TIKTOK_TOP_REGIONS = {"US", "GB", "BR", "ID", "MX", "DE", "FR", "JP", "CA", "AU"}

def _pick_region(region_code: Optional[str]) -> dict:
    """Resolve a requested region code to a full region dict, or pick a
    realistic random one (weighted toward TikTok's top markets)."""
    if region_code:
        for r in _REGIONS:
            if r["code"].upper() == region_code.upper():
                return r
    # Random with TikTok-top-market weighting
    pool = []
    for r in _REGIONS:
        pool.extend([r] * (3 if r["code"] in _TIKTOK_TOP_REGIONS else 1))
    return random.choice(pool)

# Common mobile resolutions the user can pin explicitly.
_MOBILE_RESOLUTIONS = [
    "720x1612", "720x1600",
    "1080x1920", "1080x2160", "1080x2240", "1080x2280", "1080x2340",
    "1080x2400", "1080x2408", "1080x2412",
    "1125x2436",
    "1170x2532",
    "1179x2556",
    "1206x2622",
    "1242x2688",
    "1260x2800",
    "1284x2778",
    "1290x2796",
    "1320x2868",
    "1344x2992",
    "1440x3088", "1440x3120", "1440x3200",
]

# Supported OS versions the user can pin. Kept to the latest 7 — older
# values are auto-dropped as newer ones are released and pulled in by
# `_auto_refresh_ua_versions_task()` below. Defaults reflect mid-April 2026
# (iOS 26 series + Android 16) and are overridden live on startup.
_IOS_OS_VERSIONS = [
    "26_4_1", "26_4", "26_3_1", "26_3", "26_2_1", "26_2", "26_1",
]

# Android versions + their SDK/API levels (used in Instagram UA `sdk/ver`).
# Android 16 (SDK 36) is the current stable (Android 16 QPR1 released Sep 2025).
_ANDROID_OS_VERSIONS = [
    {"version": "16", "sdk": "36"},
    {"version": "15", "sdk": "35"},
    {"version": "14", "sdk": "34"},
    {"version": "13", "sdk": "33"},
    {"version": "12", "sdk": "31"},
    {"version": "11", "sdk": "30"},
    {"version": "10", "sdk": "29"},
]

def _normalize_ios_version(v: str) -> str:
    """Accept "18.3" or "18_3" and always return "18_3" for UA use."""
    return (v or "").replace(".", "_").strip()

def _apply_os_version_override(device: dict, platform: str, os_version: Optional[str]) -> dict:
    """
    Return a shallow copy of `device` with iOS or Android version overridden
    if the caller asked for a specific OS version.
    """
    if not os_version:
        return device
    d = dict(device)
    if platform == "ios" or "ios" in d:
        norm = _normalize_ios_version(os_version)
        d["ios"] = norm
    elif platform == "android" or "and_ver" in d:
        # Match to our SDK table
        ver = os_version.strip()
        match = next((x for x in _ANDROID_OS_VERSIONS if x["version"] == ver), None)
        if match:
            d["and_ver"] = match["version"]
            d["sdk"] = match["sdk"]
        else:
            d["and_ver"] = ver  # allow arbitrary, keep device's sdk
    return d


# ─── Auto-refresh UA version lists from iTunes Lookup API ──────────────
# Pull the current live iOS version of each app (TikTok, Instagram, FB,
# Pinterest, Snapchat) daily, plus the most-recent iOS OS minimum so we
# keep up with whatever Apple/apps ship. Failures never raise.

_UA_REFRESH_INTERVAL_SECONDS = 24 * 60 * 60      # 1 day
_UA_REFRESH_TIMEOUT = 8                           # per-request timeout

def _prepend_and_trim(lst: List[str], value: str, max_len: int = 7) -> List[str]:
    """Insert `value` at the top of `lst` if it's not already present, then
    trim the list to `max_len`. Preserves relative order of older entries."""
    if not value:
        return lst
    if value in lst:
        lst.remove(value)
    lst.insert(0, value)
    return lst[:max_len]

async def _fetch_itunes_version(app_id: int, country: str = "us") -> Optional[str]:
    """Fetch the current live version of an iOS app via iTunes Lookup API.
    Returns None on any failure — this must never raise."""
    try:
        async with httpx.AsyncClient(timeout=_UA_REFRESH_TIMEOUT) as cli:
            r = await cli.get(f"https://itunes.apple.com/lookup?id={app_id}&country={country}")
            if r.status_code != 200:
                return None
            data = r.json()
            results = data.get("results") or []
            if not results:
                return None
            ver = (results[0].get("version") or "").strip()
            return ver or None
    except Exception:
        return None


async def _fetch_latest_ios_versions(limit: int = 7) -> List[str]:
    """
    Fetch the latest `limit` unique iOS versions from ipsw.me API.
    Uses the flagship device (iPhone 16 Pro Max) as it ships the newest builds.
    Returns versions as UA-formatted strings ("26_4_1") or [] on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=_UA_REFRESH_TIMEOUT) as cli:
            # iPhone 16 Pro Max — supports all latest iOS builds
            r = await cli.get("https://api.ipsw.me/v4/device/iPhone17,2")
            if r.status_code != 200:
                return []
            data = r.json()
            fws = data.get("firmwares", [])
            seen, out = set(), []
            for fw in fws:
                v = (fw.get("version") or "").strip()
                if not v or v in seen:
                    continue
                seen.add(v)
                # convert "26.4.1" -> "26_4_1"
                out.append(v.replace(".", "_"))
                if len(out) >= limit:
                    break
            return out
    except Exception:
        return []


async def _fetch_latest_chrome_versions(limit: int = 7) -> List[str]:
    """Fetch latest Chrome stable versions from Google's Chrome Version History API."""
    try:
        async with httpx.AsyncClient(timeout=_UA_REFRESH_TIMEOUT) as cli:
            r = await cli.get(
                "https://versionhistory.googleapis.com/v1/chrome/platforms/win64/channels/stable/versions"
            )
            if r.status_code != 200:
                return []
            versions = r.json().get("versions", [])
            seen, out = set(), []
            for v in versions:
                ver = (v.get("version") or "").strip()
                if not ver or ver in seen:
                    continue
                seen.add(ver)
                out.append(ver)
                if len(out) >= limit:
                    break
            return out
    except Exception:
        return []


async def _fetch_latest_firefox_versions(limit: int = 7) -> List[str]:
    """Fetch latest Firefox stable + older stable versions from Mozilla."""
    try:
        async with httpx.AsyncClient(timeout=_UA_REFRESH_TIMEOUT) as cli:
            r = await cli.get("https://product-details.mozilla.org/1.0/firefox_versions.json")
            if r.status_code != 200:
                return []
            data = r.json()
            latest = (data.get("LATEST_FIREFOX_VERSION") or "").strip()
            devedition = (data.get("FIREFOX_DEVEDITION") or "").strip()
            esr = (data.get("FIREFOX_ESR") or "").strip()
            # Build realistic list with recent minor releases
            candidates = [latest]
            # Add implicit previous versions by decrementing major
            try:
                major = int(latest.split(".")[0])
                for i in range(1, 7):
                    candidates.append(f"{major - i}.0")
            except Exception:
                pass
            if devedition and devedition not in candidates:
                candidates.append(devedition)
            if esr and esr not in candidates:
                candidates.append(esr.replace("esr", ""))
            # Dedup + trim
            seen, out = set(), []
            for v in candidates:
                v = (v or "").strip()
                if v and v not in seen:
                    seen.add(v)
                    out.append(v)
                if len(out) >= limit:
                    break
            return out
    except Exception:
        return []


async def _fetch_latest_android_versions() -> List[dict]:
    """
    Android releases are stable (one major/year) and Google doesn't expose a
    live version API. We derive the latest list from the current Chrome major
    version as a ceiling — Chrome on Android is always in lock-step with
    AOSP, and we bump the Android major yearly to match real-world rollout.
    Returns list of {"version": "16", "sdk": "36"} dicts.
    """
    # Updated ceiling. Android 16 (SDK 36) is the current stable build
    # (released via Android 16 QPR1 in September 2025). This list is the
    # "supported in the field" set — bumping a new entry as each major ships.
    return [
        {"version": "16", "sdk": "36"},
        {"version": "15", "sdk": "35"},
        {"version": "14", "sdk": "34"},
        {"version": "13", "sdk": "33"},
        {"version": "12", "sdk": "31"},
        {"version": "11", "sdk": "30"},
        {"version": "10", "sdk": "29"},
    ]


async def refresh_ua_versions() -> dict:
    """
    Refresh EVERY UA version list from live sources in one go:
        • iOS app versions (iTunes Lookup)
        • iOS OS versions (ipsw.me)
        • Android OS versions (curated ceiling)
        • Desktop Chrome versions (Google Version History)
        • Desktop Firefox versions (Mozilla product-details)
    Returns {"ok": bool, "updated": [...], "failures": [...]}.
    Never raises.
    """
    updated, failures, sources = [], [], {}

    # ─── 1. App versions (iTunes Lookup API) ─────────────────────────
    for app_key, app_id in _ITUNES_APP_IDS.items():
        try:
            latest = await _fetch_itunes_version(app_id)
            if not latest:
                failures.append(app_key)
                continue
            old_head = _APP_VERSIONS.get(app_key, [None])[0]
            _APP_VERSIONS[app_key] = _prepend_and_trim(
                list(_APP_VERSIONS.get(app_key, [])), latest, max_len=7,
            )
            sources[app_key] = "iTunes Lookup"
            if latest != old_head:
                updated.append(f"{app_key}:{latest}")
        except Exception as e:
            logger.warning(f"refresh_ua_versions[{app_key}] failed: {e}")
            failures.append(app_key)

    # ─── 2. iOS OS versions (ipsw.me) ────────────────────────────────
    try:
        latest_ios = await _fetch_latest_ios_versions(limit=7)
        if latest_ios:
            old_head = _IOS_OS_VERSIONS[0] if _IOS_OS_VERSIONS else None
            _IOS_OS_VERSIONS.clear()
            _IOS_OS_VERSIONS.extend(latest_ios)
            sources["ios_os"] = "ipsw.me"
            if latest_ios[0] != old_head:
                updated.append(f"ios_os:{latest_ios[0].replace('_','.')}")
        else:
            failures.append("ios_os")
    except Exception as e:
        logger.warning(f"refresh_ua_versions[ios_os] failed: {e}")
        failures.append("ios_os")

    # ─── 3. Chrome desktop versions (Google Version History API) ─────
    try:
        latest_chrome = await _fetch_latest_chrome_versions(limit=7)
        if latest_chrome:
            old_head = _CHROME_VERSIONS[0] if _CHROME_VERSIONS else None
            _CHROME_VERSIONS.clear()
            _CHROME_VERSIONS.extend(latest_chrome)
            sources["chrome"] = "Google Version History"
            if latest_chrome[0] != old_head:
                updated.append(f"chrome:{latest_chrome[0]}")
        else:
            failures.append("chrome")
    except Exception as e:
        logger.warning(f"refresh_ua_versions[chrome] failed: {e}")
        failures.append("chrome")

    # ─── 4. Firefox desktop versions (Mozilla product-details) ───────
    try:
        latest_ff = await _fetch_latest_firefox_versions(limit=7)
        if latest_ff:
            old_head = _FIREFOX_VERSIONS[0] if _FIREFOX_VERSIONS else None
            _FIREFOX_VERSIONS.clear()
            _FIREFOX_VERSIONS.extend(latest_ff)
            sources["firefox"] = "Mozilla product-details"
            if latest_ff[0] != old_head:
                updated.append(f"firefox:{latest_ff[0]}")
        else:
            failures.append("firefox")
    except Exception as e:
        logger.warning(f"refresh_ua_versions[firefox] failed: {e}")
        failures.append("firefox")

    # ─── 5. Android OS versions (curated ceiling) ────────────────────
    try:
        latest_android = await _fetch_latest_android_versions()
        if latest_android:
            old_head = _ANDROID_OS_VERSIONS[0]["version"] if _ANDROID_OS_VERSIONS else None
            _ANDROID_OS_VERSIONS.clear()
            _ANDROID_OS_VERSIONS.extend(latest_android)
            sources["android_os"] = "Curated (AOSP ceiling)"
            if latest_android[0]["version"] != old_head:
                updated.append(f"android_os:{latest_android[0]['version']}")
    except Exception as e:
        logger.warning(f"refresh_ua_versions[android_os] failed: {e}")
        failures.append("android_os")

    # ─── 6. Update metadata ──────────────────────────────────────────
    _UA_VERSIONS_META["last_refreshed_at"] = datetime.now(timezone.utc).isoformat()
    _UA_VERSIONS_META["last_refresh_ok"] = len(failures) == 0
    _UA_VERSIONS_META["last_refresh_note"] = (
        f"{len(updated)} item(s) bumped" if updated
        else ("All versions already up-to-date" if not failures
              else f"{len(failures)} item(s) failed")
    )
    _UA_VERSIONS_META["sources"].update(sources)

    # ─── 7. Persist snapshot so it survives restarts ─────────────────
    try:
        await main_db.settings.update_one(
            {"key": "ua_versions_snapshot"},
            {"$set": {
                "key": "ua_versions_snapshot",
                "app_versions": _APP_VERSIONS,
                "ios_os_versions": list(_IOS_OS_VERSIONS),
                "android_os_versions": list(_ANDROID_OS_VERSIONS),
                "chrome_versions": list(_CHROME_VERSIONS),
                "firefox_versions": list(_FIREFOX_VERSIONS),
                "meta": _UA_VERSIONS_META,
            }},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"Could not persist UA versions snapshot: {e}")

    logger.info(f"UA versions refreshed: {len(updated)} updated, {len(failures)} failures")
    return {"ok": len(failures) == 0, "updated": updated, "failures": failures, "meta": _UA_VERSIONS_META}


async def _load_ua_versions_snapshot():
    """On startup, load the last-persisted UA version snapshot (if any)."""
    try:
        doc = await main_db.settings.find_one({"key": "ua_versions_snapshot"}, {"_id": 0})
        if not doc:
            return
        stored = doc.get("app_versions") or {}
        for k, v in stored.items():
            if isinstance(v, list) and v:
                _APP_VERSIONS[k] = v[:7]
        ios_stored = doc.get("ios_os_versions") or []
        if isinstance(ios_stored, list) and ios_stored:
            _IOS_OS_VERSIONS.clear()
            _IOS_OS_VERSIONS.extend(ios_stored[:7])
        android_stored = doc.get("android_os_versions") or []
        if isinstance(android_stored, list) and android_stored:
            _ANDROID_OS_VERSIONS.clear()
            _ANDROID_OS_VERSIONS.extend(android_stored[:7])
        chrome_stored = doc.get("chrome_versions") or []
        if isinstance(chrome_stored, list) and chrome_stored:
            _CHROME_VERSIONS.clear()
            _CHROME_VERSIONS.extend(chrome_stored[:7])
        firefox_stored = doc.get("firefox_versions") or []
        if isinstance(firefox_stored, list) and firefox_stored:
            _FIREFOX_VERSIONS.clear()
            _FIREFOX_VERSIONS.extend(firefox_stored[:7])
        meta = doc.get("meta") or {}
        _UA_VERSIONS_META.update({k: meta.get(k, _UA_VERSIONS_META.get(k)) for k in _UA_VERSIONS_META})
    except Exception as e:
        logger.warning(f"Could not load UA versions snapshot: {e}")


async def _auto_refresh_ua_versions_task():
    """Background task — runs refresh on startup, then every 24 h forever."""
    # Load persisted snapshot first so we never regress between restarts.
    await _load_ua_versions_snapshot()
    # Sleep 10s before first live refresh so startup isn't blocked.
    await asyncio.sleep(10)
    while True:
        try:
            await refresh_ua_versions()
        except Exception as e:
            logger.error(f"UA versions auto-refresh failed: {e}")
        await asyncio.sleep(_UA_REFRESH_INTERVAL_SECONDS)




# Modern iOS-only device pool alias — kept for references elsewhere. Now just
# the iPhone subset of the main iOS pool (which is fully modernised).
# (See `_IOS_DEVICES` above — every entry runs iOS 18.x in 2026 anyway.)

_CHROME_VERSIONS = ["147.0.7727.102", "146.0.7680.177", "145.0.7600.130", "144.0.7559.63", "143.0.7637.60", "142.0.7835.13", "141.0.7390.72"]
_FIREFOX_VERSIONS = ["149.0.2", "149.0.1", "149.0", "148.0.1", "148.0", "147.0.2", "147.0"]

# Desktop device pool
_DESKTOP_DEVICES = [
    {"brand":"Windows","model":"Win11","name":"Windows 11 PC","os":"Windows NT 10.0; Win64; x64"},
    {"brand":"Windows","model":"Win10","name":"Windows 10 PC","os":"Windows NT 10.0; WOW64"},
    {"brand":"Mac","model":"Intel","name":"Mac (Intel)","os":"Macintosh; Intel Mac OS X 10_15_7"},
    {"brand":"Mac","model":"AppleSilicon","name":"Mac (Apple Silicon)","os":"Macintosh; Intel Mac OS X 14_4"},
    {"brand":"Linux","model":"x64","name":"Linux PC","os":"X11; Linux x86_64"},
    {"brand":"Linux","model":"Ubuntu","name":"Ubuntu PC","os":"X11; Ubuntu; Linux x86_64"},
]

def _rand_build_id() -> int:
    return random.randint(100_000_000, 999_999_999)

def _ua_instagram_android(d: dict, app_ver: str, chrome_ver: str, region: Optional[dict] = None, resolution: Optional[str] = None) -> str:
    locale = (region or {}).get("posix_locale", "en_US")
    res = resolution or d["res"]
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"Instagram {app_ver} Android ({d['sdk']}/{d['and_ver']}; {d['dpi']}; {res}; "
        f"{d['vendor']}; {d['model']}; {d['soc']}; {d['chipset']}; {locale}; {_rand_build_id()}; IABMV/1)"
    )

def _ua_instagram_ios(d: dict, app_ver: str, region: Optional[dict] = None, resolution: Optional[str] = None) -> str:
    posix = (region or {}).get("posix_locale", "en_US")
    lang = (region or {}).get("lang_tag", "en-US")
    res = resolution or d["res"]
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU {'iPhone' if d['brand']=='iPhone' else 'iPad'} OS {d['ios']} like Mac OS X) "
        f"AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Instagram {app_ver} "
        f"({d['model']}; iOS {d['ios']}; {posix}; {lang}; scale={d['scale']}; {res}; {_rand_build_id()})"
    )

def _ua_facebook_android(d: dict, app_ver: str, chrome_ver: str, region: Optional[dict] = None) -> str:
    # Matches user's real example: ...Mobile Safari/537.36 [FB_IAB/FB4A;FBAV/556.0.0.59.68;]
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"[FB_IAB/FB4A;FBAV/{app_ver};]"
    )

def _ua_facebook_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    fbbv = random.randint(500_000_000, 999_999_999)
    fblc = (region or {}).get("posix_locale", "en_US")
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Mobile/15E148 [FBAN/FBIOS;FBDV/{d['model']};FBMD/iPhone;FBSN/iOS;"
        f"FBSV/{d['ios'].replace('_','.')};FBSS/{int(float(d['scale']))};FBID/phone;FBLC/{fblc};FBOP/5;FBRV/{fbbv};IABMV/1]"
    )

def _ua_pinterest_android(d: dict, app_ver: str) -> str:
    """
    In-app webview format (same shape as Instagram/Facebook).
    Example: Mozilla/5.0 (Linux; Android 14; Pixel 7 Build/UP1A.231105.003; wv) AppleWebKit/537.36
             (KHTML, like Gecko) Version/4.0 Chrome/144.0.7559.63 Mobile Safari/537.36
             [Pinterest/Android]
    """
    chrome_ver = random.choice(_CHROME_VERSIONS)
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"[Pinterest/Android] Pinterest/{app_ver}"
    )

def _ua_pinterest_ios(d: dict, app_ver: str) -> str:
    """
    In-app webview format for iOS Pinterest.
    Example: Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15
             (KHTML, like Gecko) Mobile/15E148 [Pinterest/iOS] Pinterest/11.37.0
    """
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Mobile/15E148 [Pinterest/iOS] Pinterest/{app_ver}"
    )

def _ua_snapchat_android(d: dict, app_ver: str) -> str:
    """
    In-app webview format (same shape as Instagram/Facebook).
    """
    chrome_ver = random.choice(_CHROME_VERSIONS)
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"Snapchat/{app_ver} (Android; {d['and_ver']}; gzip)"
    )

def _ua_snapchat_ios(d: dict, app_ver: str) -> str:
    """
    In-app webview format for iOS Snapchat.
    """
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Mobile/15E148 Snapchat/{app_ver} ({d['model']}; iOS {d['ios'].replace('_','.')}; gzip)"
    )

def _ua_tiktok_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """
    Real TikTok iOS in-app UA format (`musical_ly_` only).
    Example (2025-2026 modern build):
        Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15
        (KHTML, like Gecko) Mobile/15E148 musical_ly_39.5.0 JsSdk/2.0
        NetType/WIFI Channel/App Store ByteLocale/en Region/US
    """
    r = region or _pick_region(None)
    byte_locale = r["byte_locale"]
    region_code = r["code"]
    # Real-world NetType distribution: WIFI ~70%, 4G ~25%, 5G ~5%
    net_type = random.choices(["WIFI", "4G", "5G"], weights=[70, 25, 5], k=1)[0]
    # Channel is always "App Store" on iOS (TikTok isn't side-loaded).
    return (
        f"Mozilla/5.0 (iPhone; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Mobile/15E148 musical_ly_{app_ver} JsSdk/2.0 "
        f"NetType/{net_type} Channel/App Store "
        f"ByteLocale/{byte_locale} Region/{region_code}"
    )


def _ua_tiktok_android(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """In-app webview format — matches Instagram/Facebook shape."""
    chrome_ver = random.choice(_CHROME_VERSIONS)
    webview_hash = ''.join(random.choices('abcdef0123456789', k=7))
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"musical_ly_{app_ver} trill BytedanceWebview/{webview_hash}"
    )

# ─── YouTube in-app UAs ──────────────────────────────────────────────
def _ua_youtube_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real YouTube iOS in-app UA format.
    Example: com.google.ios.youtube/20.15.3 (iPhone17,2; U; CPU iOS 26_4_1 like Mac OS X; en_US)
    """
    locale = (region or {}).get("posix_locale", "en_US")
    return (
        f"com.google.ios.youtube/{app_ver} ({d['model']}; U; CPU iOS {d['ios']} "
        f"like Mac OS X; {locale})"
    )

def _ua_youtube_android(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real YouTube Android in-app UA.
    Example: com.google.android.youtube/20.15.3 (Linux; U; Android 16; SM-S928B) gzip
    """
    return (
        f"com.google.android.youtube/{app_ver} (Linux; U; Android {d['and_ver']}; "
        f"{d['model']} Build/{d['build']}) gzip"
    )

# ─── WhatsApp in-app UAs ─────────────────────────────────────────────
def _ua_whatsapp_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real WhatsApp iOS UA uses CFNetwork/Darwin — not Mozilla-style.
    Example: WhatsApp/25.4.82 CFNetwork/3826.500.131 Darwin/24.5.0
    """
    darwin_major = 24 if d["ios"].startswith("26") else 23
    darwin = f"{darwin_major}.{random.randint(1,6)}.0"
    cfnet = f"{3600 + random.randint(100,900)}.{random.randint(100,600)}.{random.randint(10,99)}"
    return f"WhatsApp/{app_ver} CFNetwork/{cfnet} Darwin/{darwin}"

def _ua_whatsapp_android(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real WhatsApp Android UA."""
    chrome_ver = random.choice(_CHROME_VERSIONS)
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']} Build/{d['build']}; wv) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/{chrome_ver} Mobile Safari/537.36 "
        f"WhatsApp/{app_ver}/A"
    )

# ─── Google Search (GSA) in-app UAs ──────────────────────────────────
def _ua_gsearch_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real Google Search iOS app UA (uses GSA/ token)."""
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Mobile/15E148 GSA/{app_ver} Mobile/15E148 Safari/604.1"
    )

def _ua_gsearch_android(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real Google Search Android (GSA) app UA."""
    chrome_ver = random.choice(_CHROME_VERSIONS)
    major = app_ver.split(".")[0] if app_ver else "16"
    gsa_android = f"{major}.{random.randint(10,20)}.{random.randint(20,40)}.{random.randint(20,40)}.arm64"
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_ver} Mobile Safari/537.36 GSA/{gsa_android}"
    )

# ─── Google Chrome mobile ("Google Native" browser) ──────────────────
def _ua_gchrome_ios(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real Chrome for iOS UA (uses `CriOS/` token)."""
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) CriOS/{app_ver} Mobile/15E148 Safari/604.1"
    )

def _ua_gchrome_android(d: dict, app_ver: str, region: Optional[dict] = None) -> str:
    """Real Chrome for Android mobile UA."""
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{app_ver} Mobile Safari/537.36"
    )



def _ua_chrome_android(d: dict, chrome_ver: str) -> str:
    return (
        f"Mozilla/5.0 (Linux; Android {d['and_ver']}; {d['model']}) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{chrome_ver} Mobile Safari/537.36"
    )

def _ua_safari_ios(d: dict) -> str:
    major = d["ios"].split("_")[0]
    return (
        f"Mozilla/5.0 ({d['brand']}; CPU iPhone OS {d['ios']} like Mac OS X) AppleWebKit/605.1.15 "
        f"(KHTML, like Gecko) Version/{major}.0 Mobile/15E148 Safari/604.1"
    )

def _ua_chrome_desktop(d: dict, chrome_ver: str) -> str:
    return (
        f"Mozilla/5.0 ({d['os']}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{chrome_ver} Safari/537.36"
    )

def _ua_firefox_desktop(d: dict) -> str:
    ff_ver = random.choice(["132.0","131.0","130.0.1","129.0"])
    os_for_ff = d['os'].replace("; Win64; x64", "; Win64; x64; rv:" + ff_ver)
    if "rv:" not in os_for_ff:
        os_for_ff = d['os'] + f"; rv:{ff_ver}"
    return f"Mozilla/5.0 ({os_for_ff}) Gecko/20100101 Firefox/{ff_ver}"

def _ua_safari_desktop(d: dict) -> str:
    if "Mac" in d.get('os',''):
        return (
            f"Mozilla/5.0 ({d['os']}) AppleWebKit/605.1.15 (KHTML, like Gecko) "
            f"Version/17.4 Safari/605.1.15"
        )
    return _ua_chrome_desktop(d, random.choice(_CHROME_VERSIONS))

def _find_device_by_id(device_id: str):
    """device_id format: '<brand>|<model>' - returns (device, kind) or (None, None)."""
    if not device_id or "|" not in device_id:
        return None, None
    brand, model = device_id.split("|", 1)
    brand_l = brand.strip().lower()
    model_l = model.strip().lower()
    for d in _ANDROID_DEVICES:
        if d["brand"].lower() == brand_l and d["model"].lower() == model_l:
            return d, "android"
    for d in _IOS_DEVICES:
        if d["brand"].lower() == brand_l and d["model"].lower() == model_l:
            return d, "ios"
    for d in _DESKTOP_DEVICES:
        if d["brand"].lower() == brand_l and (d["model"].lower() == model_l or d["name"].lower() == model_l):
            return d, "desktop"
    return None, None

@api_router.get("/user-agents/options")
async def get_ua_options(user: dict = Depends(get_current_user)):
    """Return the list of available apps, platforms, devices and versions so the UI can show pickers."""
    return {
        "apps": ["instagram", "facebook", "tiktok", "pinterest", "snapchat", "youtube", "whatsapp", "gsearch", "gchrome", "chrome"],
        "platforms": ["any", "android", "ios", "desktop"],
        "app_versions": _APP_VERSIONS,
        "android_devices": [
            {"id": f"{d['brand']}|{d['model']}", "label": f"{d['brand']} {d['model']}", "os": "android"}
            for d in _ANDROID_DEVICES
        ],
        "ios_devices": [
            {"id": f"{d['brand']}|{d['model']}", "label": d['name'], "os": "ios"}
            for d in _IOS_DEVICES
        ],
        "desktop_devices": [
            {"id": f"{d['brand']}|{d['model']}", "label": d['name'], "os": "desktop"}
            for d in _DESKTOP_DEVICES
        ],
        "regions": [
            {"code": r["code"], "country": r["country"], "locale": r["byte_locale"]}
            for r in _REGIONS
        ],
        "resolutions": _MOBILE_RESOLUTIONS,
        "ios_os_versions": [v.replace("_", ".") for v in _IOS_OS_VERSIONS],
        "android_os_versions": [v["version"] for v in _ANDROID_OS_VERSIONS],
        "chrome_versions": list(_CHROME_VERSIONS),
        "firefox_versions": list(_FIREFOX_VERSIONS),
        "versions_meta": _UA_VERSIONS_META,
    }


# ---------- User Agent CHECKER (analyze / summarise a pasted UA) ----------

class UACheckRequest(BaseModel):
    user_agent: str
    # When a list is provided we return one analysis per UA (bulk).
    user_agents: Optional[List[str]] = None


def _detect_inapp(ua: str) -> dict:
    """
    Detect in-app webviews / native-app UAs that the `user_agents` library
    doesn't recognise (TikTok, Instagram, Facebook, Pinterest, Snapchat).
    Returns {"app": str or None, "app_name": str, "app_version": str or None, "is_inapp": bool}
    """
    import re
    ua_low = ua or ""
    # TikTok  →  musical_ly_XX.X.X   or   trill_XX.X.X
    m = re.search(r"(?:musical_ly|trill)_([\d.]+)", ua_low)
    if m:
        return {"app": "tiktok", "app_name": "TikTok", "app_version": m.group(1), "is_inapp": True}
    # Instagram  →  Instagram 412.0.0.35.87
    m = re.search(r"Instagram\s+([\d.]+)", ua_low)
    if m:
        return {"app": "instagram", "app_name": "Instagram", "app_version": m.group(1), "is_inapp": True}
    # Facebook  →  FBAV/556.0.0.59.68  or  FB_IAB
    m = re.search(r"FBAV/([\d.]+)", ua_low)
    if m:
        return {"app": "facebook", "app_name": "Facebook", "app_version": m.group(1), "is_inapp": True}
    if "FB_IAB" in ua_low or "FBAN/FBIOS" in ua_low:
        return {"app": "facebook", "app_name": "Facebook", "app_version": None, "is_inapp": True}
    # Pinterest
    m = re.search(r"Pinterest/([\d.]+)", ua_low)
    if m:
        return {"app": "pinterest", "app_name": "Pinterest", "app_version": m.group(1), "is_inapp": True}
    if "[Pinterest/" in ua_low:
        return {"app": "pinterest", "app_name": "Pinterest", "app_version": None, "is_inapp": True}
    # Snapchat
    m = re.search(r"Snapchat/([\d.]+)", ua_low)
    if m:
        return {"app": "snapchat", "app_name": "Snapchat", "app_version": m.group(1), "is_inapp": True}
    # YouTube (iOS uses com.google.ios.youtube/; Android uses com.google.android.youtube/)
    m = re.search(r"com\.google\.(?:ios|android)\.youtube/([\d.]+)", ua_low)
    if m:
        return {"app": "youtube", "app_name": "YouTube", "app_version": m.group(1), "is_inapp": True}
    # WhatsApp
    m = re.search(r"WhatsApp/([\d.]+)", ua_low)
    if m:
        return {"app": "whatsapp", "app_name": "WhatsApp", "app_version": m.group(1), "is_inapp": True}
    # Google Search App (GSA)
    m = re.search(r"GSA/([\d.]+)", ua_low)
    if m:
        return {"app": "gsearch", "app_name": "Google Search", "app_version": m.group(1), "is_inapp": True}
    # Chrome on iOS ("Google Native" browser)
    m = re.search(r"CriOS/([\d.]+)", ua_low)
    if m:
        return {"app": "gchrome", "app_name": "Google Chrome (iOS)", "app_version": m.group(1), "is_inapp": True}
    # Twitter
    m = re.search(r"TwitterAndroid/([\d.]+)|Twitter for iPhone/([\d.]+)", ua_low)
    if m:
        ver = m.group(1) or m.group(2)
        return {"app": "twitter", "app_name": "Twitter/X", "app_version": ver, "is_inapp": True}
    # LinkedIn
    m = re.search(r"LinkedInApp/([\d.]+)", ua_low)
    if m:
        return {"app": "linkedin", "app_name": "LinkedIn", "app_version": m.group(1), "is_inapp": True}
    return {"app": None, "app_name": "Browser", "app_version": None, "is_inapp": False}


def _detect_tiktok_metadata(ua: str) -> dict:
    """Extract TikTok-specific extras (NetType, Channel, ByteLocale, Region)."""
    import re
    out = {}
    patterns = {
        "net_type":  r"NetType/([A-Za-z0-9]+)",
        "channel":   r"Channel/([^\s;]+(?:\s[^\s;]+)?)",
        "locale":    r"ByteLocale/([A-Za-z0-9_\-]+)",
        "region":    r"Region/([A-Z]{2})",
        "jssdk":     r"JsSdk/([\d.]+)",
    }
    for key, pat in patterns.items():
        m = re.search(pat, ua or "")
        if m:
            out[key] = m.group(1).strip()
    return out


def _analyze_ua(ua: str) -> dict:
    """Parse a single UA and return a detailed, structured summary."""
    import re
    ua = (ua or "").strip()
    if not ua:
        return {"valid": False, "error": "Empty user agent"}

    result = {"valid": True, "user_agent": ua, "length": len(ua)}

    # 1. Core parse via `user_agents` lib
    try:
        parsed = parse(ua)
        result["browser"] = {
            "family": parsed.browser.family or None,
            "version": parsed.browser.version_string or None,
        }
        result["os"] = {
            "family": parsed.os.family or None,
            "version": parsed.os.version_string or None,
        }
        result["device"] = {
            "family": parsed.device.family or None,
            "brand": parsed.device.brand or None,
            "model": parsed.device.model or None,
        }
        result["flags"] = {
            "is_mobile": parsed.is_mobile,
            "is_tablet": parsed.is_tablet,
            "is_pc": parsed.is_pc,
            "is_bot": parsed.is_bot,
            "is_touch_capable": parsed.is_touch_capable,
        }
    except Exception as e:
        result["browser"] = result["os"] = result["device"] = {}
        result["flags"] = {}
        result["parse_error"] = str(e)

    # 2. In-app detection
    inapp = _detect_inapp(ua)
    result["app"] = inapp

    # 3. TikTok-specific metadata (NetType / Region / Locale / Channel)
    if inapp.get("app") == "tiktok":
        result["tiktok_metadata"] = _detect_tiktok_metadata(ua)

    # 4. Normalised platform label
    os_family = (result.get("os", {}).get("family") or "").lower()
    if "ios" in os_family or "iphone" in ua.lower() or "ipad" in ua.lower():
        platform = "iOS"
    elif "android" in os_family or "android" in ua.lower():
        platform = "Android"
    elif "windows" in os_family:
        platform = "Windows"
    elif "mac" in os_family:
        platform = "macOS"
    elif "linux" in os_family:
        platform = "Linux"
    else:
        platform = result.get("os", {}).get("family") or "Unknown"
    result["platform"] = platform

    # 5. Referrer-source guess (what TrackMaster will categorise this UA as)
    source_guess = inapp.get("app") or "browser"
    source_map = {
        "tiktok": "TikTok", "instagram": "Instagram", "facebook": "Facebook",
        "pinterest": "Pinterest", "snapchat": "Snapchat", "twitter": "Twitter/X",
        "linkedin": "LinkedIn",
        "youtube": "YouTube", "whatsapp": "WhatsApp",
        "gsearch": "Google Search", "gchrome": "Google Chrome",
        "browser": "Direct / Browser",
    }
    result["traffic_source_guess"] = source_map.get(source_guess, source_guess.title())

    # 6. Verdict — does the UA "look real"?
    issues = []
    if not ua.startswith("Mozilla/"):
        issues.append("UA does not start with 'Mozilla/5.0' — most real apps do.")
    if len(ua) < 40:
        issues.append("UA is suspiciously short (< 40 chars).")
    if inapp["is_inapp"] and inapp["app"] == "tiktok":
        # TikTok UA should have musical_ly_ and JsSdk/ and Channel/
        if "JsSdk/" not in ua:
            issues.append("TikTok iOS UA missing `JsSdk/` — real app always includes it.")
        if "Channel/" not in ua:
            issues.append("TikTok UA missing `Channel/` — real app always includes it.")
    if platform == "iOS" and "AppleWebKit/605.1.15" not in ua:
        issues.append("iOS UA missing `AppleWebKit/605.1.15` — Safari/WebKit signature.")
    if platform == "Android" and "Mobile Safari/537.36" not in ua and "Android" in ua:
        # Only flag webview-style UAs (FB_IAB etc.)
        if any(x in ua for x in ["FB_IAB", "Instagram", "musical_ly", "Pinterest", "Snapchat"]):
            issues.append("Android webview UA missing `Mobile Safari/537.36` — unusual.")

    result["verdict"] = {
        "looks_realistic": len(issues) == 0,
        "issues": issues,
    }

    # 7. Human-readable one-line summary
    parts = []
    parts.append(inapp["app_name"])
    if inapp.get("app_version"):
        parts.append(f"v{inapp['app_version']}")
    parts.append(f"on {platform}")
    if result.get("os", {}).get("version"):
        parts.append(result["os"]["version"])
    device_fam = result.get("device", {}).get("family")
    if device_fam and device_fam not in ("Other", "Spider"):
        parts.append(f"— {device_fam}")
    result["summary"] = " ".join(parts)

    return result


@api_router.post("/user-agents/check")
async def check_user_agent(payload: UACheckRequest, user: dict = Depends(get_current_user)):
    """
    Analyze a single UA or a list of UAs and return detailed metadata:
    browser, OS, device, in-app detection, TikTok metadata, realism verdict,
    and a one-line human summary.
    """
    # Bulk mode
    if payload.user_agents:
        uas = [u for u in payload.user_agents if u and u.strip()]
        if len(uas) > 1000:
            raise HTTPException(status_code=400, detail="Max 1000 UAs per bulk request")
        return {"count": len(uas), "results": [_analyze_ua(u) for u in uas]}

    # Single
    ua = (payload.user_agent or "").strip()
    if not ua:
        raise HTTPException(status_code=400, detail="user_agent is required")
    return _analyze_ua(ua)




@api_router.post("/user-agents/generate")
async def generate_user_agents(payload: UAGenerateRequest, user: dict = Depends(get_current_user)):
    """Generate realistic user agents. Returns JSON or XLSX based on payload.format."""
    count = max(1, min(int(payload.count or 10), 50000))
    app = (payload.app or "instagram").lower().strip()
    platform = (payload.platform or "any").lower().strip()
    brand_filter = (payload.brand or "").lower().strip()
    want_format = (payload.format or "json").lower().strip()

    # If user requested a specific device, resolve once up-front
    pinned_device = None
    pinned_kind = None
    if payload.device_id:
        pinned_device, pinned_kind = _find_device_by_id(payload.device_id)
        if not pinned_device:
            raise HTTPException(status_code=400, detail=f"Unknown device_id: {payload.device_id}")

    # Multi-device pool — user selected 2-N exact devices to cycle through
    multi_device_pool = None
    multi_device_kind = None
    if payload.device_ids:
        resolved = []
        kinds_seen = set()
        for did in payload.device_ids:
            dev, k = _find_device_by_id(did)
            if not dev:
                raise HTTPException(status_code=400, detail=f"Unknown device_id: {did}")
            resolved.append(dev)
            kinds_seen.add(k)
        if resolved:
            multi_device_pool = resolved
            # if all same kind use that; else "mixed"
            multi_device_kind = (list(kinds_seen)[0] if len(kinds_seen) == 1 else "mixed")

    def _pick_device_pool():
        if pinned_device:
            return [pinned_device], pinned_kind
        if multi_device_pool:
            return list(multi_device_pool), multi_device_kind
        if platform == "ios":
            return list(_IOS_DEVICES), "ios"
        if platform == "android":
            return list(_ANDROID_DEVICES), "android"
        if platform == "desktop":
            return list(_DESKTOP_DEVICES), "desktop"
        # Any
        pool = _ANDROID_DEVICES + _IOS_DEVICES
        return pool, "mixed"

    base_pool, pool_kind = _pick_device_pool()

    # TikTok iOS runs on iPhone much more than iPad — stick to iPhones only so
    # every generated UA feels authentic to the platform.
    if app == "tiktok" and not pinned_device:
        if platform == "ios":
            base_pool = [d for d in base_pool if d.get("brand") == "iPhone"]
            pool_kind = "ios"
        elif platform == "any":
            base_pool = [
                d for d in base_pool
                if "and_ver" in d or d.get("brand") == "iPhone"
            ]

    if brand_filter and brand_filter != "any" and not pinned_device:
        def _match(d):
            return (
                brand_filter == (d.get("brand","").lower())
                or brand_filter == (d.get("vendor","").lower())
                or brand_filter in (d.get("name","").lower())
            )
        filtered = [d for d in base_pool if _match(d)]
        if filtered:
            base_pool = filtered

    if not base_pool:
        raise HTTPException(status_code=400, detail="No devices match your filters")

    # Validate resolution (if pinned)
    pinned_resolution = (payload.resolution or "").strip() or None
    if pinned_resolution:
        import re
        if not re.match(r"^\d{3,5}x\d{3,5}$", pinned_resolution):
            raise HTTPException(status_code=400, detail=f"Invalid resolution format (expected e.g. '1080x2340'): {pinned_resolution}")

    # Multi-resolution pool
    resolutions_pool = None
    if payload.resolutions:
        import re
        for r in payload.resolutions:
            if not re.match(r"^\d{3,5}x\d{3,5}$", r or ""):
                raise HTTPException(status_code=400, detail=f"Invalid resolution format: {r}")
        resolutions_pool = list(payload.resolutions)

    # Validate OS version (if pinned)
    pinned_os = (payload.os_version or "").strip() or None
    if pinned_os:
        import re
        if not re.match(r"^\d{1,2}(?:[._]\d{1,2}){0,2}$", pinned_os):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid OS version (expected e.g. '18_3', '18.3', '14'): {pinned_os}",
            )

    # Multi-OS version pool
    os_versions_pool = None
    if payload.os_versions:
        import re
        for ov in payload.os_versions:
            if not re.match(r"^\d{1,2}(?:[._]\d{1,2}){0,2}$", ov or ""):
                raise HTTPException(status_code=400, detail=f"Invalid OS version: {ov}")
        os_versions_pool = list(payload.os_versions)

    # Multi-app version pool
    app_versions_pool = list(payload.app_versions) if payload.app_versions else None

    # Resolve pinned region (if any) — else it's picked per-UA at random
    pinned_region = None
    if payload.region:
        pinned_region = next(
            (r for r in _REGIONS if r["code"].upper() == payload.region.upper()),
            None,
        )
        if not pinned_region:
            raise HTTPException(status_code=400, detail=f"Unknown region code: {payload.region}")

    # Multi-region pool
    regions_pool = None
    if payload.regions:
        regs = []
        for rc in payload.regions:
            match = next((r for r in _REGIONS if r["code"].upper() == (rc or "").upper()), None)
            if not match:
                raise HTTPException(status_code=400, detail=f"Unknown region code: {rc}")
            regs.append(match)
        regions_pool = regs

    results = []
    for _ in range(count):
        device = random.choice(base_pool)
        kind = pool_kind if pool_kind != "mixed" else ("android" if "and_ver" in device else "ios")
        if pinned_device:
            kind = pinned_kind

        # Per-UA OS version: pinned > pool > device default
        per_ua_os = pinned_os
        if not per_ua_os and os_versions_pool:
            per_ua_os = random.choice(os_versions_pool)
        device = _apply_os_version_override(device, kind, per_ua_os)

        # Per-UA app version: pinned > pool > random from master list
        if payload.app_version:
            app_ver = payload.app_version
        elif app_versions_pool:
            app_ver = random.choice(app_versions_pool)
        else:
            app_ver = random.choice(_APP_VERSIONS.get(app, ["1.0.0"]))
        chrome_ver = random.choice(_CHROME_VERSIONS)

        # Per-UA region: pinned > pool > random
        if pinned_region:
            region_for_ua = pinned_region
        elif regions_pool:
            region_for_ua = random.choice(regions_pool)
        else:
            region_for_ua = _pick_region(None)

        # Per-UA resolution: pinned > pool > device default
        per_ua_resolution = pinned_resolution
        if not per_ua_resolution and resolutions_pool:
            per_ua_resolution = random.choice(resolutions_pool)

        if kind == "android":
            if app == "instagram":
                ua = _ua_instagram_android(device, app_ver, chrome_ver, region=region_for_ua, resolution=per_ua_resolution)
            elif app == "facebook":
                ua = _ua_facebook_android(device, app_ver, chrome_ver, region=region_for_ua)
            elif app == "tiktok":
                ua = _ua_tiktok_android(device, app_ver, region=region_for_ua)
            elif app == "pinterest":
                ua = _ua_pinterest_android(device, app_ver)
            elif app == "snapchat":
                ua = _ua_snapchat_android(device, app_ver)
            elif app == "youtube":
                ua = _ua_youtube_android(device, app_ver, region=region_for_ua)
            elif app == "whatsapp":
                ua = _ua_whatsapp_android(device, app_ver, region=region_for_ua)
            elif app == "gsearch":
                ua = _ua_gsearch_android(device, app_ver, region=region_for_ua)
            elif app == "gchrome":
                ua = _ua_gchrome_android(device, app_ver, region=region_for_ua)
            else:
                ua = _ua_chrome_android(device, chrome_ver)
            device_label = f"{device['brand']} {device['model']}"
        elif kind == "ios":
            if app == "instagram":
                ua = _ua_instagram_ios(device, app_ver, region=region_for_ua, resolution=per_ua_resolution)
            elif app == "facebook":
                ua = _ua_facebook_ios(device, app_ver, region=region_for_ua)
            elif app == "tiktok":
                ua = _ua_tiktok_ios(device, app_ver, region=region_for_ua)
            elif app == "pinterest":
                ua = _ua_pinterest_ios(device, app_ver)
            elif app == "snapchat":
                ua = _ua_snapchat_ios(device, app_ver)
            elif app == "youtube":
                ua = _ua_youtube_ios(device, app_ver, region=region_for_ua)
            elif app == "whatsapp":
                ua = _ua_whatsapp_ios(device, app_ver, region=region_for_ua)
            elif app == "gsearch":
                ua = _ua_gsearch_ios(device, app_ver, region=region_for_ua)
            elif app == "gchrome":
                ua = _ua_gchrome_ios(device, app_ver, region=region_for_ua)
            else:
                ua = _ua_safari_ios(device)
            device_label = device.get("name") or device.get("model", "")
        else:  # desktop
            # On desktop, in-app UAs don't exist -> use a regular browser UA.
            # Pick Chrome/Firefox/Safari depending on OS.
            browser_choice = random.choice(["chrome","firefox"]) if "Mac" not in device.get("os","") else random.choice(["chrome","safari","firefox"])
            if browser_choice == "chrome":
                ua = _ua_chrome_desktop(device, chrome_ver)
            elif browser_choice == "safari":
                ua = _ua_safari_desktop(device)
            else:
                ua = _ua_firefox_desktop(device)
            device_label = device.get("name", "Desktop")

        # Derive displayable OS version from the (possibly overridden) device
        if kind == "ios":
            os_version_display = device.get("ios", "").replace("_", ".")
        elif kind == "android":
            os_version_display = device.get("and_ver")
        else:
            os_version_display = None

        results.append({
            "user_agent": ua,
            "device": device_label,
            "platform": kind,
            "app": app,
            "app_version": app_ver if app in _APP_VERSIONS else None,
            "os_version": os_version_display,
            "region": region_for_ua["code"],
            "country": region_for_ua["country"],
            "resolution": per_ua_resolution or (device.get("res") if kind != "desktop" else None),
        })

    # XLSX export path
    if want_format == "xlsx":
        import pandas as pd
        import io
        df = pd.DataFrame(results, columns=["user_agent","device","platform","app","app_version","os_version","region","country","resolution"])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='User Agents', index=False)
        output.seek(0)
        download_name = f"user_agents_{app}_{platform}_{len(results)}.xlsx"
        return Response(
            content=output.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{download_name}"',
                "X-UA-Count": str(len(results)),
                "Access-Control-Expose-Headers": "X-UA-Count, Content-Disposition",
            }
        )

    return {"user_agents": results, "count": len(results), "app": app, "platform": platform}


# ==================== REAL TRAFFIC SENDER (via residential proxies) ====================

class RealTrafficRequest(BaseModel):
    link_id: str
    proxies: List[str]                   # lines in "user:pass@host:port" or "host:port" format
    user_agents: List[str]
    total_clicks: int = 10
    concurrency: int = 3
    skip_duplicate: bool = True
    skip_vpn: bool = True
    allowed_countries: Optional[List[str]] = None   # ISO names; empty/None = any
    follow_redirect: bool = False        # if True, also GET the offer URL after redirect
    no_repeat_proxy: bool = False        # if True, each proxy line can be used at most once per run
    target_url: Optional[str] = None     # optional explicit PUBLIC URL to hit (overrides auto-detection)
    duration_minutes: Optional[float] = None  # if set, pace the run so it completes over this many minutes


def _parse_proxy_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a proxy line. Supports:
        user:pass@host:port
        host:port
        http://user:pass@host:port
    Returns dict with url + auth, or None if invalid.
    """
    s = (line or "").strip()
    if not s:
        return None
    # Drop scheme if present
    if s.startswith("http://") or s.startswith("https://"):
        s = s.split("://", 1)[1]

    auth = None
    host_port = s
    if "@" in s:
        auth_part, host_port = s.rsplit("@", 1)
        if ":" in auth_part:
            user, pwd = auth_part.split(":", 1)
        else:
            user, pwd = auth_part, ""
        auth = (user, pwd)

    if ":" not in host_port:
        return None
    host, port_str = host_port.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        return None

    proxy_url = f"http://{host}:{port}"
    return {"proxy_url": proxy_url, "auth": auth, "raw": line.strip()}


async def _proxy_exit_ip(session, proxy: Dict[str, Any], ua: str, timeout: float = 10.0) -> Optional[str]:
    """Hit ipify through the given proxy to discover its exit IP."""
    import aiohttp
    kwargs = {
        "proxy": proxy["proxy_url"],
        "headers": {"User-Agent": ua},
        "timeout": aiohttp.ClientTimeout(total=timeout),
        "ssl": False,
    }
    if proxy.get("auth"):
        kwargs["proxy_auth"] = aiohttp.BasicAuth(proxy["auth"][0], proxy["auth"][1])
    try:
        async with session.get("https://api.ipify.org?format=json", **kwargs) as r:
            if r.status == 200:
                data = await r.json(content_type=None)
                return (data or {}).get("ip")
    except Exception as e:
        logger.debug(f"Proxy probe failed for {proxy['raw']}: {e}")
        return None
    return None


async def _fire_real_click(session, proxy: Dict[str, Any], ua: str, target_url: str,
                           follow_redirect: bool, timeout: float = 15.0) -> Dict[str, Any]:
    """Fire a GET against target_url through the proxy with the given UA."""
    import aiohttp
    out = {"status": None, "redirect_to": None, "final_status": None, "error": None}
    kwargs = {
        "proxy": proxy["proxy_url"],
        "headers": {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "timeout": aiohttp.ClientTimeout(total=timeout),
        "ssl": False,
        "allow_redirects": False,
    }
    if proxy.get("auth"):
        kwargs["proxy_auth"] = aiohttp.BasicAuth(proxy["auth"][0], proxy["auth"][1])
    try:
        async with session.get(target_url, **kwargs) as r:
            out["status"] = r.status
            out["redirect_to"] = r.headers.get("Location")
        if follow_redirect and out["redirect_to"]:
            async with session.get(
                out["redirect_to"],
                proxy=kwargs["proxy"],
                proxy_auth=kwargs.get("proxy_auth"),
                headers=kwargs["headers"],
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False,
                allow_redirects=True,
            ) as r2:
                out["final_status"] = r2.status
    except Exception as e:
        out["error"] = str(e)
    return out


@api_router.post("/traffic/send-real")
async def send_real_traffic(
    payload: RealTrafficRequest,
    request: Request,
    user: dict = Depends(get_current_user_with_fresh_data),
):
    """
    Send REAL HTTP traffic to a user's short link through residential proxies.
    Each click:
      1. Picks next (proxy, UA) pair.
      2. Probes the proxy to discover its exit IP.
      3. Optionally pre-filters that exit IP: duplicate check, VPN check, country whitelist.
      4. If it passes, fires `GET /t/{short_code}` through the proxy with that UA.
         The normal redirect/click-logging code path then runs with the proxy's real IP
         as the client IP - so the click shows up in the Clicks table exactly like an
         organic visit.
    Streams NDJSON progress to the caller.
    """
    import aiohttp

    check_user_feature(user, "real_traffic")

    if payload.total_clicks < 1 or payload.total_clicks > 100000:
        raise HTTPException(status_code=400, detail="total_clicks must be 1..100000")
    if not payload.proxies:
        raise HTTPException(status_code=400, detail="At least one proxy is required")
    if not payload.user_agents:
        raise HTTPException(status_code=400, detail="At least one user agent is required")
    concurrency = max(1, min(int(payload.concurrency or 3), 20))

    # Validate link ownership
    link = await db.links.find_one({"id": payload.link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    # Build the target short link URL (public one, so proxies can reach it)
    # Priority: explicit payload.target_url > PUBLIC_BASE_URL env > incoming Request's public host > REACT_APP_BACKEND_URL
    short_url = None
    if payload.target_url and payload.target_url.strip():
        tu = payload.target_url.strip().rstrip("/")
        # Accept either a full URL ending in the shortcode, or a base URL
        if f"/t/{link['short_code']}" in tu or f"/r/{link['short_code']}" in tu:
            short_url = tu
        else:
            short_url = f"{tu}/t/{link['short_code']}"
    else:
        # Try env vars
        public_base = os.environ.get("PUBLIC_BASE_URL") or os.environ.get("REACT_APP_BACKEND_URL") or ""
        if public_base and public_base.startswith("http"):
            short_url = f"{public_base.rstrip('/')}/t/{link['short_code']}"
        else:
            # Fall back to the host the frontend called us on
            try:
                # Prefer X-Forwarded-* (ingress/proxy) over direct request.url
                fwd_proto = request.headers.get("x-forwarded-proto")
                fwd_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
                if fwd_host:
                    scheme = (fwd_proto or request.url.scheme or "https").split(",")[0].strip()
                    host = fwd_host.split(",")[0].strip()
                    short_url = f"{scheme}://{host}/t/{link['short_code']}"
            except Exception:
                short_url = None

    if not short_url or not short_url.startswith("http"):
        raise HTTPException(
            status_code=400,
            detail=(
                "Could not determine a PUBLIC URL to fire traffic at. "
                "Residential proxies cannot reach localhost/127.0.0.1. "
                "Fix by either: (a) pasting your public URL in the 'Target URL' field "
                "(e.g. https://yourdomain.com/t/insta), or "
                "(b) setting PUBLIC_BASE_URL in backend .env to your public host."
            ),
        )

    # Parse proxies (skip invalid lines)
    parsed_proxies: List[Dict[str, Any]] = []
    for line in payload.proxies:
        p = _parse_proxy_line(line)
        if p:
            parsed_proxies.append(p)
    if not parsed_proxies:
        raise HTTPException(status_code=400, detail="No valid proxies after parsing")

    # Clean UAs
    uas = [u.strip() for u in payload.user_agents if u and u.strip()]
    if not uas:
        raise HTTPException(status_code=400, detail="No valid user agents")

    allowed_countries_lc = set(
        (c or "").strip().lower() for c in (payload.allowed_countries or []) if (c or "").strip()
    )

    # Common country aliases so users can type "usa", "us", "america",
    # "united state" (missing s) and still match "United States", etc.
    COUNTRY_ALIASES = {
        "us": "united states", "usa": "united states", "u.s.": "united states",
        "u.s.a.": "united states", "america": "united states",
        "united state": "united states", "united states of america": "united states",
        "uk": "united kingdom", "u.k.": "united kingdom", "britain": "united kingdom",
        "great britain": "united kingdom", "england": "united kingdom",
        "uae": "united arab emirates",
    }

    def _country_allowed(country: Optional[str]) -> bool:
        if not allowed_countries_lc:
            return True
        if not country:
            return False
        got = country.strip().lower()
        # Try alias resolution on the detected country too
        got_alias = COUNTRY_ALIASES.get(got, got)
        for allowed in allowed_countries_lc:
            a = COUNTRY_ALIASES.get(allowed, allowed)
            # Exact, or contains (either direction) so "united state" ~ "united states"
            if a == got or a == got_alias:
                return True
            if a and (a in got or got in a):
                return True
        return False

    async def generate():
        import random
        # Emit the resolved target URL as the first event so the UI can display it
        yield json.dumps({"type": "info", "target_url": short_url}) + "\n"
        fired = 0
        succeeded = 0
        blocked_dup = 0
        blocked_vpn = 0
        blocked_geo = 0
        probe_failed = 0
        fire_failed = 0
        target_total = int(payload.total_clicks)

        sem = asyncio.Semaphore(concurrency)
        lock = asyncio.Lock()
        used_exit_ips: set = set()  # avoid firing through same exit IP twice in one run

        async def _one(idx: int, proxy: Dict[str, Any], ua: str):
            nonlocal fired, succeeded, blocked_dup, blocked_vpn, blocked_geo, probe_failed, fire_failed
            async with sem:
                result = {
                    "type": "result",
                    "index": idx,
                    "proxy": proxy["raw"][:80],
                    "ua": ua[:80],
                    "exit_ip": None,
                    "country": None,
                    "status": "pending",
                    "reason": None,
                    "http_status": None,
                    "error": None,
                }

                # Step 1: probe exit IP
                async with aiohttp.ClientSession() as session:
                    exit_ip = await _proxy_exit_ip(session, proxy, ua)
                    if not exit_ip:
                        result["status"] = "probe_failed"
                        result["reason"] = "Proxy did not respond to IP probe"
                        async with lock:
                            probe_failed += 1
                        return result
                    result["exit_ip"] = exit_ip

                    # Step 2: skip if we've already used this exit IP in this run
                    # (only if user asked to skip duplicates)
                    if payload.skip_duplicate:
                        async with lock:
                            if exit_ip in used_exit_ips:
                                result["status"] = "blocked_duplicate"
                                result["reason"] = "Exit IP already used in this run"
                                blocked_dup += 1
                                return result
                            used_exit_ips.add(exit_ip)

                    # Step 3: duplicate-in-DB check
                    if payload.skip_duplicate:
                        dup = await db.clicks.find_one({"ip_address": exit_ip}, {"_id": 0, "id": 1})
                        if dup:
                            result["status"] = "blocked_duplicate"
                            result["reason"] = "Exit IP already in clicks DB"
                            async with lock:
                                blocked_dup += 1
                            return result

                    # Step 4: geo lookup
                    country = None
                    try:
                        geo = await get_country_from_ip(exit_ip)
                        country = (geo or {}).get("country")
                        result["country"] = country
                    except Exception as e:
                        logger.debug(f"geo lookup failed for {exit_ip}: {e}")

                    if allowed_countries_lc:
                        if not _country_allowed(country):
                            result["status"] = "blocked_geo"
                            result["reason"] = f"Country '{country}' not in allowed list"
                            async with lock:
                                blocked_geo += 1
                            return result

                    # Step 5: VPN check
                    if payload.skip_vpn:
                        try:
                            vpn = await check_vpn_detailed(exit_ip)
                            if vpn.get("is_vpn"):
                                result["status"] = "blocked_vpn"
                                result["reason"] = f"Detected as VPN/datacenter ({vpn.get('source')})"
                                async with lock:
                                    blocked_vpn += 1
                                return result
                        except Exception as e:
                            logger.debug(f"vpn check failed for {exit_ip}: {e}")

                    # Step 6: fire the real click
                    fired_res = await _fire_real_click(session, proxy, ua, short_url, payload.follow_redirect)
                    result["http_status"] = fired_res["status"]
                    result["redirect_to"] = fired_res.get("redirect_to")
                    result["final_status"] = fired_res.get("final_status")
                    result["error"] = fired_res["error"]

                    if fired_res["error"]:
                        result["status"] = "fire_failed"
                        result["reason"] = fired_res["error"][:200]
                        async with lock:
                            fire_failed += 1
                        return result
                    # A short link returns 302 with Location header -> success
                    if fired_res["status"] in (301, 302, 303, 307, 308, 200):
                        result["status"] = "success"
                        async with lock:
                            fired += 1
                            succeeded += 1
                    else:
                        result["status"] = "fire_failed"
                        result["reason"] = f"Unexpected HTTP {fired_res['status']}"
                        async with lock:
                            fire_failed += 1
                    return result

        # Loop: keep firing until we hit target_total successes OR we exhaust retries.
        # If no_repeat_proxy is set, each proxy line is used at most once (attempts <= len(proxies)).
        attempt = 0
        if payload.no_repeat_proxy:
            max_attempts = len(parsed_proxies)
        else:
            max_attempts = max(target_total * 5, len(parsed_proxies) * 2)
        batch: List[asyncio.Task] = []

        # Pacing: if user wants N clicks spread over D minutes, sleep before scheduling each attempt
        pacing_delay = 0.0
        try:
            dur = float(payload.duration_minutes) if payload.duration_minutes else 0.0
        except Exception:
            dur = 0.0
        if dur and target_total > 0:
            pacing_delay = max(0.0, (dur * 60.0) / float(target_total))

        while succeeded < target_total and attempt < max_attempts:
            # Schedule `concurrency` tasks at a time
            while len(batch) < concurrency and succeeded + len(batch) < target_total and attempt < max_attempts:
                if pacing_delay > 0 and attempt > 0:
                    await asyncio.sleep(pacing_delay)
                proxy = parsed_proxies[attempt % len(parsed_proxies)]
                ua = uas[attempt % len(uas)] if len(uas) else random.choice(uas)
                batch.append(asyncio.create_task(_one(attempt, proxy, ua)))
                attempt += 1

            if not batch:
                break

            # Wait for the first task to complete, then yield its result
            done, pending = await asyncio.wait(batch, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                batch.remove(t)
                try:
                    res = await t
                except Exception as e:
                    res = {"type": "result", "status": "fire_failed", "error": str(e)}
                yield json.dumps(res) + "\n"
                # Progress
                yield json.dumps({
                    "type": "progress",
                    "attempted": attempt,
                    "succeeded": succeeded,
                    "target": target_total,
                    "blocked_dup": blocked_dup,
                    "blocked_vpn": blocked_vpn,
                    "blocked_geo": blocked_geo,
                    "probe_failed": probe_failed,
                    "fire_failed": fire_failed,
                }) + "\n"

        # Wait for any remaining in-flight tasks
        for t in batch:
            try:
                res = await t
            except Exception as e:
                res = {"type": "result", "status": "fire_failed", "error": str(e)}
            yield json.dumps(res) + "\n"

        yield json.dumps({
            "type": "complete",
            "attempted": attempt,
            "succeeded": succeeded,
            "target": target_total,
            "blocked_dup": blocked_dup,
            "blocked_vpn": blocked_vpn,
            "blocked_geo": blocked_geo,
            "probe_failed": probe_failed,
            "fire_failed": fire_failed,
        }) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")



@api_router.post("/links", response_model=LinkResponse)
async def create_link(link: LinkCreate, user: dict = Depends(get_current_user_with_fresh_data)):
    # Check feature access
    check_user_feature(user, "links")
    
    if link.custom_short_code:
        if not validate_short_code(link.custom_short_code):
            raise HTTPException(
                status_code=400, 
                detail="Invalid short code. Use 3-50 characters: letters, numbers, hyphens, underscores only"
            )
        
        existing = await db.links.find_one({"short_code": link.custom_short_code})
        if existing:
            raise HTTPException(status_code=400, detail=f"Short code '{link.custom_short_code}' is already taken")
        
        short_code = link.custom_short_code
    else:
        short_code = generate_short_code()
        while await db.links.find_one({"short_code": short_code}):
            short_code = generate_short_code()
    
    link_doc = {
        "id": str(uuid.uuid4()),
        "short_code": short_code,
        "offer_url": link.offer_url,
        "status": link.status,
        "name": link.name,
        "allowed_countries": link.allowed_countries or [],
        "allowed_os": link.allowed_os or [],
        "block_vpn": link.block_vpn,
        "duplicate_timer_enabled": link.duplicate_timer_enabled,
        "duplicate_timer_seconds": link.duplicate_timer_seconds,
        "forced_source": link.forced_source,
        "forced_source_name": link.forced_source_name,
        "referrer_mode": link.referrer_mode or "normal",
        "url_params": link.url_params,
        "simulate_platform": link.simulate_platform,
        "clicks": 0,
        "conversions": 0,
        "revenue": 0.0,
        "user_id": user["id"],
        "created_by": user.get("sub_user_id") if user.get("is_sub_user") else None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.links.insert_one(link_doc)
    return LinkResponse(**link_doc)

@api_router.get("/links", response_model=List[LinkResponse])
async def get_links(user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "links")
    
    # Sub-users only see what they created, main users see everything
    query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    
    links = await db.links.find(query, {"_id": 0}).to_list(100000)
    return [LinkResponse(**link) for link in links]

@api_router.get("/links/{link_id}", response_model=LinkResponse)
async def get_link(link_id: str, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "links")
    link = await db.links.find_one({"id": link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    return LinkResponse(**link)

@api_router.put("/links/{link_id}", response_model=LinkResponse)
async def update_link(link_id: str, link_update: LinkUpdate, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "links")
    link = await db.links.find_one({"id": link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    update_data = {}
    
    # Handle custom_short_code update
    if link_update.custom_short_code:
        new_short_code = link_update.custom_short_code.lower().strip()
        if not validate_short_code(new_short_code):
            raise HTTPException(status_code=400, detail="Invalid short code format. Use 3-50 characters: letters, numbers, hyphens, underscores")
        
        # Check if new short code already exists (but not for the same link)
        existing = await db.links.find_one({"short_code": new_short_code, "id": {"$ne": link_id}})
        if existing:
            raise HTTPException(status_code=400, detail=f"Short code '{new_short_code}' is already in use")
        
        update_data["short_code"] = new_short_code
    
    # Add other fields to update
    for k, v in link_update.model_dump().items():
        if v is not None and k not in ["custom_short_code"]:  # Skip custom_short_code as we handle it above
            update_data[k] = v
    
    if update_data:
        await db.links.update_one({"id": link_id}, {"$set": update_data})
        link.update(update_data)
    
    return LinkResponse(**link)

@api_router.delete("/links/{link_id}")
async def delete_link(link_id: str, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "links")
    result = await db.links.delete_one({"id": link_id, "user_id": user["id"]})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Link not found")
    return {"message": "Link deleted"}

@api_router.post("/clicks/import")
async def import_clicks(request: Request, user: dict = Depends(get_current_user_with_fresh_data)):
    """Import clicks from external source (JSON array)"""
    check_user_feature(user, "import_traffic")
    try:
        data = await request.json()
        clicks_data = data.get("clicks", [])
        
        if not clicks_data or not isinstance(clicks_data, list):
            raise HTTPException(status_code=400, detail="Invalid format. Expected 'clicks' array")
        
        user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1, "short_code": 1}).to_list(10000)
        link_map = {link["short_code"]: link["id"] for link in user_links}
        link_ids = [link["id"] for link in user_links]
        
        imported_clicks = []
        skipped = 0
        
        for click_data in clicks_data:
            try:
                link_id = click_data.get("link_id")
                short_code = click_data.get("short_code")
                
                if short_code and short_code in link_map:
                    link_id = link_map[short_code]
                elif not link_id or link_id not in link_ids:
                    skipped += 1
                    continue
                
                click_doc = {
                    "id": str(uuid.uuid4()),
                    "click_id": click_data.get("click_id", str(uuid.uuid4())),
                    "link_id": link_id,
                    "ip_address": click_data.get("ip_address", "Unknown"),
                    "country": click_data.get("country", "Unknown"),
                    "is_vpn": click_data.get("is_vpn", False),
                    "is_proxy": click_data.get("is_proxy", False),
                    "user_agent": click_data.get("user_agent", ""),
                    "referrer": click_data.get("referrer", ""),
                    "device": click_data.get("device", "desktop"),
                    "sub1": click_data.get("sub1"),
                    "sub2": click_data.get("sub2"),
                    "sub3": click_data.get("sub3"),
                    "created_at": click_data.get("created_at", datetime.now(timezone.utc).isoformat())
                }
                
                imported_clicks.append(click_doc)
            except Exception as e:
                skipped += 1
                continue
        
        if imported_clicks:
            # Insert in smaller batches to avoid timeout
            batch_size = 5000
            for i in range(0, len(imported_clicks), batch_size):
                batch = imported_clicks[i:i + batch_size]
                try:
                    await db.clicks.insert_many(batch, ordered=False)
                except Exception as batch_error:
                    logger.error(f"Error inserting click batch: {batch_error}")
            
            # Update link click counts
            for link_id in link_ids:
                link_clicks = [c for c in imported_clicks if c["link_id"] == link_id]
                if link_clicks:
                    try:
                        await db.links.update_one(
                            {"id": link_id},
                            {"$inc": {"clicks": len(link_clicks)}}
                        )
                    except Exception as update_error:
                        logger.error(f"Error updating link click count: {update_error}")
        
        return {
            "message": f"Successfully imported {len(imported_clicks)} clicks",
            "imported": len(imported_clicks),
            "skipped": skipped,
            "total": len(clicks_data)
        }
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing clicks: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")

@api_router.post("/clicks/bulk-delete")
async def bulk_delete_clicks(click_ids: List[str], user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "clicks")
    user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1}).to_list(100000)
    link_ids = [link["id"] for link in user_links]
    
    if not link_ids:
        return {"message": "No clicks found", "deleted_count": 0}
    
    result = await db.clicks.delete_many({
        "id": {"$in": click_ids},
        "link_id": {"$in": link_ids}
    })
    
    return {
        "message": f"Deleted {result.deleted_count} clicks",
        "deleted_count": result.deleted_count
    }

# ==================== VPN CHECK ENDPOINT ====================
@api_router.post("/vpn/check")
async def check_ip_vpn(data: dict, user: dict = Depends(get_current_user_with_fresh_data)):
    """Check if an IP is a VPN/Proxy using multiple services"""
    ip = data.get("ip", "").strip()
    if not ip:
        raise HTTPException(status_code=400, detail="IP address required")
    
    # Use the detailed VPN check with API tracking and fallback
    result = await check_vpn_detailed(ip)
    return {
        "ip": ip,
        "is_vpn": result.get("is_vpn", False),
        "vpn_score": result.get("vpn_score", 0),
        "risk": result.get("risk", "unknown"),
        "source": result.get("source", "none"),
        "threshold": 25,
        "message": "VPN Detected" if result.get("is_vpn") else "Clean IP"
    }

@api_router.post("/vpn/bulk-check")
async def bulk_check_vpn(data: dict, user: dict = Depends(get_current_user_with_fresh_data)):
    """Check multiple IPs for VPN status - OPTIMIZED with parallel processing"""
    ips = data.get("ips", [])
    if not ips:
        raise HTTPException(status_code=400, detail="IP list required")
    
    # Limit to 100 IPs per request
    ips_to_check = [ip.strip() for ip in ips[:100] if ip.strip()]
    
    # Run VPN checks in parallel (batches of 10) using check_vpn_detailed
    results = []
    batch_size = 10
    for i in range(0, len(ips_to_check), batch_size):
        batch = ips_to_check[i:i + batch_size]
        tasks = [check_vpn_detailed(ip) for ip in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for ip, result in zip(batch, batch_results):
            if isinstance(result, Exception):
                results.append({"ip": ip, "is_vpn": False, "vpn_score": 0, "source": "error"})
            else:
                results.append({
                    "ip": ip,
                    "is_vpn": result.get("is_vpn", False),
                    "vpn_score": result.get("vpn_score", 0),
                    "source": result.get("source", "none")
                })
    
    vpn_count = sum(1 for r in results if r["is_vpn"])
    return {
        "total": len(results),
        "vpn_count": vpn_count,
        "clean_count": len(results) - vpn_count,
        "results": results
    }

@api_router.delete("/clicks/delete-by-date")
async def delete_clicks_by_date(start_date: str, end_date: str, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "clicks")
    try:
        start_datetime = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        end_datetime = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        end_datetime = end_datetime.replace(hour=23, minute=59, second=59)
        
        user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1}).to_list(100000)
        link_ids = [link["id"] for link in user_links]
        
        if not link_ids:
            return {"message": "No links found", "deleted_count": 0}
        
        result = await db.clicks.delete_many({
            "link_id": {"$in": link_ids},
            "created_at": {
                "$gte": start_datetime.isoformat(),
                "$lte": end_datetime.isoformat()
            }
        })
        
        return {
            "message": f"Deleted {result.deleted_count} clicks from {start_date} to {end_date}",
            "deleted_count": result.deleted_count,
            "start_date": start_date,
            "end_date": end_date
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format or error: {str(e)}")

@api_router.delete("/clicks/delete-by-category")
async def delete_clicks_by_category(categories: str, user: dict = Depends(get_current_user_with_fresh_data)):
    """Delete clicks by category (vpn, proxy, duplicate)"""
    check_user_feature(user, "clicks")
    
    category_list = [c.strip().lower() for c in categories.split(',') if c.strip()]
    if not category_list:
        raise HTTPException(status_code=400, detail="No categories specified")
    
    # Get user's database
    user_db = get_db_for_user(user)
    
    # Get user's link IDs
    user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1}).to_list(100000)
    link_ids = [link["id"] for link in user_links]
    
    if not link_ids:
        return {"message": "No links found", "deleted_count": 0}
    
    # Build query based on categories
    or_conditions = []
    for category in category_list:
        if category == 'vpn':
            or_conditions.append({"is_vpn": True})
        elif category == 'proxy':
            or_conditions.append({"is_proxy": True})
        elif category == 'duplicate':
            # Match any duplicate flag - could be duplicate proxy, duplicate click, or general duplicate
            or_conditions.append({"$or": [
                {"is_duplicate": True},
                {"is_duplicate_proxy": True},
                {"is_duplicate_click": True}
            ]})
    
    if not or_conditions:
        raise HTTPException(status_code=400, detail="Invalid categories. Use: vpn, proxy, duplicate")
    
    query = {
        "link_id": {"$in": link_ids},
        "$or": or_conditions
    }
    
    # Delete from user's database
    result_user_db = await user_db.clicks.delete_many(query)
    
    # Also delete from main database (legacy data)
    result_main_db = await db.clicks.delete_many(query)
    
    total_deleted = result_user_db.deleted_count + result_main_db.deleted_count
    
    return {
        "message": f"Deleted {total_deleted} clicks matching categories: {', '.join(category_list)}",
        "deleted_count": total_deleted,
        "categories": category_list
    }

@api_router.get("/clicks", response_model=List[ClickResponse])
async def get_clicks(
    user: dict = Depends(get_current_user_with_fresh_data), 
    limit: int = 100,  # Default limit for faster loading
    skip: int = 0,
    start_date: str = None,
    end_date: str = None,
    filter_type: str = "all",
    link_id: str = None
):
    check_user_feature(user, "clicks")
    
    # If limit is 0 or not specified, return ALL clicks (no limit)
    # Otherwise cap at 10000 for performance
    if limit <= 0:
        limit = 100000  # Return all clicks
    else:
        limit = min(limit, 10000)
    
    # Get the correct database for this user
    user_db = get_db_for_user(user)
    
    # Sub-users only see clicks from their own links, main users see all
    link_query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        link_query["created_by"] = user.get("sub_user_id")
    
    user_links = await db.links.find(link_query, {"_id": 0, "id": 1}).to_list(1000000)
    link_ids = [link["id"] for link in user_links]
    
    # If specific link requested, filter by that link only
    if link_id and link_id in link_ids:
        query = {"link_id": link_id}
    else:
        query = {"link_id": {"$in": link_ids}}
    
    # Date filtering
    if start_date:
        try:
            start_dt = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
            query["created_at"] = {"$gte": start_dt.isoformat()}
        except:
            pass
    
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
            end_dt = end_dt.replace(hour=23, minute=59, second=59)
            if "created_at" in query:
                query["created_at"]["$lte"] = end_dt.isoformat()
            else:
                query["created_at"] = {"$lte": end_dt.isoformat()}
        except:
            pass
    
    # Filter by time period (only if start_date/end_date not provided)
    if not start_date and not end_date:
        if filter_type == "today":
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            query["created_at"] = {"$gte": today.isoformat()}
        elif filter_type == "yesterday":
            today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday = today - timedelta(days=1)
            query["created_at"] = {"$gte": yesterday.isoformat(), "$lt": today.isoformat()}
        elif filter_type == "week":
            week_ago = datetime.now(timezone.utc) - timedelta(days=7)
            query["created_at"] = {"$gte": week_ago.isoformat()}
        elif filter_type == "month":
            month_ago = datetime.now(timezone.utc) - timedelta(days=30)
            query["created_at"] = {"$gte": month_ago.isoformat()}
    
    # Query from user's database first, then also from main db for legacy data
    cursor = user_db.clicks.find(query, {"_id": 0}).sort("created_at", -1)
    if skip > 0:
        cursor = cursor.skip(skip)
    if limit > 0:
        cursor = cursor.limit(limit)
    
    clicks = await cursor.to_list(None)
    
    # Also get legacy clicks from main db
    legacy_cursor = db.clicks.find(query, {"_id": 0}).sort("created_at", -1)
    if skip > 0:
        legacy_cursor = legacy_cursor.skip(skip)
    if limit > 0:
        legacy_cursor = legacy_cursor.limit(limit)
    legacy_clicks = await legacy_cursor.to_list(None)
    
    # Combine and deduplicate by click_id
    all_clicks = clicks + legacy_clicks
    seen_ids = set()
    unique_clicks = []
    for click in all_clicks:
        click_id = click.get("id") or click.get("click_id")
        if click_id not in seen_ids:
            seen_ids.add(click_id)
            unique_clicks.append(click)
    
    # Sort by created_at descending
    unique_clicks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    return [ClickResponse(**click) for click in unique_clicks]

@api_router.get("/clicks/count")
async def get_clicks_count(
    user: dict = Depends(get_current_user_with_fresh_data),
    filter_type: str = "all",
    link_id: str = None
):
    """Get total click count for pagination"""
    check_user_feature(user, "clicks")
    
    # Get user's database
    user_db = get_db_for_user(user)
    
    user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1}).to_list(100000)
    link_ids = [link["id"] for link in user_links]
    
    if link_id and link_id in link_ids:
        query = {"link_id": link_id}
    else:
        query = {"link_id": {"$in": link_ids}}
    
    # Filter by time period
    if filter_type == "today":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query["created_at"] = {"$gte": today.isoformat()}
    elif filter_type == "yesterday":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        query["created_at"] = {"$gte": yesterday.isoformat(), "$lt": today.isoformat()}
    elif filter_type == "week":
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query["created_at"] = {"$gte": week_ago.isoformat()}
    elif filter_type == "month":
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        query["created_at"] = {"$gte": month_ago.isoformat()}
    
    # Count from BOTH user_db and main db
    user_db_count = await user_db.clicks.count_documents(query)
    main_db_count = await db.clicks.count_documents(query)
    total_count = user_db_count + main_db_count
    
    # Get unique IPs count
    user_db_ips = await user_db.clicks.distinct("ip_address", query)
    main_db_ips = await db.clicks.distinct("ip_address", query)
    unique_ips = set(user_db_ips + main_db_ips)
    unique_count = len(unique_ips)
    
    # Count duplicates and VPN
    duplicate_count = await user_db.clicks.count_documents({**query, "is_duplicate_proxy": True}) + \
                     await db.clicks.count_documents({**query, "is_duplicate_proxy": True})
    vpn_count = await user_db.clicks.count_documents({**query, "is_vpn": True}) + \
               await db.clicks.count_documents({**query, "is_vpn": True})
    
    return {
        "count": total_count,
        "unique": unique_count,
        "duplicate": duplicate_count,
        "vpn": vpn_count
    }

@api_router.get("/clicks/export")
async def export_clicks(
    user: dict = Depends(get_current_user_with_fresh_data),
    filter_type: str = "all",
    link_id: str = None
):
    """Export ALL clicks for CSV download"""
    check_user_feature(user, "clicks")
    
    user_db = get_db_for_user(user)
    
    # Get user's link IDs
    link_query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        link_query["created_by"] = user.get("sub_user_id")
    
    user_links = await db.links.find(link_query, {"_id": 0, "id": 1, "name": 1, "short_code": 1}).to_list(1000000)
    link_ids = [link["id"] for link in user_links]
    link_names = {link["id"]: link.get("name") or link.get("short_code", "Unknown") for link in user_links}
    
    # Build query
    if link_id and link_id in link_ids:
        query = {"link_id": link_id}
    else:
        query = {"link_id": {"$in": link_ids}}
    
    # Apply date filter
    if filter_type == "today":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query["created_at"] = {"$gte": today.isoformat()}
    elif filter_type == "yesterday":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        query["created_at"] = {"$gte": yesterday.isoformat(), "$lt": today.isoformat()}
    elif filter_type == "week":
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query["created_at"] = {"$gte": week_ago.isoformat()}
    elif filter_type == "month":
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        query["created_at"] = {"$gte": month_ago.isoformat()}
    
    # Get ALL clicks from both databases
    clicks_user_db = await user_db.clicks.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000000)
    clicks_main_db = await db.clicks.find(query, {"_id": 0}).sort("created_at", -1).to_list(1000000)
    
    # Combine and sort
    all_clicks = clicks_user_db + clicks_main_db
    all_clicks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    
    # Format for export
    export_data = []
    for click in all_clicks:
        export_data.append({
            "ipv4": click.get("ipv4") or click.get("ip_address", ""),
            "ipv6": click.get("ipv6", ""),
            "proxy_ips": "; ".join(click.get("proxy_ips", [])) if click.get("proxy_ips") else "",
            "country": click.get("country", ""),
            "city": click.get("city", ""),
            "region": click.get("region", ""),
            "device": click.get("device_type") or click.get("device", ""),
            "browser": click.get("browser", ""),
            "os": click.get("os_name", ""),
            "is_vpn": "Yes" if click.get("is_vpn") else "No",
            "is_duplicate": "Yes" if click.get("is_duplicate_proxy") else "No",
            "link_name": link_names.get(click.get("link_id"), "Unknown"),
            "created_at": click.get("created_at", "")
        })
    
    return {"clicks": export_data, "total": len(export_data)}

# ==================== REFERRER STATS ====================

@api_router.get("/clicks/referrer-stats")
async def get_referrer_stats(
    user: dict = Depends(get_current_user_with_fresh_data),
    link_id: str = None,
    filter_type: str = "all"
):
    """Get referrer/traffic source statistics"""
    check_user_feature(user, "clicks")
    
    user_db = get_db_for_user(user)
    
    # Get user's link IDs
    link_query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        link_query["created_by"] = user.get("sub_user_id")
    
    user_links = await db.links.find(link_query, {"_id": 0, "id": 1}).to_list(1000000)
    link_ids = [link["id"] for link in user_links]
    
    if not link_ids:
        return {"referrers": [], "total": 0}
    
    # Build query
    if link_id and link_id in link_ids:
        query = {"link_id": link_id}
    else:
        query = {"link_id": {"$in": link_ids}}
    
    # Apply date filter
    if filter_type == "today":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        query["created_at"] = {"$gte": today.isoformat()}
    elif filter_type == "yesterday":
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)
        query["created_at"] = {"$gte": yesterday.isoformat(), "$lt": today.isoformat()}
    elif filter_type == "week":
        week_ago = datetime.now(timezone.utc) - timedelta(days=7)
        query["created_at"] = {"$gte": week_ago.isoformat()}
    elif filter_type == "month":
        month_ago = datetime.now(timezone.utc) - timedelta(days=30)
        query["created_at"] = {"$gte": month_ago.isoformat()}
    
    # Aggregate referrer stats from user's database
    pipeline = [
        {"$match": query},
        {"$group": {
            "_id": {
                "source": {"$ifNull": ["$referrer_source", "unknown"]},
                "source_name": {"$ifNull": ["$referrer_source_name", "Unknown"]}
            },
            "count": {"$sum": 1},
            "domains": {"$addToSet": "$referrer_domain"}
        }},
        {"$sort": {"count": -1}}
    ]
    
    results = await user_db.clicks.aggregate(pipeline).to_list(100)
    
    # Also check main database for legacy data
    results_main = await db.clicks.aggregate(pipeline).to_list(100)
    
    # Merge results
    merged = {}
    for r in results + results_main:
        source = r["_id"]["source"]
        if source in merged:
            merged[source]["count"] += r["count"]
            merged[source]["domains"] = list(set(merged[source]["domains"] + r["domains"]))
        else:
            merged[source] = {
                "source": source,
                "source_name": r["_id"]["source_name"],
                "count": r["count"],
                "domains": r["domains"]
            }
    
    # Convert to list and sort
    referrer_list = list(merged.values())
    referrer_list.sort(key=lambda x: x["count"], reverse=True)
    
    # Calculate percentages
    total = sum(r["count"] for r in referrer_list)
    for r in referrer_list:
        r["percentage"] = round((r["count"] / total) * 100, 1) if total > 0 else 0
        r["domains"] = [d for d in r["domains"] if d][:10]  # Limit domains and remove None
    
    # Handle unknown/direct - parse old clicks that don't have referrer_source
    if "unknown" in merged or not referrer_list:
        # Re-categorize clicks without referrer_source
        old_clicks = await user_db.clicks.find(
            {**query, "referrer_source": {"$exists": False}},
            {"_id": 0, "referrer": 1}
        ).to_list(10000)
        
        if old_clicks:
            old_stats = {}
            for click in old_clicks:
                ref_info = categorize_referrer(click.get("referrer", ""))
                source = ref_info["source"]
                if source not in old_stats:
                    old_stats[source] = {"count": 0, "source_name": ref_info["source_name"]}
                old_stats[source]["count"] += 1
            
            # Merge old stats
            for source, data in old_stats.items():
                found = False
                for r in referrer_list:
                    if r["source"] == source:
                        r["count"] += data["count"]
                        found = True
                        break
                if not found:
                    referrer_list.append({
                        "source": source,
                        "source_name": data["source_name"],
                        "count": data["count"],
                        "domains": [],
                        "percentage": 0
                    })
            
            # Remove unknown entry if we categorized it
            referrer_list = [r for r in referrer_list if r["source"] != "unknown"]
            
            # Recalculate percentages
            total = sum(r["count"] for r in referrer_list)
            for r in referrer_list:
                r["percentage"] = round((r["count"] / total) * 100, 1) if total > 0 else 0
            
            referrer_list.sort(key=lambda x: x["count"], reverse=True)
    
    return {
        "referrers": referrer_list,
        "total": total,
        "filter_type": filter_type
    }

@api_router.get("/clicks/referrer-breakdown")
async def get_referrer_breakdown(
    user: dict = Depends(get_current_user_with_fresh_data),
    source: str = "all",
    link_id: str = None,
    limit: int = 50
):
    """Get detailed breakdown for a specific referrer source"""
    check_user_feature(user, "clicks")
    
    user_db = get_db_for_user(user)
    
    # Get user's link IDs
    link_query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        link_query["created_by"] = user.get("sub_user_id")
    
    user_links = await db.links.find(link_query, {"_id": 0, "id": 1, "name": 1, "short_code": 1}).to_list(1000000)
    link_ids = [link["id"] for link in user_links]
    link_names = {link["id"]: link.get("name") or link.get("short_code", "Unknown") for link in user_links}
    
    if not link_ids:
        return {"clicks": [], "total": 0}
    
    # Build query
    if link_id and link_id in link_ids:
        query = {"link_id": link_id}
    else:
        query = {"link_id": {"$in": link_ids}}
    
    # Filter by source
    if source != "all":
        query["referrer_source"] = source
    
    clicks = await user_db.clicks.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    
    # Add link names
    for click in clicks:
        click["link_name"] = link_names.get(click.get("link_id"), "Unknown")
    
    return {
        "clicks": clicks,
        "total": len(clicks),
        "source": source
    }

@api_router.get("/conversions", response_model=List[ConversionResponse])
async def get_conversions(user: dict = Depends(get_current_user), limit: int = 100):
    user_links = await db.links.find({"user_id": user["id"]}, {"_id": 0, "id": 1}).to_list(100000)
    link_ids = [link["id"] for link in user_links]
    
    conversions = await db.conversions.find({"link_id": {"$in": link_ids}}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return [ConversionResponse(**conv) for conv in conversions]

async def find_click_across_dbs(clickid: str):
    """Find a click by click_id across the main DB and all per-user DBs.
    Returns (click_doc, source_db) or (None, None) if not found.
    Clicks are normally written to user-specific DBs (trackmaster_user_*) by the
    redirect handler, so a simple lookup on main_db is not sufficient.
    """
    # 1. Legacy/main DB first (fast path)
    click = await db.clicks.find_one({"click_id": clickid}, {"_id": 0})
    if click:
        return click, db
    # 2. Scan per-user databases
    try:
        all_db_names = await client.list_database_names()
        for name in all_db_names:
            if not name.startswith("trackmaster_user_"):
                continue
            user_db_instance = client[name]
            click = await user_db_instance.clicks.find_one({"click_id": clickid}, {"_id": 0})
            if click:
                return click, user_db_instance
    except Exception as e:
        logger.warning(f"Error scanning user DBs for click {clickid}: {e}")
    return None, None

@api_router.get("/postback")
async def postback(clickid: str, payout: float, status: str = "approved", token: str = ""):
    if token != POSTBACK_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
    
    click, _ = await find_click_across_dbs(clickid)
    if not click:
        raise HTTPException(status_code=404, detail="Click not found")
    
    existing = await db.conversions.find_one({"click_id": clickid})
    if existing:
        raise HTTPException(status_code=400, detail="Conversion already recorded")
    
    conversion_doc = {
        "id": str(uuid.uuid4()),
        "click_id": clickid,
        "link_id": click["link_id"],
        "payout": payout,
        "status": status,
        "ip_address": click.get("ip_address", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.conversions.insert_one(conversion_doc)
    await db.links.update_one({"id": click["link_id"]}, {"$inc": {"conversions": 1, "revenue": payout}})
    
    return {"message": "Conversion recorded", "conversion_id": conversion_doc["id"]}

@api_router.get("/pixel")
async def pixel_tracking(clickid: str, payout: float):
    click, _ = await find_click_across_dbs(clickid)
    if not click:
        return Response(content="", media_type="image/gif")
    
    existing = await db.conversions.find_one({"click_id": clickid})
    if existing:
        return Response(content="", media_type="image/gif")
    
    conversion_doc = {
        "id": str(uuid.uuid4()),
        "click_id": clickid,
        "link_id": click["link_id"],
        "payout": payout,
        "status": "approved",
        "ip_address": click.get("ip_address", "unknown"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.conversions.insert_one(conversion_doc)
    await db.links.update_one({"id": click["link_id"]}, {"$inc": {"conversions": 1, "revenue": payout}})
    
    pixel = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\x00\x00\x00!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
    return Response(content=pixel, media_type="image/gif")

@api_router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(user: dict = Depends(get_current_user)):
    # Get user's database for clicks
    user_db = get_db_for_user(user)
    
    # Sub-users only see stats from their own links, main users see all
    link_query = {"user_id": user["id"]}
    if user.get("is_sub_user"):
        link_query["created_by"] = user.get("sub_user_id")
    
    user_links = await db.links.find(link_query, {"_id": 0, "id": 1}).to_list(100000)
    link_ids = [link["id"] for link in user_links]
    
    # Count clicks from BOTH user_db and main db (legacy data)
    user_db_clicks = await user_db.clicks.count_documents({"link_id": {"$in": link_ids}})
    main_db_clicks = await db.clicks.count_documents({"link_id": {"$in": link_ids}})
    total_clicks = user_db_clicks + main_db_clicks
    
    # Get unique IPs from both databases
    user_db_ips = await user_db.clicks.distinct("ip_address", {"link_id": {"$in": link_ids}})
    main_db_ips = await db.clicks.distinct("ip_address", {"link_id": {"$in": link_ids}})
    unique_ips = set(user_db_ips + main_db_ips)
    unique_clicks = len(unique_ips)
    
    total_conversions = await db.conversions.count_documents({"link_id": {"$in": link_ids}})
    
    conversions = await db.conversions.find({"link_id": {"$in": link_ids}}, {"_id": 0}).to_list(100000)
    revenue = sum(conv["payout"] for conv in conversions)
    
    conversion_rate = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0
    epc = revenue / total_clicks if total_clicks > 0 else 0
    
    # Aggregate clicks by country from user_db
    clicks_by_country = await user_db.clicks.aggregate([
        {"$match": {"link_id": {"$in": link_ids}}},
        {"$group": {"_id": "$country", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10}
    ]).to_list(10)
    
    # Aggregate clicks by device from user_db
    clicks_by_device = await user_db.clicks.aggregate([
        {"$match": {"link_id": {"$in": link_ids}}},
        {"$group": {"_id": "$device", "count": {"$sum": 1}}}
    ]).to_list(10)
    
    # Aggregate clicks by date from user_db
    clicks_by_date = await user_db.clicks.aggregate([
        {"$match": {"link_id": {"$in": link_ids}}},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 30}
    ]).to_list(30)
    
    revenue_by_date = await db.conversions.aggregate([
        {"$match": {"link_id": {"$in": link_ids}}},
        {"$group": {
            "_id": {"$substr": ["$created_at", 0, 10]},
            "revenue": {"$sum": "$payout"}
        }},
        {"$sort": {"_id": 1}},
        {"$limit": 30}
    ]).to_list(30)
    
    return DashboardStats(
        total_clicks=total_clicks,
        unique_clicks=unique_clicks,
        total_conversions=total_conversions,
        conversion_rate=round(conversion_rate, 2),
        revenue=round(revenue, 2),
        epc=round(epc, 4),
        clicks_by_country=[{"country": item["_id"], "count": item["count"]} for item in clicks_by_country],
        clicks_by_device=[{"device": item["_id"], "count": item["count"]} for item in clicks_by_device],
        clicks_by_date=[{"date": item["_id"], "count": item["count"]} for item in clicks_by_date],
        revenue_by_date=[{"date": item["_id"], "revenue": round(item["revenue"], 2)} for item in revenue_by_date]
    )

def extract_ip_from_proxy(proxy_string: str) -> str:
    """Extract IP address from proxy string"""
    proxy_string = proxy_string.strip()
    
    if "@" in proxy_string:
        parts = proxy_string.split("@")
        host_port = parts[-1]
    else:
        host_port = proxy_string
    
    if ":" in host_port:
        ip = host_port.split(":")[0]
        return ip.strip()
    
    return host_port.strip()

@api_router.post("/proxies/upload", response_model=List[ProxyResponse])
async def upload_proxies(proxy_upload: ProxyUpload, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "proxies")
    proxy_docs = []
    
    # Get the main user_id (for sub-users, use parent_user_id)
    main_user_id = user["id"]
    
    # Get user's database
    user_db = get_db_for_user(user)
    
    # Check existing proxies from both user_db and main_db (for duplicate proxy string check only)
    proxy_query = {"user_id": main_user_id}
    if user.get("is_sub_user"):
        proxy_query["created_by"] = user.get("sub_user_id")
    
    # Get proxies from user_db
    existing_proxies_user_db = await user_db.proxies.find(proxy_query, {"_id": 0, "proxy_string": 1}).to_list(100000)
    # Get proxies from main_db (legacy)
    existing_proxies_main_db = await db.proxies.find(proxy_query, {"_id": 0, "proxy_string": 1}).to_list(100000)
    
    existing_proxy_strings = set()
    for p in existing_proxies_user_db + existing_proxies_main_db:
        existing_proxy_strings.add(p["proxy_string"])
    
    # NOTE: We skip the slow database IP check during upload for performance
    # Duplicate IP check against clicks will happen during proxy TESTING (one by one)
    # This prevents timeout when uploading many proxies
    
    # However, we do a quick check against the cached IPs for immediate feedback
    all_click_ips = await get_all_click_ips_from_entire_database()
    
    for proxy_string in proxy_upload.proxy_list:
        cleaned_proxy = proxy_string.strip()
        if not cleaned_proxy:
            continue
            
        is_duplicate_proxy = cleaned_proxy in existing_proxy_strings
        
        proxy_ip = extract_ip_from_proxy(cleaned_proxy)
        
        # Check if this proxy's IP is already in clicks database (duplicate click check)
        is_duplicate_click = proxy_ip in all_click_ips if proxy_ip else False
        
        # Skip VPN check during upload for speed - will be checked during testing
        # Only do quick local IP check
        is_private_ip = proxy_ip and proxy_ip.startswith(("10.", "172.", "192.168.", "127."))
        
        proxy_doc = {
            "id": str(uuid.uuid4()),
            "proxy_string": cleaned_proxy,
            "proxy_ip": proxy_ip,
            "proxy_type": proxy_upload.proxy_type,
            "status": "pending",
            "response_time": None,
            "detected_ip": None,
            "all_detected_ips": None,
            "is_duplicate": is_duplicate_proxy or is_duplicate_click,  # Combined duplicate status
            "is_duplicate_proxy": is_duplicate_proxy,
            "is_duplicate_click": is_duplicate_click,  # IP found in clicks database
            "duplicate_matched_ip": proxy_ip if is_duplicate_click else None,
            "is_vpn": False,  # Will be checked during testing
            "vpn_score": None,
            "user_id": main_user_id,
            "created_by": user.get("sub_user_id") if user.get("is_sub_user") else None,
            "last_checked": datetime.now(timezone.utc).isoformat()
        }
        proxy_docs.append(proxy_doc)
        
        if not is_duplicate_proxy:
            existing_proxy_strings.add(cleaned_proxy)
    
    if proxy_docs:
        # Save to user's database
        await user_db.proxies.insert_many(proxy_docs)
    
    logger.info(f"Uploaded {len(proxy_docs)} proxies for user {main_user_id} (duplicate/VPN check will happen during testing)")
    
    return [ProxyResponse(**proxy) for proxy in proxy_docs]

@api_router.get("/proxies", response_model=List[ProxyResponse])
async def get_proxies(user: dict = Depends(get_current_user_with_fresh_data), filter: str = "all"):
    check_user_feature(user, "proxies")
    user_db = get_db_for_user(user)
    query = {"user_id": user["id"]}
    
    # Complete isolation: each user only sees their OWN proxies
    # Sub-users see only proxies they created (created_by = sub_user_id)
    # Main users see only proxies they created (created_by = null/None)
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    else:
        # Main user only sees their own proxies, not sub-users' proxies
        query["created_by"] = None
    
    if filter == "unique":
        query["is_duplicate"] = False
    elif filter == "duplicate":
        query["is_duplicate"] = True
    elif filter == "alive":
        query["status"] = "alive"
    elif filter == "dead":
        query["status"] = "dead"
    elif filter == "pending":
        query["status"] = "pending"
    elif filter == "vpn":
        query["is_vpn"] = True
    elif filter == "clean":
        query["is_vpn"] = {"$ne": True}
        query["status"] = "alive"
    
    # Get proxies from both user_db and main_db (for legacy data)
    proxies_user_db = await user_db.proxies.find(query, {"_id": 0}).to_list(100000)
    proxies_main_db = await db.proxies.find(query, {"_id": 0}).to_list(100000)
    
    # Combine and dedupe by proxy id
    all_proxies = {p["id"]: p for p in proxies_main_db}
    for p in proxies_user_db:
        all_proxies[p["id"]] = p  # User_db takes precedence
    
    return [ProxyResponse(**proxy) for proxy in all_proxies.values()]

# Helper function for fast proxy testing
async def _test_proxy_fast(proxy_string: str, proxy_type: str, timeout: float = 3) -> dict:
    """Ultra-fast proxy test - optimized for speed"""
    detected_ip = None
    detected_ips = []
    response_time = None
    status = "dead"
    error_msg = None
    
    try:
        if "@" in proxy_string:
            proxy_url = f"http://{proxy_string}" if proxy_type == "http" else f"socks5://{proxy_string}"
        else:
            parts = proxy_string.split(":")
            if len(parts) == 4:
                host, port, username, password = parts
                proxy_url = f"http://{username}:{password}@{host}:{port}" if proxy_type == "http" else f"socks5://{username}:{password}@{host}:{port}"
            elif len(parts) == 2:
                proxy_url = f"http://{proxy_string}" if proxy_type == "http" else f"socks5://{proxy_string}"
            else:
                return {"status": "dead", "error": "Invalid format", "detected_ip": None, "all_detected_ips": [], "response_time": None}
        
        # Use fastest IP check service first (ipify is very fast)
        ip_check_urls = [
            "http://api.ipify.org?format=json",
            "http://ip-api.com/json/?fields=query"
        ]
        
        start_time = time.time()
        for url in ip_check_urls:
            try:
                async with httpx.AsyncClient(
                    proxy=httpx.Proxy(url=proxy_url), 
                    timeout=timeout, 
                    follow_redirects=True
                ) as client:
                    response = await client.get(url)
                    response_time = time.time() - start_time
                    
                    if response.status_code == 200:
                        data = response.json()
                        origin = data.get("origin") or data.get("ip") or data.get("query") or ""
                        if origin:
                            detected_ips = [ip.strip() for ip in str(origin).split(",") if ip.strip()]
                            detected_ip = detected_ips[-1] if detected_ips else None
                        status = "alive"
                        break
            except:
                continue
    except Exception as e:
        error_msg = str(e)[:100]
    
    return {
        "status": status,
        "detected_ip": detected_ip,
        "all_detected_ips": detected_ips,
        "response_time": round(response_time, 3) if response_time else None,
        "error": error_msg
    }

async def _test_proxy_with_proxycheck(proxy_string: str, proxy_type: str, timeout: float = 5) -> dict:
    """Test proxy using proxycheck.io for IP detection, VPN check, and geo"""
    detected_ip = None
    detected_ips = []
    response_time = None
    status = "dead"
    error_msg = None
    is_vpn = False
    country = None
    city = None
    region = None
    isp = None
    
    try:
        # Build proxy URL
        if "@" in proxy_string:
            proxy_url = f"http://{proxy_string}" if proxy_type == "http" else f"socks5://{proxy_string}"
        else:
            parts = proxy_string.split(":")
            if len(parts) == 4:
                host, port, username, password = parts
                proxy_url = f"http://{username}:{password}@{host}:{port}" if proxy_type == "http" else f"socks5://{username}:{password}@{host}:{port}"
            elif len(parts) == 2:
                proxy_url = f"http://{proxy_string}" if proxy_type == "http" else f"socks5://{proxy_string}"
            else:
                return {
                    "status": "dead", "error": "Invalid format", "detected_ip": None,
                    "all_detected_ips": [], "response_time": None, "is_vpn": False,
                    "country": None, "city": None, "region": None, "isp": None
                }
        
        start_time = time.time()
        
        # Step 1: Get IP using ipify through proxy
        async with httpx.AsyncClient(
            proxy=httpx.Proxy(url=proxy_url), 
            timeout=timeout, 
            follow_redirects=True
        ) as client:
            ip_response = await client.get("http://api.ipify.org?format=json")
            response_time = time.time() - start_time
            
            if ip_response.status_code == 200:
                ip_data = ip_response.json()
                detected_ip = ip_data.get("ip", "").strip()
                
                # Only IPv4
                if detected_ip and ":" not in detected_ip:
                    detected_ips.append(detected_ip)
                    status = "alive"
                    
                    # Step 2: Use proxycheck.io for VPN and Geo (direct call)
                    try:
                        async with httpx.AsyncClient(timeout=5) as direct_client:
                            pc_url = f"https://proxycheck.io/v2/{detected_ip}?vpn=1&asn=1"
                            pc_response = await direct_client.get(pc_url)
                            
                            if pc_response.status_code == 200:
                                pc_data = pc_response.json()
                                ip_info = pc_data.get(detected_ip, {})
                                
                                # VPN Check
                                proxy_status = ip_info.get("proxy", "no")
                                ip_type = ip_info.get("type", "")
                                is_vpn = proxy_status == "yes" or ip_type in ["VPN", "Proxy", "Hosting", "TOR"]
                                
                                # Geo Info
                                country = ip_info.get("country")
                                city = ip_info.get("city")
                                region = ip_info.get("region")
                                isp = ip_info.get("provider") or ip_info.get("organisation")
                                
                                logger.info(f"Proxycheck.io result for {detected_ip}: VPN={is_vpn}, Country={country}")
                    except Exception as e:
                        logger.error(f"Proxycheck.io error for {detected_ip}: {e}")
                else:
                    status = "dead"
                    error_msg = "No IPv4 detected (IPv6 not supported)"
    except Exception as e:
        error_msg = str(e)[:100]
    
    return {
        "status": status,
        "detected_ip": detected_ip,
        "all_detected_ips": detected_ips,
        "response_time": round(response_time, 3) if response_time else None,
        "error": error_msg,
        "is_vpn": is_vpn,
        "country": country,
        "city": city,
        "region": region,
        "isp": isp
    }

@api_router.post("/proxies/bulk-test")
async def bulk_test_proxies(
    data: dict,
    user: dict = Depends(get_current_user_with_fresh_data)
):
    """Ultra-fast bulk proxy testing with optimized duplicate check"""
    check_user_feature(user, "proxies")
    
    proxy_ids = data.get("proxy_ids", [])
    skip_vpn_check = data.get("skip_vpn_check", True)  # Default TRUE for faster testing
    batch_size = min(data.get("batch_size", 50), 100)  # Reduced for stability
    timeout = data.get("timeout", 3)
    
    if not proxy_ids:
        raise HTTPException(status_code=400, detail="No proxy IDs provided")
    
    user_db = get_db_for_user(user)
    main_user_id = user["id"]
    
    # Get all proxies to test
    query = {"id": {"$in": proxy_ids}, "user_id": main_user_id}
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    else:
        query["created_by"] = None
    
    proxies_user_db = await user_db.proxies.find(query, {"_id": 0}).to_list(1000000)
    proxies_main_db = await db.proxies.find(query, {"_id": 0}).to_list(1000000)
    
    all_proxies = {p["id"]: ("user_db", p) for p in proxies_user_db}
    for p in proxies_main_db:
        if p["id"] not in all_proxies:
            all_proxies[p["id"]] = ("main_db", p)
    
    if not all_proxies:
        return {"message": "No proxies found", "tested": 0, "alive": 0, "dead": 0, "duplicate": 0, "vpn": 0}
    
    results = {"tested": 0, "alive": 0, "dead": 0, "duplicate": 0, "vpn": 0, "errors": 0}
    proxy_items = list(all_proxies.items())
    
    # Process in parallel batches
    for i in range(0, len(proxy_items), batch_size):
        batch = proxy_items[i:i + batch_size]
        
        async def test_single(proxy_id, db_source, proxy):
            try:
                result = await _test_proxy_fast(proxy["proxy_string"], proxy["proxy_type"], timeout)
                
                # Check duplicate using SHARED FUNCTION (same as link redirect)
                is_duplicate_click = False
                detected_ips = result.get("all_detected_ips") or []
                detected_ip = result.get("detected_ip")
                duplicate_matched_ip = None
                
                # Check all detected IPs
                ips_to_check = set()
                if detected_ip:
                    ips_to_check.add(detected_ip)
                for dip in detected_ips:
                    if dip:
                        ips_to_check.add(dip)
                
                for ip in ips_to_check:
                    is_dup, found_db = await is_ip_duplicate_in_any_database(ip, user_db)
                    if is_dup:
                        is_duplicate_click = True
                        duplicate_matched_ip = ip
                        break
                
                # Skip VPN check for speed
                is_vpn = False
                vpn_score = 0
                
                # Separate IPv4 and IPv6
                detected_ipv4 = None
                detected_ipv6 = None
                for ip in (detected_ips + [detected_ip] if detected_ip else detected_ips):
                    if ip:
                        if ":" in ip:
                            detected_ipv6 = ip
                        else:
                            detected_ipv4 = ip
                
                update_data = {
                    "status": result["status"],
                    "detected_ip": detected_ip,
                    "detected_ipv4": detected_ipv4,
                    "detected_ipv6": detected_ipv6,
                    "all_detected_ips": list(ips_to_check),
                    "response_time": result.get("response_time"),
                    "is_duplicate_click": is_duplicate_click,
                    "is_duplicate": proxy.get("is_duplicate_proxy", False) or is_duplicate_click,
                    "duplicate_matched_ip": duplicate_matched_ip,
                    "is_vpn": is_vpn,
                    "vpn_score": vpn_score,
                    "last_checked": datetime.now(timezone.utc).isoformat()
                }
                
                target_db = user_db if db_source == "user_db" else db
                await target_db.proxies.update_one({"id": proxy_id}, {"$set": update_data})
                
                return {"status": result["status"], "is_duplicate": is_duplicate_click, "is_vpn": is_vpn, "error": False}
            except Exception as e:
                logger.error(f"Proxy test error for {proxy_id}: {str(e)}")
                return {"status": "dead", "is_duplicate": False, "is_vpn": False, "error": True}
        
        # Run batch concurrently
        tasks = [test_single(pid, src, p) for pid, (src, p) in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count results
        for r in batch_results:
            results["tested"] += 1
            if isinstance(r, Exception):
                results["errors"] += 1
                results["dead"] += 1
            elif isinstance(r, dict):
                if r.get("error"):
                    results["errors"] += 1
                if r.get("status") == "alive":
                    results["alive"] += 1
                else:
                    results["dead"] += 1
                if r.get("is_duplicate"):
                    results["duplicate"] += 1
                if r.get("is_vpn"):
                    results["vpn"] += 1
    
    return {
        "message": f"Tested {results['tested']} proxies",
        **results
    }

# CORE FUNCTION: Check if IP is duplicate - USED BY BOTH PROXY TEST AND LINK REDIRECT
# ONLY CHECKS IPv4 - IPv6 is completely ignored
async def is_ip_duplicate_in_any_database(ip_to_check: str, user_db) -> tuple:
    """
    Check if an IP exists in ANY database.
    Returns (is_duplicate: bool, found_in: str or None)
    
    IMPORTANT: ONLY checks IPv4 addresses. IPv6 is completely ignored.
    This ensures proxy test (which only gets IPv4) matches link redirect behavior.
    """
    if not ip_to_check:
        return False, None
    
    # Skip IPv6 addresses completely
    if ":" in ip_to_check:
        return False, None
    
    # ONLY check IPv4 fields - NO IPv6
    ip_conditions = [
        {"ip_address": ip_to_check},
        {"ipv4": ip_to_check},
        {"detected_ip": ip_to_check},
        {"all_ips": ip_to_check},
        {"proxy_ips": ip_to_check}
    ]
    duplicate_query = {"$or": ip_conditions}
    
    # 1. Check user's own database
    try:
        existing = await user_db.clicks.find_one(duplicate_query, {"_id": 0, "id": 1})
        if existing:
            return True, "user_db"
    except:
        pass
    
    # 2. Check main database
    try:
        existing = await db.clicks.find_one(duplicate_query, {"_id": 0, "id": 1})
        if existing:
            return True, "main_db"
    except:
        pass
    
    # 3. Check ALL other user databases
    try:
        all_db_names = await client.list_database_names()
        user_databases = [name for name in all_db_names if name.startswith("trackmaster_user_")]
        
        for other_db_name in user_databases:
            try:
                other_db = client[other_db_name]
                existing = await other_db.clicks.find_one(duplicate_query, {"_id": 0, "id": 1})
                if existing:
                    return True, other_db_name
            except:
                continue
    except:
        pass
    
    return False, None

@api_router.post("/proxies/{proxy_id}/test")
async def test_proxy(
    proxy_id: str, 
    user: dict = Depends(get_current_user_with_fresh_data),
    skip_vpn: bool = False
):
    check_user_feature(user, "proxies")
    
    # Get the user's database for accurate duplicate checking
    user_db = get_db_for_user(user)
    main_user_id = user["id"]
    
    # Complete isolation: users can only test their OWN proxies
    query = {"id": proxy_id, "user_id": user["id"]}
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    else:
        query["created_by"] = None
    
    proxy = await user_db.proxies.find_one(query, {"_id": 0})
    if not proxy:
        # Also check main db for legacy proxies
        proxy = await db.proxies.find_one(query, {"_id": 0})
    if not proxy:
        raise HTTPException(status_code=404, detail="Proxy not found")
    
    proxy_string = proxy["proxy_string"]
    proxy_type = proxy["proxy_type"]
    
    detected_ip = None
    detected_ips = []  # Store all detected IPs
    response_time = None
    status = "dead"
    error_msg = None
    
    for protocol in ["http"]:  # Only try HTTP first (faster)
        try:
            if "@" in proxy_string:
                if proxy_type == "http":
                    proxy_url = f"http://{proxy_string}"
                else:
                    proxy_url = f"socks5://{proxy_string}"
            else:
                if ":" in proxy_string:
                    parts = proxy_string.split(":")
                    if len(parts) == 4:
                        host, port, username, password = parts
                        if proxy_type == "http":
                            proxy_url = f"http://{username}:{password}@{host}:{port}"
                        else:
                            proxy_url = f"socks5://{username}:{password}@{host}:{port}"
                    elif len(parts) == 2:
                        if proxy_type == "http":
                            proxy_url = f"http://{proxy_string}"
                        else:
                            proxy_url = f"socks5://{proxy_string}"
                    else:
                        raise ValueError("Invalid proxy format")
                else:
                    raise ValueError("Invalid proxy format")
            
            start_time = datetime.now(timezone.utc)
            
            proxy_config = httpx.Proxy(url=proxy_url)
            async with httpx.AsyncClient(
                proxy=proxy_config,
                timeout=3,  # Fast 3 second timeout
                follow_redirects=True
            ) as client:
                # Check IPv4 first using ipify
                test_url = "http://api.ipify.org?format=json"
                response = await client.get(test_url)
                response_time = (datetime.now(timezone.utc) - start_time).total_seconds()
                
                if response.status_code == 200:
                    data = response.json()
                    origin = data.get("ip") or data.get("origin") or ""
                    if origin:
                        detected_ips = [ip.strip() for ip in origin.split(",") if ip.strip()]
                        detected_ip = detected_ips[-1] if detected_ips else None
                    status = "alive"
                
                # Also try to get IPv6 using ipify IPv6 endpoint
                try:
                    ipv6_url = "http://api64.ipify.org?format=json"
                    ipv6_response = await client.get(ipv6_url, timeout=3)
                    if ipv6_response.status_code == 200:
                        ipv6_data = ipv6_response.json()
                        ipv6_ip = ipv6_data.get("ip", "")
                        if ipv6_ip and ipv6_ip not in detected_ips:
                            detected_ips.append(ipv6_ip)
                            logger.info(f"Proxy test: Also detected IPv6: {ipv6_ip}")
                except Exception as ipv6_err:
                    logger.debug(f"IPv6 check failed (proxy may not support IPv6): {ipv6_err}")
                
                if status == "alive":
                    break
        except Exception as e:
            error_msg = str(e)
            continue
    
    logger.info(f"Proxy test: Detected IPs: {detected_ips}")
    
    # Get the proxy's HOST IP
    proxy_host_ip = None
    try:
        proxy_parts = proxy_string.split(":")
        if len(proxy_parts) >= 2:
            potential_ip = proxy_parts[0].strip()
            if potential_ip.replace(".", "").isdigit() or ":" in potential_ip:
                proxy_host_ip = potential_ip
    except:
        pass
    
    # Build list of ALL IPs to check
    all_ips_to_check = set()
    if detected_ips:
        for dip in detected_ips:
            if dip:
                all_ips_to_check.add(dip)
    if proxy_host_ip:
        all_ips_to_check.add(proxy_host_ip)
    
    logger.info(f"Proxy test: Checking IPs: {all_ips_to_check}")
    
    # USE THE SHARED FUNCTION - SAME AS LINK REDIRECT
    is_duplicate_click = False
    duplicate_matched_ip = None
    found_in_db = None
    
    for ip_to_check in all_ips_to_check:
        is_dup, found_db = await is_ip_duplicate_in_any_database(ip_to_check, user_db)
        if is_dup:
            is_duplicate_click = True
            duplicate_matched_ip = ip_to_check
            found_in_db = found_db
            logger.info(f"Proxy test: DUPLICATE found! IP={ip_to_check}, DB={found_db}")
            break
    
    is_duplicate = proxy.get("is_duplicate_proxy", False) or is_duplicate_click
    
    logger.info(f"Proxy test result: is_duplicate={is_duplicate}, matched_ip={duplicate_matched_ip}")
    
    # Check VPN status (skip if requested for faster testing)
    is_vpn = False
    vpn_score = 0
    vpn_source = "none"
    if not skip_vpn and detected_ip and status == "alive":
        logger.info(f"Checking VPN status for proxy IP: {detected_ip}")
        # Use check_vpn_detailed for API tracking and fallback
        vpn_info = await check_vpn_detailed(detected_ip)
        is_vpn = vpn_info.get("is_vpn", False)
        vpn_score = vpn_info.get("vpn_score", 0)
        vpn_source = vpn_info.get("source", "none")
        logger.info(f"VPN check result for {detected_ip}: is_vpn={is_vpn}, score={vpn_score}, source={vpn_source}")
    
    # Separate IPv4 and IPv6 from detected IPs
    detected_ipv4 = None
    detected_ipv6 = None
    for ip in detected_ips:
        if ip:
            if ":" in ip:  # IPv6 contains colons
                detected_ipv6 = ip
            else:  # IPv4 has dots only
                detected_ipv4 = ip
    
    # Update proxy in user_db first, then main db
    update_data = {
        "status": status,
        "response_time": round(response_time, 3) if response_time else None,
        "detected_ip": detected_ip,
        "detected_ipv4": detected_ipv4,  # Separate IPv4 field
        "detected_ipv6": detected_ipv6,  # Separate IPv6 field
        "proxy_host_ip": proxy_host_ip,  # The proxy's own IP from proxy string
        "all_detected_ips": detected_ips,  # Store ALL detected IPs
        "all_ips_checked": list(all_ips_to_check),  # All IPs we checked for duplicates
        "is_duplicate_click": is_duplicate_click,
        "is_duplicate": is_duplicate,
        "duplicate_matched_ip": duplicate_matched_ip,
        "is_vpn": is_vpn,
        "vpn_score": vpn_score,
        "vpn_source": vpn_source,
        "last_checked": datetime.now(timezone.utc).isoformat()
    }
    
    # Try to update in user_db first
    result = await user_db.proxies.update_one({"id": proxy_id}, {"$set": update_data})
    if result.matched_count == 0:
        # Fallback to main db for legacy proxies
        await db.proxies.update_one({"id": proxy_id}, {"$set": update_data})
    
    if status == "alive":
        return {
            "status": "alive",
            "response_time": round(response_time, 3),
            "detected_ip": detected_ip,
            "detected_ipv4": detected_ipv4,
            "detected_ipv6": detected_ipv6,
            "all_detected_ips": detected_ips,
            "is_duplicate_click": is_duplicate_click,
            "duplicate_matched_ip": duplicate_matched_ip,
            "is_vpn": is_vpn,
            "vpn_score": vpn_score,
            "vpn_source": vpn_source
        }
    else:
        return {"status": "dead", "error": error_msg or "Connection failed"}

@api_router.delete("/proxies/{proxy_id}")
async def delete_proxy(proxy_id: str, user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "proxies")
    user_db = get_db_for_user(user)
    
    # Complete isolation: users can only delete their OWN proxies
    query = {"id": proxy_id, "user_id": user["id"]}
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    else:
        query["created_by"] = None
    
    # Try deleting from user_db first
    result = await user_db.proxies.delete_one(query)
    if result.deleted_count == 0:
        # Try main db for legacy proxies
        result = await db.proxies.delete_one(query)
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Proxy not found")
    return {"message": "Proxy deleted"}

@api_router.post("/proxies/bulk-delete")
async def bulk_delete_proxies(proxy_ids: List[str], user: dict = Depends(get_current_user_with_fresh_data)):
    check_user_feature(user, "proxies")
    user_db = get_db_for_user(user)
    
    # Complete isolation: users can only delete their OWN proxies
    query = {"id": {"$in": proxy_ids}, "user_id": user["id"]}
    if user.get("is_sub_user"):
        query["created_by"] = user.get("sub_user_id")
    else:
        query["created_by"] = None
    
    # Delete from both databases
    result_user_db = await user_db.proxies.delete_many(query)
    result_main_db = await db.proxies.delete_many(query)
    total_deleted = result_user_db.deleted_count + result_main_db.deleted_count
    return {"message": f"Deleted {total_deleted} proxies", "deleted_count": total_deleted}

@api_router.post("/proxies/refresh-status")
async def refresh_proxy_status(user: dict = Depends(get_current_user_with_fresh_data)):
    """Re-check all proxies against current click database to update duplicate status"""
    check_user_feature(user, "proxies")
    
    main_user_id = user["id"]
    user_db = get_db_for_user(user)
    
    # Get user's proxies from both databases
    proxy_query = {"user_id": main_user_id}
    if user.get("is_sub_user"):
        proxy_query["created_by"] = user.get("sub_user_id")
    else:
        proxy_query["created_by"] = None
    
    proxies_user_db = await user_db.proxies.find(proxy_query, {"_id": 0}).to_list(100000)
    proxies_main_db = await db.proxies.find(proxy_query, {"_id": 0}).to_list(100000)
    
    # Combine and dedupe
    all_proxies = {p["id"]: ("user_db", p) for p in proxies_user_db}
    for p in proxies_main_db:
        if p["id"] not in all_proxies:
            all_proxies[p["id"]] = ("main_db", p)
    
    if not all_proxies:
        return {"message": "No proxies to refresh", "updated": 0}
    
    # Collect ALL used IPs from ENTIRE DATABASE (all users, all user databases)
    # This ensures proxy duplicate check matches link redirect duplicate check
    all_used_ips = await get_all_click_ips_from_entire_database()
    
    logger.info(f"Refresh: Checking against {len(all_used_ips)} IPs from entire database (all users)")
    
    # Update each proxy's duplicate status
    updated_count = 0
    new_duplicates = 0
    for proxy_id, (db_source, proxy) in all_proxies.items():
        proxy_ip = proxy.get("proxy_ip") or extract_ip_from_proxy(proxy.get("proxy_string", ""))
        detected_ip = proxy.get("detected_ip")
        all_detected_ips = proxy.get("all_detected_ips", [])
        
        # Check if ANY of extracted IP, detected IP, or all_detected_ips is in used IPs
        is_duplicate_click = False
        if proxy_ip in all_used_ips:
            is_duplicate_click = True
        elif detected_ip and detected_ip in all_used_ips:
            is_duplicate_click = True
        elif all_detected_ips:
            for dip in all_detected_ips:
                if dip in all_used_ips:
                    is_duplicate_click = True
                    break
        
        is_duplicate = proxy.get("is_duplicate_proxy", False) or is_duplicate_click
        
        # Only update if status changed
        if proxy.get("is_duplicate_click") != is_duplicate_click or proxy.get("is_duplicate") != is_duplicate:
            target_db = user_db if db_source == "user_db" else db
            await target_db.proxies.update_one(
                {"id": proxy["id"]},
                {"$set": {
                    "is_duplicate_click": is_duplicate_click,
                    "is_duplicate": is_duplicate
                }}
            )
            updated_count += 1
            if is_duplicate_click and not proxy.get("is_duplicate_click"):
                new_duplicates += 1
    
    return {
        "message": f"Refreshed {len(all_proxies)} proxies",
        "total_proxies": len(all_proxies),
        "updated": updated_count,
        "new_duplicates_found": new_duplicates,
        "total_used_ips": len(all_used_ips)
    }

@api_router.post("/offers", response_model=dict)
async def create_offer(offer: OfferCreate, user: dict = Depends(get_current_user)):
    link = await db.links.find_one({"id": offer.link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    offer_doc = {
        "id": str(uuid.uuid4()),
        "link_id": offer.link_id,
        "offer_url": offer.offer_url,
        "weight": offer.weight,
        "clicks": 0,
        "conversions": 0,
        "revenue": 0.0,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    await db.offers.insert_one(offer_doc)
    # Remove MongoDB _id field before returning
    offer_doc.pop('_id', None)
    return offer_doc

@api_router.get("/offers/{link_id}")
async def get_offers(link_id: str, user: dict = Depends(get_current_user)):
    link = await db.links.find_one({"id": link_id, "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    offers = await db.offers.find({"link_id": link_id}, {"_id": 0}).to_list(100)
    return offers

@api_router.delete("/offers/{offer_id}")
async def delete_offer(offer_id: str, user: dict = Depends(get_current_user)):
    offer = await db.offers.find_one({"id": offer_id}, {"_id": 0})
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    
    link = await db.links.find_one({"id": offer["link_id"], "user_id": user["id"]}, {"_id": 0})
    if not link:
        raise HTTPException(status_code=403, detail="Access denied")
    
    await db.offers.delete_one({"id": offer_id})
    return {"message": "Offer deleted"}

# Multiple route decorators to support both direct access and via /api prefix
# /api/r/ and /api/t/ - accessible through Kubernetes ingress (preferred for Emergent)
# /t/ and /r/ - for direct backend access and DigitalOcean deployment
@api_router.get("/r/{short_code}")
@api_router.get("/t/{short_code}")
@app.get("/t/{short_code}")
@app.get("/r/{short_code}")
async def redirect_link(short_code: str, request: Request, sub1: str = "", sub2: str = "", sub3: str = ""):
    # Use cached link lookup for high traffic performance
    link = await get_cached_link(short_code)
    if not link or link["status"] != "active":
        raise HTTPException(status_code=404, detail="Link not found or inactive")
    
    # Get the main user ID for this link
    # If the link was created by a sub-user, we need to find the parent user
    link_user_id = link.get("user_id")
    link_created_by = link.get("created_by")
    
    # Determine the main user's database to use
    if link_created_by:
        # Link was created by a sub-user, find their parent
        sub_user = await db.sub_users.find_one({"id": link_created_by})
        if sub_user:
            main_user_id = sub_user.get("parent_user_id", link_user_id)
        else:
            main_user_id = link_user_id
    else:
        main_user_id = link_user_id
    
    # Get the main user's database
    user_db = get_user_db(main_user_id)
    
    # Get all client IPs (IPv4 and IPv6)
    client_ips = get_all_client_ips(request)
    client_ip = client_ips["primary"]
    ipv4 = client_ips["ipv4"]
    all_ips = client_ips["all"]
    proxy_ips = client_ips.get("proxy_ips", [])
    
    # Check for duplicate clicks - IPv4 ONLY
    ip_conditions = []
    
    # Check primary IP (IPv4 only)
    if client_ip and ":" not in client_ip:
        ip_conditions.append({"ip_address": client_ip})
        ip_conditions.append({"ipv4": client_ip})
        ip_conditions.append({"detected_ip": client_ip})
        ip_conditions.append({"all_ips": client_ip})
        ip_conditions.append({"proxy_ips": client_ip})
    
    # Check IPv4 specifically
    if ipv4 and ipv4 != client_ip and ":" not in ipv4:
        ip_conditions.append({"ip_address": ipv4})
        ip_conditions.append({"ipv4": ipv4})
        ip_conditions.append({"detected_ip": ipv4})
        ip_conditions.append({"all_ips": ipv4})
        ip_conditions.append({"proxy_ips": ipv4})
    
    # SKIP IPv6 completely
    
    # Check all proxy IPs from headers (only IPv4)
    for pip in proxy_ips:
        if pip and pip not in [client_ip, ipv4] and ":" not in pip:
            ip_conditions.append({"ip_address": pip})
            ip_conditions.append({"ipv4": pip})
            ip_conditions.append({"detected_ip": pip})
            ip_conditions.append({"all_ips": pip})
            ip_conditions.append({"proxy_ips": pip})
    
    # Check all_ips array (only IPv4)
    for ip in all_ips:
        if ip and ip not in [client_ip, ipv4] and ":" not in ip:
            ip_conditions.append({"ip_address": ip})
            ip_conditions.append({"all_ips": ip})
    
    # If no IPv4 conditions found, use a fallback
    if not ip_conditions:
        if ipv4:
            ip_conditions.append({"ipv4": ipv4})
        elif client_ip and ":" not in client_ip:
            ip_conditions.append({"ip_address": client_ip})
        else:
            ip_conditions.append({"ip_address": "no-ipv4-detected"})
    
    # STRICT GLOBAL DUPLICATE CHECK - One IP can only pass ONCE across ALL links
    # If IP was seen on ANY link by ANY user, it's blocked everywhere
    duplicate_query = {"$or": ip_conditions}  # No link_id filter - global check
    
    existing_click = None
    
    # 1. Check user's own database first (fastest)
    try:
        existing_click = await user_db.clicks.find_one(duplicate_query, {"_id": 0, "ip_address": 1, "link_id": 1})
    except Exception:
        pass
    
    # 2. Check main database (legacy data)
    if not existing_click:
        try:
            existing_click = await db.clicks.find_one(duplicate_query, {"_id": 0, "ip_address": 1, "link_id": 1})
        except Exception:
            pass
    
    # 3. Check ALL other user databases for complete global duplicate blocking
    if not existing_click:
        try:
            all_db_names = await client.list_database_names()
            user_databases = [name for name in all_db_names if name.startswith("trackmaster_user_")]
            
            for other_db_name in user_databases:
                if existing_click:
                    break
                try:
                    other_db = client[other_db_name]
                    existing_click = await other_db.clicks.find_one(duplicate_query, {"_id": 0, "ip_address": 1, "link_id": 1})
                except Exception:
                    continue
        except Exception:
            pass
    
    # Get timer settings for display (NOT for checking duplicates)
    timer_enabled = link.get("duplicate_timer_enabled", False)
    timer_seconds = link.get("duplicate_timer_seconds", 5)
    
    if existing_click:
        # Found duplicate - STRICTLY BLOCK - NO ACCESS AT ALL
        matched_ip = existing_click.get("ip_address", "Unknown")
        matched_link = existing_click.get("link_id", "Unknown")
        
        # Timer controls auto-close behavior
        # Timer ON = page auto-closes after X seconds
        # Timer OFF = page stays open (no countdown)
        if timer_enabled and timer_seconds > 0:
            # Timer ON - show countdown and auto-close
            return Response(
                content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script>
        var countdown = {timer_seconds};
        var countdownEl;
        
        window.onload = function() {{
            countdownEl = document.getElementById('countdown');
            setInterval(updateCountdown, 1000);
        }};
        
        function updateCountdown() {{
            countdown--;
            if (countdownEl && countdown >= 0) {{
                countdownEl.textContent = countdown;
            }}
            if (countdown <= 0) {{
                closeTab();
            }}
        }}
        
        function closeTab() {{
            window.close();
            if (window.opener) {{
                window.opener = null;
                window.open('', '_self');
                window.close();
            }}
            if (window.history.length > 1) {{
                window.history.go(-(window.history.length));
            }}
            setTimeout(function() {{
                window.location.replace('about:blank');
                window.close();
            }}, 100);
            setTimeout(function() {{
                document.documentElement.innerHTML = '';
                document.body.style.background = '#000';
            }}, 200);
        }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: #000000; 
            color: #FFFFFF; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            height: 100vh; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            text-align: center;
            padding: 20px;
        }}
        .container {{ max-width: 400px; }}
        .icon {{ font-size: 64px; margin-bottom: 20px; }}
        h1 {{ color: #EF4444; font-size: 32px; margin-bottom: 16px; font-weight: 700; }}
        .message {{ color: #A1A1AA; font-size: 16px; margin-bottom: 12px; line-height: 1.5; }}
        .ip-info {{ color: #525252; font-size: 12px; margin-top: 20px; padding: 10px; background: #111111; border-radius: 8px; }}
        .countdown {{ color: #F59E0B; font-size: 18px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">⛔</div>
        <h1>Duplicate IP</h1>
        <p class="message">This IP address has already been used.<br>Access denied.</p>
        <div class="ip-info">IP: {client_ip}</div>
        <p class="countdown">Closing in <span id="countdown">{timer_seconds}</span> seconds...</p>
    </div>
</body>
</html>""",
                media_type="text/html",
                status_code=403
            )
        else:
            # Timer OFF - page stays open (no countdown)
            return Response(
                content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: #000000; 
            color: #FFFFFF; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            height: 100vh; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            text-align: center;
            padding: 20px;
        }}
        .container {{ max-width: 400px; }}
        .icon {{ font-size: 64px; margin-bottom: 20px; }}
        h1 {{ color: #EF4444; font-size: 32px; margin-bottom: 16px; font-weight: 700; }}
        .message {{ color: #A1A1AA; font-size: 16px; margin-bottom: 12px; line-height: 1.5; }}
        .ip-info {{ color: #525252; font-size: 12px; margin-top: 20px; padding: 10px; background: #111111; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">⛔</div>
        <h1>Duplicate IP</h1>
        <p class="message">This IP address has already been used.<br>Access denied.</p>
        <div class="ip-info">IP: {client_ip}</div>
    </div>
</body>
</html>""",
                media_type="text/html",
                status_code=403
            )
    
    # Also check against ALL proxies in the ENTIRE database (not just user's)
    # This ensures an IP used as proxy by ANY user is marked as duplicate
    proxy_ip_conditions = []
    for ip in [client_ip, ipv4] + proxy_ips + all_ips:
        if ip:
            proxy_ip_conditions.append({"ip_address": ip})
            proxy_ip_conditions.append({"detected_ip": ip})
            proxy_ip_conditions.append({"ipv4": ip})
            proxy_ip_conditions.append({"all_ips": ip})
            proxy_ip_conditions.append({"proxy_ips": ip})
            proxy_ip_conditions.append({"proxy_string": {"$regex": ip}})
    
    if proxy_ip_conditions:
        # Check user's proxies
        existing_proxy = await user_db.proxies.find_one({"$or": proxy_ip_conditions})
        
        # Check ALL proxies in main database
        if not existing_proxy:
            existing_proxy = await db.proxies.find_one({"$or": proxy_ip_conditions})
    else:
        existing_proxy = None
    
    is_duplicate_proxy = existing_proxy is not None
    if is_duplicate_proxy:
        # print(f"DEBUG: IP matches existing proxy in database - proxy_id: {existing_proxy.get('id', 'unknown')}")
        # STRICTLY BLOCK - IP matches a known proxy
        return Response(
            content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Access Denied</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            background: #000000; 
            color: #FFFFFF; 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            height: 100vh; 
            display: flex; 
            align-items: center; 
            justify-content: center; 
            text-align: center;
            padding: 20px;
        }}
        .container {{
            max-width: 400px;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{ 
            color: #EF4444; 
            font-size: 32px; 
            margin-bottom: 16px;
            font-weight: 700;
        }}
        .message {{
            color: #A1A1AA;
            font-size: 16px;
            margin-bottom: 12px;
            line-height: 1.5;
        }}
        .ip-info {{
            color: #525252;
            font-size: 12px;
            margin-top: 20px;
            padding: 10px;
            background: #111111;
            border-radius: 8px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">🚫</div>
        <h1>Proxy Detected</h1>
        <p class="message">This IP matches a known proxy.<br>Access denied.</p>
        <div class="ip-info">IP: {client_ip}</div>
    </div>
</body>
</html>""",
            media_type="text/html",
            status_code=403
        )
    
    user_agent = request.headers.get("user-agent", "")
    referrer = request.headers.get("referer", "")
    
    ip_info = await get_country_from_ip(client_ip)
    country = ip_info["country"]
    city = ip_info.get("city", "")
    region = ip_info.get("region", "")
    lat = ip_info.get("lat", 0)
    lon = ip_info.get("lon", 0)
    isp = ip_info.get("isp", "")
    is_vpn = ip_info["is_vpn"]
    is_proxy = ip_info["is_proxy"]
    vpn_score = ip_info.get("vpn_score", 0)
    
    # print(f"DEBUG: Geolocation - Country: {country}, City: {city}, Region: {region}, VPN: {is_vpn}, Score: {vpn_score}")
    
    if link.get("block_vpn") and (is_vpn or is_proxy):
        return Response(
            content=f"""<!DOCTYPE html>
<html>
<head>
    <title>VPN/Proxy Detected</title>
    <script>
        var countdown = 5;
        var countdownEl;
        
        window.onload = function() {{
            countdownEl = document.getElementById('countdown');
            setInterval(updateCountdown, 1000);
        }};
        
        function updateCountdown() {{
            countdown--;
            if (countdownEl && countdown >= 0) {{
                countdownEl.textContent = countdown;
            }}
            if (countdown <= 0) {{
                closeTab();
            }}
        }}
        
        function closeTab() {{
            window.close();
            if (window.opener) {{
                window.opener = null;
                window.open('', '_self');
                window.close();
            }}
            if (window.history.length > 1) {{
                window.history.go(-(window.history.length));
            }}
            setTimeout(function() {{
                window.location.replace('about:blank');
                window.close();
            }}, 100);
            setTimeout(function() {{
                document.documentElement.innerHTML = '';
                document.body.style.background = '#000';
            }}, 200);
        }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; }}
        body {{ background: #09090B; color: #FFF; font-family: system-ui, sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center; }}
        h1 {{ color: #EF4444; font-size: 36px; margin-bottom: 12px; }}
        p {{ color: #888; font-size: 16px; margin: 8px 0; }}
        .countdown {{ color: #F59E0B; font-size: 20px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div>
        <h1>🚫 VPN/Proxy Detected</h1>
        <p>VPN/Proxy connections not allowed.</p>
        <p style="font-size:12px;">Fraud Score: {vpn_score}</p>
        <p class="countdown">Closing in <span id="countdown">5</span>...</p>
    </div>
</body>
</html>""",
            media_type="text/html",
            status_code=403
        )
    
    allowed_countries = link.get("allowed_countries", [])
    if allowed_countries:
        # Normalize all country names for comparison
        normalized_allowed = [normalize_country(c).lower() for c in allowed_countries]
        normalized_visitor = normalize_country(country).lower()
        visitor_country_lower = country.lower().strip()
        
        # print(f"DEBUG: Country restriction check:")
        # print(f"DEBUG:   Visitor country: '{country}' -> normalized: '{normalized_visitor}'")
        # print(f"DEBUG:   Allowed countries: {allowed_countries}")
        # print(f"DEBUG:   Normalized allowed: {normalized_allowed}")
        
        # Check if visitor's country matches any allowed country (case-insensitive)
        is_allowed = (
            visitor_country_lower in [c.lower() for c in allowed_countries] or
            normalized_visitor in normalized_allowed or
            country in allowed_countries or
            normalize_country(country) in [normalize_country(c) for c in allowed_countries]
        )
        
        # print(f"DEBUG:   Country allowed: {is_allowed}")
        
        if not is_allowed:
            allowed_display = ", ".join(allowed_countries)
            return Response(
                content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Country Restricted</title>
    <script>
        var countdown = 5;
        var countdownEl;
        
        window.onload = function() {{
            countdownEl = document.getElementById('countdown');
            setInterval(updateCountdown, 1000);
        }};
        
        function updateCountdown() {{
            countdown--;
            if (countdownEl && countdown >= 0) {{
                countdownEl.textContent = countdown;
            }}
            if (countdown <= 0) {{
                closeTab();
            }}
        }}
        
        function closeTab() {{
            window.close();
            if (window.opener) {{
                window.opener = null;
                window.open('', '_self');
                window.close();
            }}
            if (window.history.length > 1) {{
                window.history.go(-(window.history.length));
            }}
            setTimeout(function() {{
                window.location.replace('about:blank');
                window.close();
            }}, 100);
            setTimeout(function() {{
                document.documentElement.innerHTML = '';
                document.body.style.background = '#000';
            }}, 200);
        }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; }}
        body {{ background: #09090B; color: #FFF; font-family: system-ui, sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center; }}
        h1 {{ color: #EF4444; font-size: 36px; margin-bottom: 12px; }}
        p {{ color: #888; font-size: 16px; margin: 8px 0; }}
        .countdown {{ color: #F59E0B; font-size: 20px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div>
        <h1>🌍 Country Restricted</h1>
        <p>Only available in: {allowed_display}</p>
        <p style="font-size:12px;">Your location: {country}</p>
        <p class="countdown">Closing in <span id="countdown">5</span>...</p>
    </div>
</body>
</html>""",
                media_type="text/html",
                status_code=403
            )
    
    device_info = detect_device(user_agent)
    
    # Check OS restriction
    allowed_os = link.get("allowed_os", [])
    if allowed_os:
        visitor_os = device_info["os_name"]
        # print(f"DEBUG: Checking OS restriction - Visitor OS: {visitor_os}, Allowed OS: {allowed_os}")
        
        if visitor_os not in allowed_os:
            allowed_display = ", ".join(allowed_os)
            return Response(
                content=f"""<!DOCTYPE html>
<html>
<head>
    <title>Device Restricted</title>
    <script>
        var countdown = 5;
        var countdownEl;
        
        window.onload = function() {{
            countdownEl = document.getElementById('countdown');
            setInterval(updateCountdown, 1000);
        }};
        
        function updateCountdown() {{
            countdown--;
            if (countdownEl && countdown >= 0) {{
                countdownEl.textContent = countdown;
            }}
            if (countdown <= 0) {{
                closeTab();
            }}
        }}
        
        function closeTab() {{
            window.close();
            if (window.opener) {{
                window.opener = null;
                window.open('', '_self');
                window.close();
            }}
            if (window.history.length > 1) {{
                window.history.go(-(window.history.length));
            }}
            setTimeout(function() {{
                window.location.replace('about:blank');
                window.close();
            }}, 100);
            setTimeout(function() {{
                document.documentElement.innerHTML = '';
                document.body.style.background = '#000';
            }}, 200);
        }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; }}
        body {{ background: #09090B; color: #FFF; font-family: system-ui, sans-serif; height: 100vh; display: flex; align-items: center; justify-content: center; text-align: center; }}
        h1 {{ color: #EF4444; font-size: 36px; margin-bottom: 12px; }}
        p {{ color: #888; font-size: 16px; margin: 8px 0; }}
        .countdown {{ color: #F59E0B; font-size: 20px; margin-top: 16px; }}
    </style>
</head>
<body>
    <div>
        <h1>📱 Device Restricted</h1>
        <p>Only available on: {allowed_display}</p>
        <p style="font-size:12px;">Your device: {visitor_os}</p>
        <p class="countdown">Closing in <span id="countdown">5</span>...</p>
    </div>
</body>
</html>""",
                media_type="text/html",
                status_code=403
            )
    
    click_id = str(uuid.uuid4())
    
    # For storing clicks, use IPv4 as the primary IP address
    # This ensures consistency with duplicate checking which ignores IPv6
    primary_ip_for_storage = ipv4 or client_ip
    
    # Get all URL parameters for referrer detection
    url_params = dict(request.query_params)
    
    # Categorize referrer source - use forced_source from link if set
    if link.get("forced_source"):
        referrer_info = {
            "source": link["forced_source"],
            "source_name": link.get("forced_source_name") or link["forced_source"].title(),
            "domain": None,
            "detected_from": "forced"
        }
    else:
        # Pass URL params for better detection (igshid, fbclid, etc.)
        referrer_info = categorize_referrer(referrer, url_params)
    
    click_doc = {
        "id": str(uuid.uuid4()),
        "click_id": click_id,
        "link_id": link["id"],
        "user_id": main_user_id,
        "created_by": link_created_by,
        "ip_address": primary_ip_for_storage,  # Store IPv4 as primary
        "ipv4": ipv4,
        "all_ips": all_ips,
        "proxy_ips": proxy_ips,
        "country": country,
        "city": city,
        "region": region,
        "lat": lat,
        "lon": lon,
        "isp": isp,
        "is_vpn": is_vpn,
        "is_proxy": is_proxy,
        "is_duplicate_proxy": is_duplicate_proxy,
        "vpn_score": vpn_score,
        "user_agent": user_agent,
        "user_agent_raw": user_agent,  # Store raw user agent for debugging
        "referrer": referrer,
        "referrer_source": referrer_info["source"],
        "referrer_source_name": referrer_info["source_name"],
        "referrer_domain": referrer_info["domain"],
        "referrer_detected_from": referrer_info.get("detected_from", "unknown"),  # Track how referrer was detected
        "forced_source": link.get("forced_source"),  # Track if source was forced
        "device": device_info["device_type"],
        "device_type": device_info["device_type"],
        "device_brand": device_info.get("device_brand", "Unknown"),
        "device_model": device_info.get("device_model", "Unknown"),
        "device_display": device_info.get("device_display", device_info["device_type"]),
        "os_name": device_info["os_name"],
        "os_version": device_info["os_version"],
        "browser": device_info["browser"],
        "browser_version": device_info.get("browser_version", ""),
        "browser_display": device_info.get("browser_display", device_info["browser"]),
        "url_params": url_params,  # Store URL params for analysis
        "sub1": sub1 or None,
        "sub2": sub2 or None,
        "sub3": sub3 or None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    # Save click to user's database
    await user_db.clicks.insert_one(click_doc)
    
    # Update link click count in main database (where links are stored)
    await db.links.update_one({"id": link["id"]}, {"$inc": {"clicks": 1}})
    
    # Broadcast new click to user via WebSocket for real-time updates
    click_doc.pop("_id", None)
    asyncio.create_task(manager.broadcast_click(main_user_id, click_doc))
    
    offers = await db.offers.find({"link_id": link["id"]}, {"_id": 0}).to_list(100)
    
    if offers:
        import random
        total_weight = sum(offer["weight"] for offer in offers)
        rand = random.randint(1, total_weight)
        
        cumulative = 0
        selected_offer = None
        for offer in offers:
            cumulative += offer["weight"]
            if rand <= cumulative:
                selected_offer = offer
                break
        
        if selected_offer:
            destination_url = selected_offer["offer_url"]
            await db.offers.update_one({"id": selected_offer["id"]}, {"$inc": {"clicks": 1}})
        else:
            destination_url = link["offer_url"]
    else:
        destination_url = link["offer_url"]
    
    # Add clickid parameter
    if "?" in destination_url:
        destination_url += f"&clickid={click_id}"
    else:
        destination_url += f"?clickid={click_id}"
    
    # Add platform simulation parameters if configured
    simulate_platform = link.get("simulate_platform")
    custom_params = link.get("url_params") or {}
    referrer_mode = link.get("referrer_mode", "normal")
    
    if simulate_platform:
        platform_params = generate_platform_params(simulate_platform, custom_params)
        destination_url = build_redirect_url(destination_url, platform_params)
    elif custom_params:
        destination_url = build_redirect_url(destination_url, custom_params)
    
    # Set referrer policy based on referrer_mode
    headers = {}
    if referrer_mode == "no_referrer":
        headers["Referrer-Policy"] = "no-referrer"
    elif referrer_mode == "origin":
        headers["Referrer-Policy"] = "origin"
    
    return RedirectResponse(url=destination_url, status_code=302, headers=headers)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup_db_indexes():
    """Create database indexes for faster queries - OPTIMIZED FOR HIGH TRAFFIC"""
    try:
        # Clicks collection indexes for fast duplicate IP checking
        await db.clicks.create_index([("link_id", 1), ("created_at", -1)])
        await db.clicks.create_index([("created_at", -1)])
        await db.clicks.create_index([("ip_address", 1)])
        await db.clicks.create_index([("ipv4", 1)])
        await db.clicks.create_index([("ipv6", 1)])
        await db.clicks.create_index([("click_id", 1)], unique=True)
        # Compound index for fast duplicate checking
        await db.clicks.create_index([("ip_address", 1), ("created_at", -1)])
        
        # Links collection indexes - short_code is critical for redirects
        await db.links.create_index([("user_id", 1)])
        await db.links.create_index([("short_code", 1)], unique=True)
        
        # Users collection indexes
        await db.users.create_index([("email", 1)], unique=True)
        await db.users.create_index([("id", 1)], unique=True)
        
        # Sub-users collection indexes
        await db.sub_users.create_index([("parent_user_id", 1)])
        await db.sub_users.create_index([("email", 1)], unique=True)
        
        # Proxies collection indexes
        await db.proxies.create_index([("user_id", 1), ("status", 1)])
        await db.proxies.create_index([("proxy_ip", 1)])
        
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")

    # Kick off the UA-versions auto-refresh background task
    try:
        asyncio.create_task(_auto_refresh_ua_versions_task())
        logger.info("UA versions auto-refresh task scheduled (runs on startup + every 24h)")
    except Exception as e:
        logger.warning(f"Could not schedule UA versions auto-refresh: {e}")

    # Reap orphan Real-User-Traffic jobs whose worker died before they could
    # mark themselves done. Without this, the UI keeps showing a permanent
    # "running" job that can never be stopped (the in-memory entry is gone).
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        orphan_q = {"status": {"$in": ["running", "queued"]}}
        orphan_jobs = await db.real_user_traffic_jobs.find(orphan_q, {"_id": 0, "job_id": 1}).to_list(length=500)
        if orphan_jobs:
            for j in orphan_jobs:
                jid = j.get("job_id")
                if not jid:
                    continue
                # Try to package any partial results left on disk.
                zip_path = await _package_partial_results(jid)
                updates = {
                    "status": "stopped",
                    "finished_at": now_iso,
                    "stop_reason": "Worker restarted — job auto-stopped on startup.",
                }
                if zip_path:
                    updates["zip_path"] = zip_path
                await db.real_user_traffic_jobs.update_one(
                    {"job_id": jid}, {"$set": updates}
                )
            logger.info(f"Reaped {len(orphan_jobs)} orphan real-user-traffic job(s) on startup")
    except Exception as e:
        logger.warning(f"Could not reap orphan real-user-traffic jobs: {e}")

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()

# WebSocket endpoint for real-time click updates
@app.websocket("/ws/clicks/{token}")
async def websocket_clicks(websocket: WebSocket, token: str):
    """WebSocket endpoint for real-time click updates"""
    try:
        # Verify token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            await websocket.close(code=4001)
            return
        
        user = await db.users.find_one({"email": email}, {"_id": 0})
        if not user or user.get("status") != "active":
            await websocket.close(code=4002)
            return
        
        user_id = user["id"]
        await manager.connect(websocket, user_id)
        
        try:
            while True:
                # Keep connection alive, listen for any client messages
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            manager.disconnect(websocket, user_id)
    except JWTError:
        await websocket.close(code=4003)