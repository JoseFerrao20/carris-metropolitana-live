# syntax=docker/dockerfile:1.7
FROM python:3.12-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

# Opcional: atrás de um proxy com inspeção TLS, passe a CA sem a gravar na imagem:
#   docker build --secret id=ca_bundle,src=/caminho/ca.crt .
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then \
      export PIP_CERT=/run/secrets/ca_bundle SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir uv==0.5.11 && uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN --mount=type=secret,id=ca_bundle \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "cmlive"]
