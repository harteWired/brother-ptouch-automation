FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi8 \
    && rm -rf /var/lib/apt/lists/*

# Build context is the REPO ROOT (not this folder) — the workflow invokes
#   docker/build-push-action with context: . and file: containers/<name>/Dockerfile
# so the image stays byte-identical to the commit that triggered the build,
# with no dependence on a pinned remote commit or network access to GitHub.
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# Templates, fonts, and bundled icons all ship inside the package as
# package-data (see pyproject.toml); tests/docs/skill stay out of the image.
# git is kept for `lp icons install-*` (clones the full icon repos).
RUN pip install --no-cache-dir ".[service,barcode,icons]"

RUN groupadd --system --gid 65532 labelprinter \
    && useradd --system --uid 65532 --gid 65532 --shell /bin/false --home /home/labelprinter --create-home labelprinter \
    && mkdir -p /home/labelprinter/.config/label-printer \
    && chown -R labelprinter:labelprinter /home/labelprinter

USER labelprinter
WORKDIR /home/labelprinter
EXPOSE 8765
ENTRYPOINT ["lp", "serve", "--host", "0.0.0.0", "--port", "8765"]
