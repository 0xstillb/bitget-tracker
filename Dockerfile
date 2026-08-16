FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Xvfb gives the headful auto-login Chromium a virtual display on the Pi.
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir --require-hashes -r requirements.lock \
    && playwright install chromium --with-deps

COPY . .

# Git on Windows does not track the exec bit; ensure the entrypoint runs.
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 10000

CMD ["/app/docker-entrypoint.sh"]
