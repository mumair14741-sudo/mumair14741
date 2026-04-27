# 🚀 Deploy RealFlow — Quick Links

**Full deployment guide**: [`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)

## Setup overview
```
┌──────────────────────┐          ┌──────────────────────┐
│  realflow.online     │          │  api.realflow.online │
│  (Vercel frontend)   │ ────────►│  (Cloudflare Tunnel) │
└──────────────────────┘          └──────────┬───────────┘
                                             │
                                             ▼
                                ┌──────────────────────────┐
                                │   Your Home PC (Windows) │
                                │   Docker containers:     │
                                │   • realflow-backend     │
                                │   • realflow-mongo       │
                                └──────────────────────────┘
```

## Home PC files (copy from `deployment/home-pc/`)
| File | Purpose |
|------|---------|
| `env.template` | Backend environment config template — fill in secrets |
| `cloudflared-config.yml.template` | Cloudflare Tunnel config |
| `start.bat` | One-click start (Docker + tunnel check) |
| `stop.bat` | One-click stop |
| `status.bat` | Check all services health |
| `logs.bat` | Live backend logs |
| `update.bat` | Git pull + rebuild |

## First-time setup summary
1. Cloudflare: add `realflow.online` → change nameservers at registrar
2. Home PC: install Docker Desktop + Git + `cloudflared`
3. Clone repo → copy `.env.template` to `.env` → fill secrets
4. `docker compose up -d --build` → backend running locally
5. `cloudflared tunnel login / create / route dns` → `api.realflow.online` live
6. `cloudflared service install` → auto-start on boot
7. Vercel: import GitHub repo → `REACT_APP_BACKEND_URL=https://api.realflow.online` → deploy
8. Vercel: attach `realflow.online` domain → done 🎉

Full commands and troubleshooting: **[`deployment/DEPLOYMENT.md`](deployment/DEPLOYMENT.md)**
