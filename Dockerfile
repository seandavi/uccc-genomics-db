# syntax=docker/dockerfile:1
FROM oven/bun:1.4.2 AS web
WORKDIR /web
COPY web/package.json web/bun.lock ./
RUN bun install --frozen-lockfile
COPY web/ ./
RUN bun run build                        # -> /web/dist (index.html, discover.html, requests.html, assets/)

FROM ghcr.io/astral-sh/uv:0.11.21-python3.12-trixie-slim AS app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
COPY mcp/pyproject.toml mcp/
COPY src/ src/
COPY mcp/src/ mcp/src/
RUN uv sync --locked --no-dev --no-editable --package uccc-genomics-mcp

FROM python:3.12-slim-trixie
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=app /app/.venv /app/.venv
COPY --from=web /web/dist /app/web/dist
# The build context keeps host modes (umask 027 makes new files 640) and the container runs as the data
# owner's uid, not root: make the static files world-readable.
RUN chmod -R a+rX /app/web/dist
ENV PATH=/app/.venv/bin:$PATH HOME=/tmp PYTHONUNBUFFERED=1 DATA=/data
WORKDIR /app
USER 10001
EXPOSE 8092
ENTRYPOINT ["genomics-app"]
CMD ["--auth", "authentik", "--host", "0.0.0.0", "--port", "8092", "--static", "/app/web/dist"]
