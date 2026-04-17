# ── Stage 1: build the React (Vite) frontend ─────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /build

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Build-time env — values come from docker-compose build.args, which
# in turn reads them from .env at the monorepo root.
ARG VITE_API_BASE_URL
ARG VITE_CLERK_PUBLISHABLE_KEY
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_CLERK_PUBLISHABLE_KEY=${VITE_CLERK_PUBLISHABLE_KEY}

RUN npm run build

# ── Stage 2: nginx serving the SPA + reverse-proxying the API ────────────
FROM nginx:1.27-alpine

COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-build /build/dist /var/www/clause
COPY nginx/certs /etc/nginx/certs

EXPOSE 80 443

CMD ["nginx", "-g", "daemon off;"]
