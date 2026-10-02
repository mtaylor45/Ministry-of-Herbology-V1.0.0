# SvelteKit PWA, built then served by the Node adapter. The deployment.
FROM node:22-slim AS build
WORKDIR /srv/web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

FROM node:22-slim AS runtime
ENV NODE_ENV=production
WORKDIR /srv/web
RUN adduser --system --group --no-create-home herbology
COPY --from=build /srv/web/build ./build
COPY --from=build /srv/web/package.json ./
COPY --from=build /srv/web/node_modules ./node_modules
USER herbology
EXPOSE 3000

# No secrets here: the web app talks to the API over the overlay network and
# holds no credential of its own, so it needs no entrypoint shim.
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "build/index.js"]
