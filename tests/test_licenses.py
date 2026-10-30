"""Direct and transitive licenses stay inside the demo's allow list.

Dual licenses are accepted when one side is MIT, ISC, BSD, or 0BSD.
Two transitive packages are exceptions forced by ``aischemagate``:
``certifi`` (MPL-2.0) and ``typing_extensions`` (PSF-2.0).
"""

from __future__ import annotations

import importlib.metadata as metadata
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement

ALLOWED = {"MIT", "ISC", "BSD", "BSD-2-Clause", "BSD-3-Clause", "0BSD"}
# Pulled in by aischemagate -> httpx/anyio. Not added by this demo.
EXCEPTIONS = {
    "certifi": "MPL-2.0",
    "typing_extensions": "PSF-2.0",
}


def _direct_names() -> list[str]:
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    names = []
    for spec in project["project"]["dependencies"] + project["project"]["optional-dependencies"]["dev"]:
        names.append(spec.split("==")[0].split("[")[0].strip())
    return names


def _license_tokens(dist: metadata.Distribution) -> set[str]:
    tokens = set()
    expression = dist.metadata.get("License-Expression") or ""
    license_text = dist.metadata.get("License") or ""
    blob = f"{expression} {license_text}"
    for classifier in dist.metadata.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            blob += " " + classifier
    normalized = blob.replace("-", " ").upper()
    if "MIT" in normalized:
        tokens.add("MIT")
    if "ISC" in normalized:
        tokens.add("ISC")
    if "0BSD" in blob.upper() or "BSD ZERO" in normalized:
        tokens.add("0BSD")
    if "BSD" in normalized:
        tokens.add("BSD")
    if "MPL" in normalized:
        tokens.add("MPL-2.0")
    if "PSF" in normalized:
        tokens.add("PSF-2.0")
    if "APACHE" in normalized:
        tokens.add("Apache-2.0")
    return tokens


def _requirement_name(req: str) -> str:
    try:
        parsed = Requirement(req)
    except InvalidRequirement:
        return ""
    # Skip extras and markers that do not apply to this interpreter (for example Windows-only).
    if parsed.marker is not None and not parsed.marker.evaluate():
        return ""
    return parsed.name


def _walk(name: str, seen: set[str]) -> None:
    if name in seen:
        return
    try:
        dist = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return
    seen.add(name)
    for req in dist.requires or []:
        dep = _requirement_name(req)
        if dep:
            _walk(dep, seen)


def test_dependency_licenses():
    closure: set[str] = set()
    for name in _direct_names():
        _walk(name, closure)
    problems = []
    for name in sorted(closure):
        dist = metadata.distribution(name)
        tokens = _license_tokens(dist)
        if tokens & ALLOWED:
            continue
        expected = EXCEPTIONS.get(dist.metadata["Name"].lower()) or EXCEPTIONS.get(name.lower())
        if expected and expected in tokens:
            continue
        problems.append(f"{name}: {sorted(tokens) or ['unknown']}")
    assert problems == []
