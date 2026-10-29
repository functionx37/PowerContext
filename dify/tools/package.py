"""Create a submission archive from an explicit allowlist, excluding all runtime secrets."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = [ROOT / name for name in (
        "README.md", "dify.md", ".env.example", ".gitignore", "requirements.txt",
        "requirements-lock-windows.txt", "game.py", "server.py")]
    for folder in ("deploy", "dsl", "evidence", "tests", "tools"):
        files += [p for p in (ROOT / folder).rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts and p.suffix in {".py", ".json", ".yml", ".yaml", ".md"}
                  and not p.name.startswith("local-")]
    files.sort()
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    target = ROOT / "dist/grudge-shop.zip"
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for p in files:
            archive.write(p, "dify/" + p.relative_to(ROOT).as_posix())
        archive.writestr("dify/MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Packaged {len(files)} files: {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
