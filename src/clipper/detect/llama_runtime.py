"""Bundled llama.cpp runtime and local model downloads.

Clipper used to depend on a separately installed Ollama daemon. This module
keeps the same local-only guarantees with a much smaller footprint: a pinned
llama.cpp server, GGUF model files, and no system-wide install.

The runtime is optional and downloaded on demand. Models are stored under
%LOCALAPPDATA%\\Clipper so they survive app upgrades and are shared by every
install of the same user.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

RUNTIME_VERSION = "b12776"
RUNTIME_DIR_NAME = f"llama-{RUNTIME_VERSION}"
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
ProgressFn = Callable[[int, int], None]
CancelledFn = Callable[[], bool]


@dataclass(frozen=True)
class RuntimeFile:
    name: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelFile:
    role: str
    filename: str
    url: str
    sha256: str
    size: int


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    tier: str
    description: str
    params: str
    vram_gb: float
    files: tuple[ModelFile, ...]
    context: int = 8192
    server_args: tuple[str, ...] = ()
    vision: bool = True
    audio: bool = True
    engine: str = "llamacpp"
    license: str = ""
    experimental: bool = False


RUNTIME_FILES = (
    RuntimeFile(
        name="llama-cuda.zip",
        url=(
            "https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{RUNTIME_VERSION}/llama-{RUNTIME_VERSION}-bin-win-cuda-12.4-x64.zip"
        ),
        sha256="661637CFC6D75F63FD8BC9E837C70A2221A62EB1C91DEA91088681AB878C238E",
        size=357_982_680,
    ),
    RuntimeFile(
        name="cudart.zip",
        url=(
            "https://github.com/ggml-org/llama.cpp/releases/download/"
            f"{RUNTIME_VERSION}/cudart-llama-bin-win-cuda-12.4-x64.zip"
        ),
        sha256="8C79A9B226DE4B3CACFD1F83D24F962D0773BE79F1E7B75C6AF4DED7E32AE1D6",
        size=391_443_627,
    ),
)

LFM3_OMNI_2B = ModelSpec(
    id="lfm3-omni-2b",
    name="LFM3-Omni-2B",
    tier="Lite",
    description=(
        "Fastest option. Watches the HUD and hears laughter and tone, but is "
        "less accurate on complex scenes. Use Standard for better clips."
    ),
    params="2B",
    vram_gb=4.0,
    context=8192,
    files=(
        ModelFile(
            role="model",
            filename="model.gguf",
            url=(
                "https://registry.ollama.ai/v2/library/lfm3-omni/blobs/"
                "sha256-9f8d30e9d4fd7a9349d586e077988229b3ca0a0e4ad730897563d1eccc9893e2"
            ),
            sha256="9f8d30e9d4fd7a9349d586e077988229b3ca0a0e4ad730897563d1eccc9893e2",
            size=1_099_630_080,
        ),
        ModelFile(
            role="mmproj",
            filename="mmproj.gguf",
            url=(
                "https://registry.ollama.ai/v2/library/lfm3-omni/blobs/"
                "sha256-92907148363ed89f67c46a09264bf2635d4069a66ced26db75abd63370eddb7e"
            ),
            sha256="92907148363ed89f67c46a09264bf2635d4069a66ced26db75abd63370eddb7e",
            size=949_841_248,
        ),
    ),
    license="LFM Open License v1.0",
)

MINICPM_O_4_5 = ModelSpec(
    id="minicpm-o-4.5",
    name="MiniCPM-o 4.5",
    tier="Standard",
    description=(
        "9B vision model with stronger scene and HUD understanding. Pairs with "
        "LFM3-Omni for audio; best on a 10-12 GB GPU."
    ),
    params="9B",
    vram_gb=8.5,
    context=4096,
    audio=False,
    files=(
        ModelFile(
            role="model",
            filename="model.gguf",
            url=(
                "https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf/resolve/main/"
                "MiniCPM-o-4_5-Q4_K_M.gguf"
            ),
            sha256="1237A97EE081B8ABEBC47AA7DAD565701E8F5F904CDC92F6723AC4281BBC0932",
            size=5_026_714_400,
        ),
        ModelFile(
            role="vision",
            filename="vision.gguf",
            url=(
                "https://huggingface.co/openbmb/MiniCPM-o-4_5-gguf/resolve/main/"
                "vision/MiniCPM-o-4_5-vision-F16.gguf"
            ),
            sha256="1453678CC4E4FE18DE241952962E234F265CB8DDA780773526103AB8BA82F421",
            size=1_095_113_184,
        ),
    ),
    engine="llamacpp",
    license="Apache-2.0",
    experimental=True,
)

GEMMA_4_12B = ModelSpec(
    id="gemma4-12b",
    name="Gemma 4 12B",
    tier="Google",
    description=(
        "Google 12B vision model with strong reasoning and HUD reading. Pairs "
        "with LFM3-Omni for audio; best on a 12 GB GPU."
    ),
    params="12B",
    vram_gb=10.5,
    context=4096,
    audio=False,
    files=(
        ModelFile(
            role="model",
            filename="model.gguf",
            url=(
                "https://registry.ollama.ai/v2/library/gemma4/blobs/"
                "sha256-bb722270d54346adc198f213851dbe0207e87c3ecf2a0aff4d92262726215391"
            ),
            sha256="bb722270d54346adc198f213851dbe0207e87c3ecf2a0aff4d92262726215391",
            size=7_381_383_680,
        ),
        ModelFile(
            role="mmproj",
            filename="mmproj.gguf",
            url=(
                "https://registry.ollama.ai/v2/library/gemma4/blobs/"
                "sha256-0cb0cd0a5c499d92942caa22fe5abb98f6e8874868d590e2b094ece4ac8e6d28"
            ),
            sha256="0cb0cd0a5c499d92942caa22fe5abb98f6e8874868d590e2b094ece4ac8e6d28",
            size=175_115_616,
        ),
    ),
    engine="llamacpp",
    license="Gemma Terms of Use",
    experimental=True,
)

VIDEO_SALMONN_2_PRO = ModelSpec(
    id="video-salmonn-2-pro",
    name="Video-SALMONN 2 Pro",
    tier="Alternative",
    description=(
        "Research audio-visual model. Requires a PyTorch/vLLM environment and "
        "is not part of the bundled runtime yet."
    ),
    params="8B / 32B",
    vram_gb=16.0,
    files=(),
    engine="external",
    license="Apache-2.0",
    experimental=True,
)

MODELS: tuple[ModelSpec, ...] = (
    LFM3_OMNI_2B,
    MINICPM_O_4_5,
    GEMMA_4_12B,
    VIDEO_SALMONN_2_PRO,
)
MODEL_BY_ID = {spec.id: spec for spec in MODELS}
MODEL_ALIASES = {
    "lfm3-omni": "lfm3-omni-2b",
    "lfm3-omni:latest": "lfm3-omni-2b",
    "minicpm-o-4_5": "minicpm-o-4.5",
    "gemma4:12b": "gemma4-12b",
}


def model_spec(model_id: str) -> ModelSpec | None:
    key = model_id.strip().lower()
    return MODEL_BY_ID.get(MODEL_ALIASES.get(key, key))


def runtime_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "Clipper" / "ai-runtime" / RUNTIME_DIR_NAME


def runtime_server() -> Path:
    return runtime_root() / "llama-server.exe"


def runtime_ready() -> bool:
    server = runtime_server()
    return server.is_file() and (runtime_root() / ".ready").is_file()


def model_root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache")
    return base / "Clipper" / "ai-models"


def model_dir(spec: ModelSpec) -> Path:
    return model_root() / spec.id


def model_paths(spec: ModelSpec) -> dict[str, Path]:
    return {
        item.role: model_dir(spec) / item.filename for item in spec.files
    }


def model_ready(spec: ModelSpec) -> bool:
    if spec.engine == "external" or not spec.files:
        return False
    marker = model_dir(spec) / ".ready"
    if not marker.is_file():
        return False
    for item in spec.files:
        path = model_dir(spec) / item.filename
        if not path.is_file() or path.stat().st_size != item.size:
            return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(
    url: str,
    target: Path,
    *,
    expected_sha256: str = "",
    expected_size: int = 0,
    progress: ProgressFn | None = None,
    cancelled: CancelledFn | None = None,
    timeout: float = 60.0,
) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    if target.is_file() and (
        not expected_size or target.stat().st_size == expected_size
    ):
        if not expected_sha256 or _sha256(target).lower() == expected_sha256.lower():
            return target
        target.unlink(missing_ok=True)
    attempts = 0
    while attempts < 3:
        attempts += 1
        start = partial.stat().st_size if partial.is_file() else 0
        headers = {"User-Agent": "Clipper/1.0"}
        if start:
            headers["Range"] = f"bytes={start}-"
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status = getattr(response, "status", 200)
                if start and status != 206:
                    start = 0
                    partial.unlink(missing_ok=True)
                total = expected_size or 0
                length = response.headers.get("Content-Length")
                if length and not total:
                    total = int(length) + start
                if progress:
                    progress(start, total)
                with partial.open("ab" if start else "wb") as handle:
                    downloaded = start
                    while True:
                        if cancelled and cancelled():
                            raise RuntimeError("cancelled")
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        handle.write(block)
                        downloaded += len(block)
                        if progress:
                            progress(downloaded, total)
            if expected_size and partial.stat().st_size != expected_size:
                raise RuntimeError(
                    f"Downloaded {partial.stat().st_size} bytes, expected {expected_size}"
                )
            if expected_sha256:
                actual = _sha256(partial)
                if actual.lower() != expected_sha256.lower():
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("Download checksum did not match")
            partial.replace(target)
            return target
        except RuntimeError:
            raise
        except Exception as exc:
            if attempts >= 3:
                raise RuntimeError(f"Download failed: {exc}") from exc
            time.sleep(1.0)
    raise RuntimeError("Download failed")


def install_runtime(
    progress: ProgressFn | None = None,
    cancelled: CancelledFn | None = None,
) -> Path:
    if runtime_ready():
        return runtime_server()
    root = runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="clipper_llama_") as raw:
        temp = Path(raw)
        for item in RUNTIME_FILES:
            archive = _download(
                item.url,
                temp / item.name,
                expected_sha256=item.sha256,
                expected_size=item.size,
                progress=progress,
                cancelled=cancelled,
            )
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(temp / "unpacked")
        for entry in (temp / "unpacked").iterdir():
            if entry.is_dir():
                for child in entry.rglob("*"):
                    if child.is_file():
                        destination = root / child.relative_to(entry)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        child.replace(destination)
            elif entry.is_file():
                entry.replace(root / entry.name)
    server = runtime_server()
    if not server.is_file():
        raise RuntimeError("The llama.cpp runtime did not contain llama-server.exe")
    (root / ".ready").write_text("ok", encoding="utf-8")
    return server


def install_model(
    spec: ModelSpec,
    progress: ProgressFn | None = None,
    cancelled: CancelledFn | None = None,
) -> Path:
    if spec.engine == "external" or not spec.files:
        raise RuntimeError(f"{spec.name} is not available for the bundled runtime")
    target_dir = model_dir(spec)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Remove a stale marker before touching files so an interrupted upgrade
    # can never be mistaken for a complete model.
    (target_dir / ".ready").unlink(missing_ok=True)
    for item in spec.files:
        _download(
            item.url,
            target_dir / item.filename,
            expected_sha256=item.sha256,
            expected_size=item.size,
            progress=progress,
            cancelled=cancelled,
        )
    (target_dir / ".ready").write_text("ok", encoding="utf-8")
    return target_dir


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _health(url: str, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=2.0) as response:
                if response.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


@dataclass
class LlamaServer:
    spec: ModelSpec
    port: int
    process: subprocess.Popen
    log_path: Path
    started: float = field(default_factory=time.monotonic)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def alive(self) -> bool:
        return self.process.poll() is None

    def stop(self) -> None:
        if self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=8)
            except Exception:
                try:
                    self.process.kill()
                    self.process.wait(timeout=4)
                except Exception:
                    pass

    def log_tail(self, limit: int = 1200) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-limit:]


_SERVERS: dict[str, LlamaServer] = {}


def active_server(model_id: str | None = None) -> LlamaServer | None:
    if model_id is not None:
        server = _SERVERS.get(model_id)
        if server is not None and not server.alive():
            _SERVERS.pop(model_id, None)
            return None
        return server
    for key, server in list(_SERVERS.items()):
        if not server.alive():
            _SERVERS.pop(key, None)
    return next(iter(_SERVERS.values()), None)


def stop_server(model_id: str | None = None) -> None:
    if model_id is not None:
        server = _SERVERS.pop(model_id, None)
        if server is not None:
            server.stop()
        return
    for server in list(_SERVERS.values()):
        server.stop()
    _SERVERS.clear()


def start_server(
    spec: ModelSpec,
    *,
    timeout: float = 120.0,
) -> LlamaServer:
    current = active_server(spec.id)
    if current is not None:
        return current
    if spec.engine != "llamacpp":
        raise RuntimeError(
            f"{spec.name} needs its experimental engine, which is not installed yet"
        )
    if not runtime_ready():
        raise RuntimeError("The local llama.cpp runtime is not installed")
    if not model_ready(spec):
        raise RuntimeError(f"{spec.name} is not downloaded")
    server = runtime_server()
    paths = model_paths(spec)
    model = paths.get("model")
    if model is None:
        raise RuntimeError(f"{spec.name} has no language model file")
    port = _free_port()
    log_path = model_dir(spec) / "server.log"
    command = [
        str(server),
        "-m",
        str(model),
        "-c",
        str(spec.context),
        # One slot. The server default is four, which multiplies the KV cache
        # and can push a 9B model into system RAM on a 10 GB card.
        "-np",
        "1",
        "-ngl",
        "99",
        "--jinja",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    mmproj = paths.get("mmproj") or paths.get("vision")
    if mmproj is not None and mmproj.is_file():
        command.extend(["--mmproj", str(mmproj)])
    command.extend(spec.server_args)
    log = log_path.open("w", encoding="utf-8", errors="replace")
    process = subprocess.Popen(
        command,
        stdout=log,
        stderr=subprocess.STDOUT,
        creationflags=_NO_WINDOW,
    )
    server_state = LlamaServer(
        spec=spec,
        port=port,
        process=process,
        log_path=log_path,
    )
    if not _health(server_state.base_url, timeout=timeout):
        detail = server_state.log_tail()
        server_state.stop()
        raise RuntimeError(
            f"{spec.name} did not start."
            + (f" {detail}" if detail else "")
        )
    _SERVERS[spec.id] = server_state
    return server_state


def openai_chat(
    server: LlamaServer,
    prompt: str,
    *,
    images: Iterable[bytes] = (),
    audio: bytes | None = None,
    max_tokens: int = 320,
    timeout: float = 300.0,
    json_mode: bool = True,
) -> str:
    content: list[dict] = []
    for image in images:
        encoded = __import__("base64").b64encode(image).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
            }
        )
    if audio is not None:
        encoded = __import__("base64").b64encode(audio).decode("ascii")
        content.append(
            {
                "type": "input_audio",
                "input_audio": {"data": encoded, "format": "wav"},
            }
        )
    content.append({"type": "text", "text": prompt})
    payload = {
        "model": server.spec.id,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0.0,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if "gemma4" in server.spec.id:
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    request = urllib.request.Request(
        server.base_url + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(600).decode("utf-8", errors="replace")
        if "response_format" in body and json_mode:
            return openai_chat(
                server,
                prompt,
                images=images,
                audio=audio,
                max_tokens=max_tokens,
                timeout=timeout,
                json_mode=False,
            )
        raise RuntimeError(f"llama.cpp HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"llama.cpp request failed: {exc}") from exc
    try:
        message = data["choices"][0]["message"]
        text = str(message.get("content") or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("llama.cpp returned an unexpected response") from exc
    if not text.strip():
        raise RuntimeError("The local model returned an empty response")
    return text
