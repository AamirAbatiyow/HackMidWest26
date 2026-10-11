"""Scaffold projects/<name>/ from templates/project/.

    make new-project name=foo desc="One-line pitch"
    python templates/new_project.py foo --description "One-line pitch" [--port 8110]

Ports: API gets the next free port from 8101 upward; inference gets API port + 100.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "project"
PROJECTS = ROOT / "projects"
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
RESERVED = {"test", "tests", "app", "core", "packages", "projects", "templates", "infra", "data", "docs"}
PORT_RE = re.compile(r"^\s*port: int = (\d+)", re.MULTILINE)
BASE_PORT = 8101


def used_ports() -> list[int]:
    ports = []
    for cfg in PROJECTS.glob("*/*/config.py"):
        ports += [int(p) for p in PORT_RE.findall(cfg.read_text())]
    return ports


def next_port() -> int:
    used = set(used_ports())
    port = BASE_PORT
    while port in used:
        port += 1
    return port


def render(text: str, tokens: dict[str, str]) -> str:
    # Longest tokens first so PROJECTNAME doesn't clobber PROJECTNAME-prefixed tokens.
    for key in sorted(tokens, key=len, reverse=True):
        text = text.replace(key, tokens[key])
    return text


def scaffold(name: str, description: str, port: int | None = None) -> Path:
    if not NAME_RE.match(name) or name in RESERVED or name.startswith("hm_"):
        raise SystemExit(f"invalid project name '{name}': use lowercase letters, digits, underscores")
    target = PROJECTS / name
    if target.exists():
        raise SystemExit(f"{target.relative_to(ROOT)} already exists")
    port = port or next_port()
    tokens = {
        "PROJECTNAME": name,
        "PROJECTENVPREFIX": name.upper(),
        "PROJECTDESCRIPTION": description.replace('"', "'"),
        "PROJECTPORT": str(port),
        "PROJECTINFERPORT": str(port + 100),
    }
    for src in sorted(TEMPLATE.rglob("*")):
        if "__pycache__" in src.parts or src.suffix == ".pyc":
            continue
        dest = target / render(str(src.relative_to(TEMPLATE)), tokens)
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            dest.write_text(render(src.read_text(), tokens))
        except UnicodeDecodeError:
            shutil.copy2(src, dest)
    _ruff_fix(target)
    return target


def _ruff_fix(target: Path) -> None:
    """Import order depends on the project name (first-party, alphabetical), so let ruff settle it."""
    for args in (["check", "--fix", "--select", "I", "--quiet"], ["format", "--quiet"]):
        try:
            subprocess.run([sys.executable, "-m", "ruff", *args, str(target)], cwd=ROOT, check=False)  # noqa: S603
        except OSError:
            return


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("name")
    parser.add_argument("--description", "-d", default="TODO: one-line pitch.")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)
    target = scaffold(args.name, args.description, args.port)
    print(f"created {target.relative_to(ROOT)}")
    print(f"next: `make setup` (registers the workspace member), then `make run-{args.name}`")


if __name__ == "__main__":
    sys.exit(main())
