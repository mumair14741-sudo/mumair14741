# 🚀 RealFlow — Production Deployment Guide

**Setup**: Frontend on Vercel + Backend/MongoDB/Chromium on your home PC via Cloudflare Tunnel
**Domain**: `realflow.online`
**Time**: ~60–90 minutes

---

## 📋 Pre-requisites check

- [x] Domain **realflow.online** purchased ✅
- [ ] Home PC: Windows, 16 GB RAM, stable internet
- [ ] Cloudflare free account
- [ ] Vercel free account (sign in with GitHub)
- [ ] Docker Desktop for Windows
- [ ] Git for Windows

---

## Phase 1 — Cloudflare: Add domain (~15 min)

### 1.1 — Sign up at Cloudflare
https://dash.cloudflare.com/sign-up (free plan is enough).

### 1.2 — Add your domain
1. Dashboard → **Add a Site** → enter `realflow.online` → continue
2. Select **Free plan** → continue
3. Cloudflare will give you **2 nameservers** (e.g. `lars.ns.cloudflare.com`, `laura.ns.cloudflare.com`). **Copy them.**

### 1.3 — Change nameservers at your registrar (Namecheap / GoDaddy)
1. Log in to your registrar.
2. Go to your domain's DNS settings.
3. Change from default nameservers to **Custom DNS**.
4. Paste the 2 Cloudflare nameservers.
5. Save.

### 1.4 — Wait for propagation
- 10 min – 2 hrs (usually fast). Cloudflare will email "Site active".
- Status: Cloudflare dashboard must show `realflow.online` → **Active**.

Continue to Phase 2 while waiting.

---

## Phase 2 — Home PC: Install requirements (~20 min)

### 2.1 — Docker Desktop
1. Download: https://www.docker.com/products/docker-desktop/
2. Install → **restart PC**.
3. Open Docker Desktop.
4. Wait for bottom-left **"Engine running"** green dot.
5. Settings → General → ✅ **Start Docker Desktop when you log in**.
6. Settings → Resources → Advanced:
   - Memory: **at least 8 GB** (recommended 10 GB)
   - CPU: at least 4
   - Apply & restart.

### 2.2 — Git for Windows
https://git-scm.com/download/win → default settings → install.

### 2.3 — Cloudflared (Cloudflare tunnel client)
**Admin** PowerShell:
```powershell
winget install --id Cloudflare.cloudflared
```
Verify:
```powershell
cloudflared --version
```

---

## Phase 3 — Clone + configure backend (~10 min)

### 3.1 — Clone the repo
Normal PowerShell:
```powershell
cd $HOME\Desktop
git clone https://github.com/mumair14741-sudo/mumair14741.git realflow
cd realflow
```
> Replace URL with **your** GitHub repo URL if different.

### 3.2 — Create `.env` from template
```powershell
copy deployment\home-pc\env.template .env
notepad .env
```

In Notepad, fill in:
- **ADMIN_PASSWORD** → your strong password
- **JWT_SECRET_KEY** → random 32+ hex chars
- **POSTBACK_TOKEN** → random 32+ hex chars

To generate random secrets:
```powershell
# Generate JWT secret (run twice for JWT + POSTBACK)
-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Max 256) })
```
Copy each output into the `.env`.

Save & close Notepad.

### 3.3 — Start containers (first build takes 5-10 min)
```powershell
docker compose up -d --build
```

Wait for it to finish. Verify:
```powershell
curl http://localhost:8001/health
```
Expected:
```json
{"status":"ok","admin_email_configured":"admin@realflow.online","mongo_connected":true}
```

If you see this → ✅ backend running locally.

---

## Phase 4 — Cloudflare Tunnel setup (~15 min)

### 4.1 — Log in to Cloudflare from cloudflared
```powershell
cloudflared tunnel login
```
Browser opens → select **realflow.online** → Authorize.

### 4.2 — Create the tunnel
```powershell
cloudflared tunnel create realflow
```
Output includes a **Tunnel UUID** like `7a8b9c10-1234-5678-abcd-ef0123456789`.
**Copy this UUID.**

### 4.3 — Create DNS record for backend subdomain
```powershell
cloudflared tunnel route dns realflow api.realflow.online
```

### 4.4 — Create the config file
1. Copy template:
```powershell
mkdir $HOME\.cloudflared -ErrorAction SilentlyContinue
copy deployment\home-pc\cloudflared-config.yml.template $HOME\.cloudflared\config.yml
notepad $HOME\.cloudflared\config.yml
```
2. Edit the file:
   - Replace `<YourName>` with your Windows username
   - Replace `<TUNNEL-UUID>` with the UUID from step 4.2
3. Save & close.

### 4.5 — Test tunnel (foreground)
```powershell
cloudflared tunnel run realflow
```
You should see "Registered tunnel connection". Open another PowerShell and test:
```powershell
curl https://api.realflow.online/health
```
Expected: `{"status":"ok","mongo_connected":true,...}`

✅ If this works, stop the foreground tunnel with **Ctrl+C**.

### 4.6 — Install tunnel as a Windows service (auto-start on boot)
**Admin** PowerShell:
```powershell
cloudflared service install
```
Verify:
```powershell
Get-Service cloudflared
# Status: Running
```

Now the tunnel survives PC restarts.

---

## Phase 5 — Frontend on Vercel (~10 min)

### 5.1 — Make sure code is pushed to GitHub
Already done if you can see the repo on GitHub. If not, use **Save to GitHub** in Emergent.

### 5.2 — Sign up at Vercel
https://vercel.com/signup → **Continue with GitHub** → Authorize.

### 5.3 — Import project
1. Vercel Dashboard → **Add New → Project**.
2. Select your RealFlow GitHub repo → **Import**.
3. Configure:
   - **Project Name**: `realflow`
   - **Framework Preset**: **Create React App**
   - **Root Directory**: click **Edit** → select `frontend`
   - **Build Command**: `CI=false yarn build`
   - **Output Directory**: `build`
4. **Environment Variables** — expand section, add:
   ```
   Name:  REACT_APP_BACKEND_URL
   Value: https://api.realflow.online
   ```
5. Click **Deploy**.

2–3 min later → **Deployment successful**. Live at `https://realflow-xxx.vercel.app`.

### 5.4 — Attach custom domain
1. Vercel Project → **Settings → Domains**.
2. **Add** → enter `realflow.online` → click Add.
3. Vercel will show a DNS record to add:
   - **Type**: CNAME (or A record for apex)
   - **Name**: `@`
   - **Value**: `cname.vercel-dns.com`
4. Go to **Cloudflare dashboard** → DNS for `realflow.online` → **Add record**:
   - Same values as Vercel showed
   - **Proxy status**: 🟠 click to **DNS only** (gray cloud) — important, Vercel needs this OFF
5. Also add `www`:
   - CNAME → name `www` → value `cname.vercel-dns.com` → **DNS only**
6. Wait 1–2 min. Vercel shows "Valid configuration" → ✅

Test: `https://realflow.online` → loads RealFlow login page.

---

## Phase 6 — Final config (~5 min)

### 6.1 — Add Vercel URL to backend CORS
Edit `.env` on home PC:
```
CORS_ORIGINS=https://realflow.online,https://www.realflow.online,https://realflow-xxx.vercel.app
```
Restart backend:
```powershell
docker compose restart backend
```

### 6.2 — Add `status.bat` / `start.bat` / `stop.bat` shortcuts
In `realflow/deployment/home-pc/` folder, right-click each `.bat` → **Send to → Desktop (create shortcut)**.

### 6.3 — Startup-on-boot for Docker compose
Docker Desktop already auto-starts. But we also want compose to auto-`up`:
1. Press `Win + R` → type `shell:startup` → Enter.
2. Drag a shortcut of `start.bat` into this folder.

Now every time PC boots: Docker starts → `start.bat` runs → containers come up → cloudflared service (already a Windows service) runs. Everything online within 1 min of boot.

---

## ✅ Final Test Checklist

Run `status.bat` — all should be green:

| # | Check | Expected |
|---|-------|----------|
| 1 | `docker compose ps` | `realflow-backend` and `realflow-mongo` — up, healthy |
| 2 | `curl http://localhost:8001/health` | `{"status":"ok"}` |
| 3 | `Get-Service cloudflared` | Status: Running |
| 4 | `curl https://api.realflow.online/health` | `{"status":"ok"}` |
| 5 | Browser: `https://realflow.online` | RealFlow login page |
| 6 | Admin login (email + password from `.env`) | Admin dashboard loads |
| 7 | Create a tracking link → click it | Click tracked, redirects |
| 8 | Real-User-Traffic → run a small job | Conversions count ✅ |

---

## 🔄 Day-to-day operations

| Action | Command |
|--------|---------|
| Start everything | `start.bat` |
| Stop everything | `stop.bat` |
| Live backend logs | `logs.bat` |
| Status check | `status.bat` |
| Update from GitHub | `update.bat` |
| Admin dashboard | `https://realflow.online/admin` |

---

## 🆘 Troubleshooting

### "CORS error" in browser console
Add your Vercel URL to `CORS_ORIGINS` in `.env`, then:
```powershell
docker compose restart backend
```

### `https://api.realflow.online` returns 502
1. Is backend up? `curl http://localhost:8001/health`
2. Is tunnel running? `Get-Service cloudflared`
3. Restart tunnel: `Restart-Service cloudflared`

### Docker containers won't start
Check `.env` — missing values cause silent failures:
```powershell
docker compose logs backend
```

### Frontend shows but API calls fail
Vercel env var `REACT_APP_BACKEND_URL` must be **exactly** `https://api.realflow.online` (no trailing slash). Re-deploy in Vercel after changing.

### Chromium / RUT jobs fail
First job on a fresh pod downloads 300 MB Chromium (takes ~1 min). Subsequent jobs are instant. Check logs: `logs.bat`.

---

## 💡 After deployment

- **Change admin password** in Settings page
- **Add your email service** (Resend recommended) for forgot-password emails
- **Set up MongoDB weekly backup**:
  ```powershell
  docker compose exec mongo mongodump --archive=/data/db/backup-$(Get-Date -f yyyy-MM-dd).archive
  ```
- **Monitor disk space** — RUT screenshots and job ZIPs accumulate in `rut_results` / `ff_results` volumes
