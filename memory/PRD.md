# TrackMaster - PRD

## Original Problem Statement
User ne GitHub repo share kiya (https://github.com/harkin005kunmin-max/harkin-trackmaster.git - TrackMaster full-stack link tracking / traffic management app) aur kaha: "ye repository check kro es ko proper run kr do mein es ke preview ko test kr k es pr kaam krna chahta hun". Aur confirm kiya: "repo public hai ap es ka setup kro mein same project pr kaam krna hai or main branch pr he kaam krna hai."

## Architecture
- **Backend**: FastAPI (Python 3.11) on port 8001 - `/app/backend/server.py` + `form_filler.py`, `real_user_traffic.py`, `ai_automation_generator.py`
- **Frontend**: React 18 (CRA + craco) on port 3000 - `/app/frontend/src`
- **Database**: MongoDB (local) - `trackmaster` DB + per-user DBs
- **Services**: Supervisor-managed (backend, frontend, mongodb)
- **Playwright**: chromium at `/pw-browsers`

## What's been implemented

### Session 1 - Jan 2026 (Repo bring-up)
- Cloned `harkin-trackmaster` main branch into `/app` (preserved `.emergent` + `.git` + protected env vars MONGO_URL / REACT_APP_BACKEND_URL)
- Set `DB_NAME=trackmaster` in `/app/backend/.env`
- Installed backend Python deps from `requirements.txt` (FastAPI 0.115.6, motor 3.6.0, playwright 1.49.1, pandas, openpyxl, user-agents, fake-useragent, faker, resend, passlib, python-jose, bcrypt, etc.)
- Installed frontend deps via `yarn install` (React 18, Radix UI, recharts, react-router-dom 7, axios, tailwind, craco)
- Playwright chromium already available at `/pw-browsers`
- Restarted backend + frontend via supervisor - both RUNNING
- Verified:
  - `GET /api/` - routing works (404 on root is expected, no root route defined)
  - `POST /api/admin/login` - returns JWT token (admin: `admin@trackmaster.local` / `admin123`) via both localhost and external preview URL
  - Frontend login page loads cleanly at https://project-track-8.preview.emergentagent.com with "TrackMaster" title and login/register/admin-login UI
  - `UA versions auto-refresh` startup task ran successfully (12 UA versions updated)

## Preview
- URL: https://project-track-8.preview.emergentagent.com
- Admin: `admin@trackmaster.local` / `admin123`
- Regular users: register via login page; admin enables feature flags per user

## Backlog / Next
- User will now test the preview and drive next feature/bug work
- (P2) SMTP / Resend API key not configured - password reset emails are logged only
- (P2) `server.py` is ~9950 lines - code split deferred
