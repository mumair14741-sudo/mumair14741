# TrackMaster - PRD

## Original Problem Statement
User shared GitHub repo: https://github.com/rylshaark-ship-it/royal-trackmaster.git
Request: Poora project /app mein clone karke chalao, har cheez working honi chahiye taaki user test kar sake.

## Architecture
- Backend: FastAPI (Python 3.11) on port 8001, file: `/app/backend/server.py` (10,651 lines)
- Frontend: React (CRA + craco) on port 3000, entry `/app/frontend/src/App.js`
- Database: MongoDB (local, per-user database pattern — `trackmaster_user_<id>`)
- Auth: JWT (python-jose + passlib/bcrypt), admin + user login, sub-user system
- Browser automation: Playwright (chromium-headless-shell) for Real-User-Traffic & Form-Filler
- Email: Resend / SMTP (optional, disabled by default in this env)

## Setup Done (Jan 2026)
- Cloned public repo into `/app` (preserved `.git`, `.emergent`)
- Installed backend requirements (fastapi 0.115.6, motor 3.6, playwright 1.49.1, passlib[bcrypt], etc.)
- Ran `yarn install` for frontend
- Created `/app/backend/.env` with admin seed creds + JWT secret + Playwright browsers path
- Preserved `/app/frontend/.env` with REACT_APP_BACKEND_URL
- Restarted backend + frontend via supervisor — both running
- Verified: `/health` endpoint OK, mongo_connected=true, admin login returns JWT, user registration works, login UI loads
- Playwright chromium-headless-shell auto-installed on startup

## Features (from repo)
Link tracking, click stats, conversions, proxy management, real-user-traffic automation, form-filler, email checker, separate data, UA generator/checker, import traffic, referrer stats, admin dashboard, sub-users with granular feature flags, branding context, uploaded resources.

## Login Credentials
- User site: https://track-ship-8.preview.emergentagent.com/login
- Admin site: https://track-ship-8.preview.emergentagent.com/admin
- Admin email: admin@trackmaster.local
- Admin password: admin123

## Status
- MVP running, user can log in / register / use admin panel / navigate all pages.
- Optional integrations (Resend/SMTP email, Google OAuth) left unconfigured — user can add keys to `/app/backend/.env` when needed.

## Next Action Items
- User to explore the app and share any specific feature / bug to work on
- Configure email (Resend/SMTP) if forgot-password flow is needed
- Configure Google OAuth if login-with-Google is desired
