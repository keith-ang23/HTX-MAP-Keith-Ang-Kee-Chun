# Build the browser assets with the complete development toolchain.
FROM node:24-alpine AS build

WORKDIR /app

# Install from the lockfile before copying source to maximize layer reuse.
COPY package.json package-lock.json ./
RUN npm ci

# Vite needs the HTML entry point, shared query config, and React source.
COPY index.html vite.config.js search-config.js ./
COPY src ./src
RUN npm run build

# Use a separate runtime stage so compilers and dev dependencies are excluded.
FROM node:24-alpine AS runtime

# Defaults are overridden by Compose when the stack uses Docker DNS.
ENV NODE_ENV=production \
    PORT=3000 \
    ELASTICSEARCH_HOST=http://es01:9200 \
    ELASTICSEARCH_INDEX=cv-transcriptions

WORKDIR /app

# Install only Express and other production dependencies.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev \
    && npm cache clean --force

# Copy the proxy code and compiled static site into the runtime image.
COPY server.js search-config.js ./
COPY --from=build /app/dist ./dist

# The standard Node image user avoids running the web process as root.
USER node

EXPOSE 3000

# Search UI is healthy only when its proxy can also reach Elasticsearch.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget --quiet --output-document=- http://127.0.0.1:3000/api/health > /dev/null || exit 1

# Express serves both the /api proxy and the production React bundle.
CMD ["node", "server.js"]
