# Contexto de build: raiz do repositório (ver platform/docker-compose.yml).
# Estágio 1: build do portal (React + Vite). O dist é copiado para a imagem final.
FROM node:22-slim AS portal
WORKDIR /portal
COPY platform/portal/package.json platform/portal/package-lock.json ./
RUN npm ci
COPY platform/portal ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AOK_DATA_DIR=/data AOK_PORTAL_DIR=/app/portal-dist

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY platform/aok_platform ./platform/aok_platform
RUN pip install --no-cache-dir ".[platform]"
COPY --from=portal /portal/dist /app/portal-dist

RUN useradd --system --uid 10001 --no-create-home aok     && mkdir /data && chown aok /data
USER aok
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "aok_platform.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
