# 🚀 RealFlow — Production Deployment Guide

**Setup**: Frontend on Vercel + Backend/MongoDB/Chromium on your home PC via Cloudflare Tunnel
**Domain**: `realflow.online`

---

## 🎯 TL;DR — the one-click path

If you prefer the click-and-wait experience, jump to **[Chapter 1: One-Click Install](#chapter-1-one-click-install)**.
If you want the detailed manual walkthrough, scroll to **[Chapter 2: Manual Install](#chapter-2-manual-install)**.

---

# Chapter 1: One-Click Install

Do these once in your browser (Cloudflare + Vercel setup — impossible to automate), then one double-click handles everything on your home PC.

---

## Step 1 — Add domain to Cloudflare (~10 min, browser)

1. Create a free Cloudflare account: <https://dash.cloudflare.com/sign-up>
2. **Add a Site** → enter `realflow.online` → Free plan → Continue.
3. Cloudflare shows you **2 nameservers** (e.g. `lars.ns.cloudflare.com`, `laura.ns.cloudflare.com`). **Copy them.**
4. Log in to the registrar where you bought the domain (Namecheap / GoDaddy / …).
   - Find your domain's DNS settings.
   - Change nameservers from "default" to **Custom DNS**.
   - Paste the 2 Cloudflare nameservers. Save.
5. Wait until Cloudflare shows your domain as **Active** (usually 10 min – 2 hrs). You'll receive an email.

**Once Active, move to Step 2.**

---

## Step 2 — Run the one-click installer (~15 min, home PC)

On your Windows home PC:

1. **Install Docker Desktop** first: <https://www.docker.com/products/docker-desktop/>
   - Install → **restart PC** → open Docker Desktop → wait for "Engine running" green dot.
   - (The installer below will still try to install Docker if you skip this, but a manual install + restart is faster.)

2. **Download the bootstrap file** to your Desktop:
   - Right-click this link → **Save link as…** → save `BOOTSTRAP.bat` to Desktop:
     `https://raw.githubusercontent.com/<your-username>/<your-repo>/main/deployment/home-pc/BOOTSTRAP.bat`
   - Open it in Notepad and update the `GITHUB_URL` line with your actual repo URL.

3. **Double-click `BOOTSTRAP.bat`** → click **Yes** on the UAC prompt.

4. The installer will:
   - Install Git automatically (if missing)
   - Clone your repo to `Desktop\realflow`
   - Launch the full setup script

5. Answer **3 simple prompts**:
   - Domain name  →  `realflow.online`
   - Admin email  →  e.g. `admin@realflow.online`
   - Admin password  →  your strong password (entered twice)

6. Sit back. The script will:
   - ✅ Install cloudflared
   - ✅ Generate secure random secrets (JWT, POSTBACK)
   - ✅ Write your `.env` file
   - ✅ Open Cloudflare login in your browser (**click "Authorize" once**)
   - ✅ Create a tunnel named `realflow`
   - ✅ Route `api.realflow.online` → the tunnel
   - ✅ Install cloudflared as a Windows service (auto-start on boot)
   - ✅ Build + start Docker containers (backend + mongo)
   - ✅ Wait for the backend to become healthy
   - ✅ Add a startup shortcut so everything auto-starts on boot
   - ✅ Verify `https://api.realflow.online/health` is live

7. Expected time: **10–15 min** (first Docker build pulls images and downloads Chromium).

8. When you see **"All Done!"** — your backend is online.

---

## Step 3 — Deploy frontend on Vercel (~10 min, browser)

1. Sign in at <https://vercel.com/signup> with **Continue with GitHub**.
2. **Add New → Project** → import your repo.
3. Configure:
   - **Framework**: Create React App
   - **Root Directory**: `frontend` (click Edit → select)
   - **Build Command**: `CI=false yarn build`
   - **Output Directory**: `build`
4. **Environment Variables**:
   ```
   REACT_APP_BACKEND_URL = https://api.realflow.online
   ```
5. Click **Deploy**. Wait 2–3 min.

### Attach your domain
1. Vercel Project → **Settings → Domains** → Add → `realflow.online`.
2. Vercel shows a CNAME record. Go to **Cloudflare dashboard** → DNS → Add record:
   - Type: CNAME
   - Name: `@`
   - Value: `cname.vercel-dns.com`
   - **Proxy status**: 🟠 **DNS only** (gray cloud) — important
3. Repeat for `www`: CNAME name `www` → value `cname.vercel-dns.com` → DNS only.
4. Wait 1 min → Vercel says "Valid configuration" → 🎉

---

## Step 4 — Test end-to-end (~2 min)

Open `https://realflow.online`:
- [x] Login page loads
- [x] Log in with your admin email + password
- [x] Dashboard loads, shows all the panels
- [x] Create a tracking link → click it → redirects correctly
- [x] Run a small Real-User-Traffic job → conversions count

**You are LIVE.** 🚀

---

# Chapter 2: Manual Install

Prefer to do every step yourself? Follow these phases instead of Chapter 1 Step 2.

### Phase 2.1 — Install tools on your PC
```powershell
winget install --id Git.Git -e --silent
winget install --id Docker.DockerDesktop -e --silent
winget install --id Cloudflare.cloudflared -e --silent
```
Restart PC → open Docker Desktop → wait for engine running.

### Phase 2.2 — Clone & configure
```powershell
cd $HOME\Desktop
git clone https://github.com/<your-username>/<your-repo>.git realflow
cd realflow
copy deployment\home-pc\env.template .env
notepad .env
```
Fill in `ADMIN_PASSWORD`, generate secrets for `JWT_SECRET_KEY` and `POSTBACK_TOKEN`:
```powershell
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```

### Phase 2.3 — Start backend
```powershell
docker compose up -d --build
curl http://localhost:8001/health
```

### Phase 2.4 — Cloudflare tunnel
```powershell
cloudflared tunnel login
cloudflared tunnel create realflow
cloudflared tunnel route dns realflow api.realflow.online
```
Create `C:\Users\<YourName>\.cloudflared\config.yml` from `deployment\home-pc\cloudflared-config.yml.template` — replace `<YourName>` and `<TUNNEL-UUID>`.

### Phase 2.5 — Install tunnel as service
**Admin** PowerShell:
```powershell
cloudflared service install
```

### Phase 2.6 — Test
```powershell
curl https://api.realflow.online/health
```
Should return `{"status":"ok"}`.

Then follow **Step 3** (Vercel) and **Step 4** (final test) from Chapter 1.

---

# 🔄 Day-to-day operations

Double-click any of the `.bat` files in `deployment\home-pc\`:

| File | What it does |
|------|--------------|
| `start.bat`  | Start Docker + tunnel |
| `stop.bat`   | Stop everything |
| `status.bat` | Health check all services |
| `logs.bat`   | Live backend logs (Ctrl+C to exit) |
| `update.bat` | `git pull` + rebuild containers |

---

# 🆘 Troubleshooting

### `https://api.realflow.online/health` returns 502
1. Backend up? → `curl http://localhost:8001/health`
2. Tunnel running? → `Get-Service cloudflared`
3. Restart tunnel: `Restart-Service cloudflared`

### Docker containers won't start
```powershell
docker compose logs backend
```
Typically a missing value in `.env`.

### CORS error in browser console
Add your Vercel URL to `CORS_ORIGINS` in `.env`:
```
CORS_ORIGINS=https://realflow.online,https://www.realflow.online,https://realflow-xxx.vercel.app
```
Then:
```powershell
docker compose restart backend
```

### Frontend loads but API calls fail
Vercel env var `REACT_APP_BACKEND_URL` must be **exactly** `https://api.realflow.online` (no trailing slash). Redeploy in Vercel after any change.

### Chromium / RUT jobs fail on first run
First job on a freshly-built container downloads ~300 MB of Chromium (1–2 min). Subsequent jobs are instant. Check: `logs.bat`.

---

# 💡 After deployment

- Change `ADMIN_PASSWORD` in the Settings page once you're logged in.
- Configure email (Resend / SMTP) in `.env` for forgot-password emails.
- Weekly backup:
  ```powershell
  docker compose exec mongo mongodump --archive=/data/db/backup-$(Get-Date -f yyyy-MM-dd).archive
  ```
- Monitor disk space — RUT job ZIPs and screenshots accumulate in the `rut_results` / `ff_results` Docker volumes.
