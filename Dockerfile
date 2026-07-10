# syntax=docker/dockerfile:1
# Backend only — static frontend is built and served by frontend/Dockerfile's
# nginx container in the cx_net topology; this image never serves frontend/dist.

FROM nexus.sogaz.ru/node:24-bookworm-slim AS deps
WORKDIR /app
RUN npm config set registry https://nexus.sogaz.ru/npm/ \
    && npm install -g pnpm \
    && pnpm config set registry https://nexus.sogaz.ru/npm/
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --prod --frozen-lockfile

FROM nexus.sogaz.ru/node:24-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production
RUN groupadd --system --gid 1001 app && useradd --system --uid 1001 --gid app app

COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
COPY backend ./backend
COPY shared ./shared

RUN chown -R app:app /app
USER app

EXPOSE 4173

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.APP_PORT||'4173')+'/api/health').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "backend/src/server/index.ts"]
