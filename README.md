# 🚀 RealFlow — Real Users. Real Results.

Self-hosted traffic tracking + conversion platform with realistic browser automation.

- **Frontend**: Vercel (`https://realflow.online`)
- **Backend + MongoDB + Chromium**: your home PC, exposed via Cloudflare Tunnel (`https://api.realflow.online`)

---

## ⚡ Home-PC deployment (ONE command)

Once Cloudflare has your domain **Active** and Docker Desktop is installed & running, open **PowerShell as Administrator** and paste this ONE line:

```powershell
irm https://raw.githubusercontent.com/mumair14741-sudo/mumair14741/main/install.ps1 | iex
```

Answer 3 prompts (domain, admin email, password). Everything else is automated:

- ✅ Git installed
- ✅ Repo cloned
- ✅ Cloudflared installed + tunnel created + DNS routed
- ✅ Windows service installed (auto-start on boot)
- ✅ Docker containers built + running
- ✅ `https://api.<your-domain>/health` verified live

Full guide: **[`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)**

---

## Architecture

```
USER BROWSERS
     │
     │ https://realflow.online
     ▼
┌──────────────────────┐
│       VERCEL         │  React frontend (global CDN, auto-SSL)
└──────────┬───────────┘
           │
           │ https://api.realflow.online
           ▼
┌──────────────────────┐
│    CLOUDFLARE        │  Free SSL + DDoS shield + tunnel endpoint
└──────────┬───────────┘
           │ outbound-only tunnel
           ▼
┌──────────────────────┐
│   YOUR HOME PC       │  Docker:
│   (Windows 10/11)    │   • realflow-backend  (FastAPI + Playwright)
│                      │   • realflow-mongo    (MongoDB 7)
└──────────────────────┘
```

---

## Home-PC helper scripts (`deployment/home-pc/`)

| File | What it does |
|------|--------------|
| `SETUP.bat` | **One-click installer** — everything from zero to live |
| `BOOTSTRAP.bat` | Downloads + clones + installs (no repo needed first) |
| `start.bat` | Start Docker containers + tunnel |
| `stop.bat`  | Stop everything |
| `status.bat` | Health check all services |
| `logs.bat`   | Live backend logs |
| `update.bat` | Pull latest code + rebuild containers |
| `env.template` | Environment config template |
| `cloudflared-config.yml.template` | Tunnel config template |
| `setup.ps1` | PowerShell engine behind `SETUP.bat` |

---

## Local development

If you want to run everything on your PC without Vercel / Cloudflare:

```bash
copy deployment\home-pc\env.template .env
notepad .env              # fill ADMIN_PASSWORD, JWT_SECRET_KEY, POSTBACK_TOKEN
docker compose --profile local-frontend up -d --build
```

Open `http://localhost:3000` — that's it.

---

## Tech stack

- **Frontend**: React 19, Tailwind 4, Radix UI, react-router 7
- **Backend**: FastAPI, Motor (async Mongo), Playwright, Pandas
- **Automation**: Chromium-headless-shell 131 via Playwright
- **Infra**: Docker Compose, Cloudflare Tunnel, Vercel
