# The pipeline image: this repo's code and the Night Bundle under one digest, so a restart fetches
# nothing from GitHub (#17 § Night bundle and image). Built by .github/workflows/image.yml.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.28 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so a code-only change reuses their layer.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project
# The project installs editable: cli.py finds the bundle and gates from the repo root.
COPY src/ src/
COPY data/ data/
COPY gates/ gates/
# The City's zeroed test files: the Mock Feed's shape (mock-feed, #37).
COPY tests/fixtures/feed/city-2026/ tests/fixtures/feed/city-2026/
RUN uv sync --locked --no-dev

ENV PATH="/app/.venv/bin:$PATH"
# No ENTRYPOINT: Fly's process command and App Platform's run_command each give the whole command.
CMD ["election-night", "--help"]
