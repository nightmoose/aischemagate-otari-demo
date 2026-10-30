from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".pytest_cache", "__pycache__", "developers_wilding.egg-info"}
BANNED = "Contract" + "Gate"


def _files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if path.suffix in {".pyc"}:
            continue
        yield path


def test_public_tree_uses_aischemagate_name():
    offenders = []
    for path in _files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if BANNED in text or BANNED.lower() in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_readme_maps_features_and_models():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for needle in (
        "alibaba/qwen3-235b-a22b-instruct-2507",
        "mistralai/mistral-small-3.2-24b-instruct-2506",
        "openai/gpt-oss-120b",
        "https://otari.ai/api/v1",
        "```mermaid",
        "OTARI_API_KEY",
        "pass",
        "repair",
        "quarantine",
        "AISchemaGate",
        "unverified",
    ):
        assert needle in readme
    assert (ROOT / "docs" / "HACKATHON.md").is_file()
    assert (ROOT / "docs" / "DEMO_SCRIPT.md").is_file()
    hackathon = (ROOT / "docs" / "HACKATHON.md").read_text(encoding="utf-8")
    assert "alibaba/qwen3-235b-a22b-instruct-2507" in hackathon
    assert "mistralai/mistral-small-3.2-24b-instruct-2506" in hackathon
