FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # The web API may only read and write these folders.
    CLIPPER_ROOTS=/footage:/out \
    # The AI director talks to Ollama (or pass an OpenAI-compatible server URL
    # in the UI). host.docker.internal reaches Ollama on the Docker host.
    CLIPPER_OLLAMA_URL=http://host.docker.internal:11434

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

# The server binds 0.0.0.0 inside the container so Docker can forward the port.
# Publish it to the host's loopback only:
#   docker run -p 127.0.0.1:8765:8765 -v D:\Videos:/footage:ro -v D:\Clips:/out clipper
# Requests with any Host other than localhost/127.0.0.1 are refused; to allow a
# LAN name deliberately, set CLIPPER_ALLOWED_HOSTS (the UI has no login).
ENTRYPOINT ["clipper"]
CMD ["ui", "--host", "0.0.0.0", "--port", "8765", "--no-browser"]
