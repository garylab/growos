# Stage 1: build the React app
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
COPY . .
RUN npm run build

# Stage 2: Caddy serves the static build and proxies /api
FROM caddy:2.9-alpine
COPY --from=build /app/dist /srv
COPY --from=build /app/Caddyfile /etc/caddy/Caddyfile
EXPOSE 8888
