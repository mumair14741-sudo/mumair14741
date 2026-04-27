# RealFlow — Localhost Docker Setup Guide

Ye guide aapko RealFlow ko apne **Windows / macOS / Linux** computer par Docker ke through chalane mein help karegi — ek bhi dependency manually install nahi karni parti.

---

## 1. Kya chahiye (Prerequisites)

| Requirement | Kyun chahiye | Install link |
|---|---|---|
| **Docker Desktop** (Windows/Mac) ya **Docker Engine + Compose v2** (Linux) | Containers chalane ke liye | <https://www.docker.com/products/docker-desktop/> |
| **Git** (optional) | Code pull karne ke liye | <https://git-scm.com/downloads> |
| **4 GB free RAM + 5 GB disk** | Playwright Chromium browser + MongoDB | — |

✔ Docker install ho chuka hai verify karne ke liye:
```bash
docker --version
docker compose version
```

---

## 2. Step-by-Step setup

### 2.1 — Codebase apne machine par laao

Option A (zip se):
```bash
unzip hasan-tackmaster--main.zip
cd hasan-tackmaster--main
```

Option B (git se):
```bash
git clone <your-repo-url>
cd hasan-tackmaster--main
```

### 2.2 — Environment variables set karo

```bash
cp .env.docker.example .env
```

Phir `.env` file khol ke in 4 cheezon ko edit karein (kam se kam):

```env
ADMIN_EMAIL=apna@email.com
ADMIN_PASSWORD=<apna-strong-password-yahan>
JWT_SECRET_KEY=<random-32-chars-yahan>
POSTBACK_TOKEN=<random-32-chars-yahan>
```

Tip — ek random secret banane ke liye:
```bash
openssl rand -hex 32
```

⚠ **Production mein dono `JWT_SECRET_KEY` aur `POSTBACK_TOKEN` unique hone chahiye.** Default chhodoge toh app chalega but security warnings milenge.

### 2.3 — Build + Run karein

```bash
docker compose up -d --build
```

Pehli baar build mein **~5–10 minutes** lagenge (Playwright Chromium download hota hai, ~300 MB). Aage se fast hoga.

Progress dekhne ke liye logs:
```bash
docker compose logs -f
```

### 2.4 — App khol ke test karein

Browser mein jao: **<http://localhost:3000>**

- Admin login ke liye: `admin` button → aap ne jo `ADMIN_EMAIL` / `ADMIN_PASSWORD` set kiya
- Regular user → `Register` tab se khud ko create karein, phir admin dashboard se activate kar lein

### 2.5 — Sab theek chal raha hai verify karein

1. **MongoDB up**: `docker compose ps` mein `realflow-mongo` = `healthy`
2. **Backend up**: `curl http://localhost:3000/health` → `{"status":"ok",...}`
3. **Frontend up**: browser mein `http://localhost:3000` khule
4. **Admin System Check**: login → Admin Dashboard → **"System Check"** tab. Sab green badges dikhne chahiye (sirf Email green nahi hoga agar SMTP/Resend set nahi kiya — normal hai).

---

## 3. Common commands

| Kaam | Command |
|---|---|
| Services start karein (background) | `docker compose up -d` |
| Stop karein | `docker compose down` |
| Logs dekho (live) | `docker compose logs -f` |
| Sirf backend ka log | `docker compose logs -f backend` |
| Container ke andar shell | `docker compose exec backend bash` |
| Rebuild (code change ke baad) | `docker compose up -d --build` |
| **Saara data mitao** (Mongo + screenshots) | `docker compose down -v` ⚠ |

---

## 4. Data kaha save hoti hai?

Docker named volumes mein — container delete karne par bhi **safe** rahti hai:

| Volume | Kya contain karta hai |
|---|---|
| `mongo_data` | MongoDB database (users, links, clicks, conversions, jobs) |
| `rut_results` | Real-User-Traffic screenshots + ZIPs |
| `ff_results` | Form-Filler screenshots + ZIPs |

Volumes list karne ke liye:
```bash
docker volume ls | grep realflow
```

⚠ `docker compose down -v` chalane par saara data delete ho jayega. Sirf `down` chalana safe hai.

---

## 5. Troubleshooting

### ❌ Port 3000 already in use

`.env` mein port badal lein:
```env
FRONTEND_PORT=4000
```
Phir `docker compose up -d` dobara.

### ❌ Backend "container unhealthy"

```bash
docker compose logs backend | tail -100
```
Common reasons:
- Mongo abhi ready nahi hua → 30-60 seconds ruk jao
- Playwright Chromium download fail → `docker compose build --no-cache backend`

### ❌ Real User Traffic "Job failed" but browser pe screenshots nahi

Playwright Chromium installed hai container mein confirm karne ke liye:
```bash
docker compose exec backend playwright --version
docker compose exec backend ls /ms-playwright
```

### ❌ "HTTP 404" on any API

nginx config check karein:
```bash
docker compose exec frontend cat /etc/nginx/conf.d/default.conf
```
`/api/` block me `proxy_pass http://backend:8001;` hona chahiye.

### ❌ Hot-reload chahiye (developer mode)

Is compose file mein frontend ek production build serve karta hai (fast + matches prod). Agar aap React ko live edit karna chahte hain toh:

```bash
# Backend containerized, frontend local dev-server
docker compose up -d mongo backend
cd frontend
yarn install
REACT_APP_BACKEND_URL=http://localhost:8001 yarn start
```

Lekin is case mein backend ko host se accessible banana hoga — `docker-compose.yml` mein `backend.ports` ko uncomment kar dein (`- "8001:8001"`).

---

## 6. Admin Features Quick Reference

| Feature | URL |
|---|---|
| User login / registration | `/` |
| Admin login | `/admin/login` |
| Admin dashboard (users, branding, API, **System Check**) | `/admin/dashboard` |
| Real-User-Traffic (Live Activity modal + screenshots) | login → side menu → Real User Traffic |
| Form Filler | login → side menu → Form Filler |
| Short-link: create in Links page, share `http://localhost:3000/api/r/{shortcode}` |

---

## 7. Upgrade path (code update ke baad)

```bash
git pull                                 # ya zip replace
docker compose up -d --build             # sirf changed services rebuild honge
```

Data safe hai — volumes touch nahi hote.

---

## 8. Production deployment notes

Localhost ke liye ye setup perfect hai. Internet par expose karna ho toh:

1. `.env` mein **strong secrets** — `JWT_SECRET_KEY`, `POSTBACK_TOKEN`, `ADMIN_PASSWORD`
2. Apne domain ka SSL chahiye → **Caddy** ya **Traefik** reverse proxy add kar dein (Let's Encrypt free SSL)
3. `CORS_ORIGINS=https://your-domain.com` (sirf apna domain)
4. MongoDB ke liye authenticated user banayen (default open-local-only safe hai, public exposure nahi karna)
5. Backup regular lein: `docker exec realflow-mongo mongodump --archive=/tmp/b.archive && docker cp realflow-mongo:/tmp/b.archive ./backup-$(date +%F).archive`

---

**Koi bhi step confuse ho ya error mile → `docker compose logs backend` ka output share karein, solve kar dete hain.**
