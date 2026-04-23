#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#   TrackMaster — 1-Click Installer for Mac / Linux
#   Run: bash install-mac-linux.sh
#   Ya:  chmod +x install-mac-linux.sh && ./install-mac-linux.sh
# ═══════════════════════════════════════════════════════════════
set -e

# Colors
G="\033[0;32m"; R="\033[0;31m"; Y="\033[1;33m"; C="\033[0;36m"; N="\033[0m"

clear
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo -e "${C}  TrackMaster — 1-Click Installer${N}"
echo -e "${C}═══════════════════════════════════════════════════════════════${N}"
echo ""

# ── Step 1: Docker check ──────────────────────────────────────
echo -e "${C}[1/5]${N} Docker check kar raha hun..."
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${R}  ERROR: Docker install nahi hai!${N}"
    echo ""
    echo "  Mac:   https://www.docker.com/products/docker-desktop/"
    echo "  Linux: curl -fsSL https://get.docker.com | sudo sh"
    echo ""
    echo "  Install karne ke baad Docker start karein, phir ye"
    echo "  script dobara run karein."
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo -e "${R}  ERROR: Docker chal nahi raha!${N}"
    echo ""
    echo "  Mac/Windows: Docker Desktop open karein."
    echo "  Linux: sudo systemctl start docker"
    exit 1
fi
echo -e "      ${G}Docker ready hai.${N}"
echo ""

# ── Step 2: .env file banao ──────────────────────────────────
echo -e "${C}[2/5]${N} Environment file set kar raha hun..."
if [ ! -f ".env" ]; then
    if [ ! -f ".env.docker.example" ]; then
        echo -e "${R}  ERROR: .env.docker.example nahi mila! Project${N}"
        echo -e "${R}  folder mein script chalao (jahan docker-compose.yml hai).${N}"
        exit 1
    fi
    cp .env.docker.example .env

    # Random secrets
    JWT_RND=$(openssl rand -hex 32 2>/dev/null || head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)
    PB_RND=$(openssl rand -hex 32 2>/dev/null || head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 48)

    # Platform-safe sed (Mac ke liye -i '' chahiye)
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_RND|" .env
        sed -i '' "s|POSTBACK_TOKEN=.*|POSTBACK_TOKEN=$PB_RND|" .env
    else
        sed -i "s|JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$JWT_RND|" .env
        sed -i "s|POSTBACK_TOKEN=.*|POSTBACK_TOKEN=$PB_RND|" .env
    fi

    echo -e "      ${G}.env file ban gayi, random secrets set ho gaye.${N}"
    echo ""
    echo -e "${Y}  NOTE: Default admin login:${N}"
    echo "    Email:    admin@trackmaster.local"
    echo "    Password: admin123"
    echo ""
    echo -e "${Y}  Security ke liye .env file mein ADMIN_EMAIL aur${N}"
    echo -e "${Y}  ADMIN_PASSWORD change kar sakte hain.${N}"
    echo ""
else
    echo -e "      ${G}.env file pehle se hai — use kar raha hun.${N}"
fi
echo ""

# ── Step 3: Containers build + start ─────────────────────────
echo -e "${C}[3/5]${N} App build + start kar raha hun..."
echo -e "${Y}      Pehli baar ~5-10 minute lag sakte hain (Chromium download).${N}"
echo -e "${Y}      Sabar rakhein, screen par text chalta rahega — normal hai.${N}"
echo ""
docker compose up -d --build
echo ""

# ── Step 4: Health wait ──────────────────────────────────────
echo -e "${C}[4/5]${N} Services ke ready hone ka wait kar raha hun..."
for i in $(seq 1 40); do
    if curl -fsS http://localhost:3000/health >/dev/null 2>&1; then
        echo -e "      ${G}App ready hai!${N}"
        break
    fi
    echo "      Ruk jao... ($i/40)"
    sleep 3
    if [ "$i" -eq 40 ]; then
        echo -e "${Y}  WARNING: App abhi tak ready nahi hua. 'docker compose${N}"
        echo -e "${Y}  logs -f' chala ke check karein.${N}"
        exit 1
    fi
done
echo ""

# ── Step 5: Browser open ─────────────────────────────────────
echo -e "${C}[5/5]${N} Browser open kar raha hun..."
URL="http://localhost:3000"
if [[ "$OSTYPE" == "darwin"* ]]; then
    open "$URL" 2>/dev/null || true
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$URL" 2>/dev/null || true
else
    echo "  Manual: browser mein khol do → $URL"
fi
echo ""

echo -e "${G}═══════════════════════════════════════════════════════════════${N}"
echo -e "${G}  TrackMaster chal raha hai!${N}"
echo -e "${G}═══════════════════════════════════════════════════════════════${N}"
echo ""
echo "  URL:             $URL"
echo "  Admin details:   .env file mein dekho"
echo ""
echo "  Useful commands:"
echo "    Stop app:      docker compose down"
echo "    Start dobara:  docker compose up -d"
echo "    Logs dekho:    docker compose logs -f"
echo "    Status:        docker compose ps"
echo ""
echo "  Koi problem ho to START-HERE.txt ya DOCKER_SETUP.md padhein."
echo ""
