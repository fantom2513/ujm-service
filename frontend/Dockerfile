# syntax=docker/dockerfile:1
# Build context must be the repo root (scripts/build.mjs reaches up to root-level
# assets like "Референсы/" and "Пример ТЗ.docx"), not this frontend/ directory.

FROM nexus.sogaz.ru/node:24-bookworm-slim AS build
WORKDIR /app
RUN npm config set registry https://nexus.sogaz.ru/npm/
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nexus.sogaz.ru/nginx:1.27-alpine
COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ux-architecture/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
