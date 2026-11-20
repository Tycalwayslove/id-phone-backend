FROM node:22-bookworm-slim AS build

RUN npm install --global pnpm@10
WORKDIR /build/admin-web
COPY admin-web/package.json admin-web/pnpm-lock.yaml admin-web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

COPY docs/api/openapi.json /build/docs/api/openapi.json
COPY admin-web/ ./
RUN pnpm run gen:api && pnpm run typecheck && pnpm run build

FROM nginx:stable
RUN rm -f /etc/nginx/conf.d/default.conf
COPY deploy/nginx/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx/site.conf.template /etc/nginx/templates/site.conf.template
COPY --from=build /build/admin-web/dist/ /usr/share/nginx/html/
