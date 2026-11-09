# syntax=docker/dockerfile:1.7

# ---------------------------------------------------------------- frontend (React + TS)
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
# Opcional: atrás de um proxy com inspeção TLS, passe a CA sem a gravar na imagem:
#   docker build --secret id=ca_bundle,src=/caminho/ca.crt .
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca_bundle; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
# outDir = ../src/cmlive/web/dist → /build/src/cmlive/web/dist
RUN npm run build

# ---------------------------------------------------------------- aplicação Python
FROM python:3.12-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then \
      export PIP_CERT=/run/secrets/ca_bundle SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir uv==0.5.11 && uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY --from=frontend /build/src/cmlive/web/dist ./src/cmlive/web/dist
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "cmlive"]
