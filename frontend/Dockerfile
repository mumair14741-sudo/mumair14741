# ===============================================================
#  TrackMaster - Frontend Dockerfile (multi-stage)
#  Stage 1: build React app with yarn
#  Stage 2: serve with nginx + proxy /api to backend
# ===============================================================

# ---- Stage 1: build ----
FROM node:20-alpine AS builder

ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL \
    DISABLE_ESLINT_PLUGIN=true \
    GENERATE_SOURCEMAP=false \
    CI=false

WORKDIR /app

# Copy package files. yarn.lock is optional — use wildcard so the
# COPY step works whether the lockfile exists or not.
COPY package.json package-lock.json* yarn.lock* ./

# Use yarn.lock when present (frozen), else install fresh (will
# generate yarn.lock inside the image).
RUN if [ -f yarn.lock ]; then \
        yarn install --frozen-lockfile --network-timeout 600000; \
    else \
        yarn install --network-timeout 600000; \
    fi

# Copy sources and build
COPY . .
RUN yarn build

# ---- Stage 2: nginx ----
FROM nginx:1.27-alpine

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
