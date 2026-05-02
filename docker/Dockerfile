# Pipeline runtime image.
#
# Selenium is intentionally NOT installed here -- the default sources are
# plain HTTP and the pool is opt-in. Users who add JS-rendered sources
# should layer a derived image with chromium + chromedriver pre-installed.

FROM python:3.12-slim

WORKDIR /app

# Build deps for any wheels that need compiling (asyncpg ships wheels for
# 3.12 already; this is a small belt-and-braces).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.pipeline"]
