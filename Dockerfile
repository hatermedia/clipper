FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg passwd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install .

RUN groupadd --gid 1000 clipper \
    && useradd --create-home --uid 1000 --gid clipper clipper \
    && mkdir -p /footage /out \
    && chown -R clipper:clipper /app /out
USER clipper

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"

ENTRYPOINT ["clipper"]
CMD ["ui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
