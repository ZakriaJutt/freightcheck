"""Write .env.local (git-ignored) from tools/env.example with a fresh random signing key."""

from __future__ import annotations

import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / ".env.local"
    if target.exists():
        print(".env.local exists; left unchanged")
        return
    text = (ROOT / "tools" / "env.example").read_text()
    target.write_text(text.replace("replace-with-random-64-hex", secrets.token_hex(32)))
    target.chmod(0o600)
    print("wrote .env.local")


if __name__ == "__main__":
    main()
