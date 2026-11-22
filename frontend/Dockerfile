FROM node:22-bookworm-slim AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG NEXT_PUBLIC_FIREBASE_API_KEY
ARG NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN
ARG NEXT_PUBLIC_FIREBASE_PROJECT_ID
ARG NEXT_PUBLIC_FIREBASE_APP_ID
ARG NEXT_PUBLIC_APP_ENV=preview

ENV NEXT_TELEMETRY_DISABLED=1

RUN set -eu; \
    if [ -z "${NEXT_PUBLIC_FIREBASE_API_KEY:-}" ]; then \
      echo "Missing required build argument: NEXT_PUBLIC_FIREBASE_API_KEY" >&2; exit 1; \
    fi; \
    if [ -z "${NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN:-}" ]; then \
      echo "Missing required build argument: NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN" >&2; exit 1; \
    fi; \
    if [ -z "${NEXT_PUBLIC_FIREBASE_PROJECT_ID:-}" ]; then \
      echo "Missing required build argument: NEXT_PUBLIC_FIREBASE_PROJECT_ID" >&2; exit 1; \
    fi; \
    if [ -z "${NEXT_PUBLIC_FIREBASE_APP_ID:-}" ]; then \
      echo "Missing required build argument: NEXT_PUBLIC_FIREBASE_APP_ID" >&2; exit 1; \
    fi; \
    if [ "${NEXT_PUBLIC_FIREBASE_PROJECT_ID}" != "prime-amulet-439718-e3" ]; then \
      echo "NEXT_PUBLIC_FIREBASE_PROJECT_ID must target the preview Firebase project" >&2; exit 1; \
    fi; \
    if [ "${NEXT_PUBLIC_APP_ENV}" != "preview" ]; then \
      echo "NEXT_PUBLIC_APP_ENV must be preview for this image" >&2; exit 1; \
    fi; \
    npm run build

RUN npm prune --omit=dev

FROM node:22-bookworm-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_APP_ENV=preview \
    HOSTNAME=0.0.0.0 \
    PORT=8080

COPY --from=build --chown=node:node /app/package.json /app/package-lock.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/.next ./.next
COPY --from=build --chown=node:node /app/next.config.ts ./next.config.ts

USER node

EXPOSE 8080

CMD ["sh", "-c", "exec npm start -- --hostname 0.0.0.0 --port ${PORT:-8080}"]
