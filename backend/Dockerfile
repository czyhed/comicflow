FROM python:3.12-bookworm

ARG UV_VERSION=0.11.25
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN python -m pip install --no-cache-dir "uv==$UV_VERSION" \
    && sed -i 's|http://deb.debian.org|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && uv export --frozen --no-dev --no-emit-project --output-file /tmp/comicflow-runtime.txt \
    && uv venv /app/.venv \
    && uv pip sync --python /app/.venv/bin/python --require-hashes --default-index "$PIP_INDEX_URL" /tmp/comicflow-runtime.txt \
    && rm /tmp/comicflow-runtime.txt
COPY backend/src ./backend/src
COPY skills/h3-prompt-writing ./skills/h3-prompt-writing
COPY skills/manju-laoli-drama ./skills/manju-laoli-drama
COPY skills/xiaoluo-visual-assets ./skills/xiaoluo-visual-assets
COPY backend/migrations ./backend/migrations
COPY alembic.ini ./
ENV PYTHONPATH=/app/backend/src
ENV PATH="/app/.venv/bin:$PATH"
