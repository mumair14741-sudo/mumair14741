# 🚀 RealFlow — Real Users. Real Results.

Self-hosted traffic tracking + conversion platform with realistic browser automation.

- **Frontend**: Vercel (`https://realflow.online`)
- **Backend + MongoDB + Chromium**: your home PC, exposed via Cloudflare Tunnel (`https://api.realflow.online`)

---

## ⚡ One-click deployment

Full guide: **[`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)**

Quick version:

1. **Cloudflare**: add `realflow.online` → change nameservers at your registrar → wait for "Active".
2. **Vercel**: import this repo → set `REACT_APP_BACKEND_URL=https://api.realflow.online` → deploy → attach `realflow.online` domain.
3. **Home PC**: double-click `deployment/home-pc/SETUP.bat` → answer 3 prompts → done.

The installer handles: Git + Docker + Cloudflared install, tunnel creation, DNS routing, service install, `.env` generation, container build, and boot-time auto-start.

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
