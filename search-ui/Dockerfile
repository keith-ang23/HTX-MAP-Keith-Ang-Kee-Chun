FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY index.html vite.config.js search-config.js ./
COPY src ./src
RUN npm run build

FROM node:24-alpine AS runtime

ENV NODE_ENV=production \
    PORT=3000 \
    ELASTICSEARCH_HOST=http://es01:9200 \
    ELASTICSEARCH_INDEX=cv-transcriptions

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force

COPY server.js search-config.js ./
COPY --from=build /app/dist ./dist

USER node

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget --quiet --output-document=- http://127.0.0.1:3000/api/health > /dev/null || exit 1

CMD ["node", "server.js"]
