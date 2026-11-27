from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_installer_readme_describes_the_bundled_runtime() -> None:
    text = (ROOT / "packaging" / "PORTABLE_DESKTOP_README.txt").read_text(
        encoding="utf-8"
    )
    assert "Clipper __CLIPPER_VERSION__ - Windows x64" in text
    assert "llama.cpp" in text
    assert "Ollama is not required" in text
    assert "Install Ollama" not in text
    assert "Connect local server..." in text
    assert "551.61" in text
    assert "CPU-only" in text
    assert "749,426,307" in text
    assert "2,049,471,328" in text
    assert "6,121,827,584" in text
    assert "7,556,499,296" in text


def test_public_installation_docs_do_not_require_ollama() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    website = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    models = (ROOT / "docs" / "AI_MODELS.md").read_text(encoding="utf-8")
    for text in (readme, website, models):
        assert "Install Ollama" not in text
        assert "llama.cpp" in text
        normalized = text.replace("**", "").lower()
        assert (
            "ollama is optional" in normalized
            or "ollama is not required" in normalized
        )
    assert "551.61" in readme
    assert "749 MB" in website
    assert "2,049,471,328" in models


def test_build_pipeline_substitutes_and_checks_the_readme_version() -> None:
    desktop = (ROOT / "packaging" / "build_desktop.ps1").read_text(
        encoding="utf-8"
    )
    installer = (ROOT / "packaging" / "build_installer.ps1").read_text(
        encoding="utf-8"
    )
    assert "__CLIPPER_VERSION__" in desktop
    assert "README.txt" in desktop
    assert '"README.txt"' in installer
    assert "README.txt does not contain the build version" in installer
    assert "__CLIPPER_VERSION__" in installer
