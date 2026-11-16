# Contexto de build: raiz do repositório (ver platform/docker-compose.yml).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 AOK_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY platform ./platform
RUN pip install --no-cache-dir ".[platform]"

RUN useradd --system --uid 10001 --no-create-home aok     && mkdir /data && chown aok /data
USER aok
VOLUME /data
EXPOSE 8000

CMD ["uvicorn", "aok_platform.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
