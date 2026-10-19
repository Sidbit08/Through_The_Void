"""Allowlisted, non-destructive ZIP import. Originals remain private."""
import hashlib
import json
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image

from .puzzles import ASSETS


def import_archive(archive, data_dir):
    data_dir = Path(data_dir)
    assets = data_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    reports = {}
    with zipfile.ZipFile(archive) as source:
        infos = source.infolist()
        if len(infos) > 1000 or sum(i.file_size for i in infos) > 512 * 1024 * 1024:
            raise ValueError("Archive exceeds 1000 entries or 512 MiB expanded")
        selected = {}
        for info in infos:
            path = PurePosixPath(info.filename)
            if (path.is_absolute() or ".." in path.parts or "\\" in info.filename
                    or ":" in info.filename or stat.S_ISLNK(info.external_attr >> 16)):
                raise ValueError("Unsafe ZIP path or symlink")
            if info.is_dir() or "__MACOSX" in path.parts:
                continue
            if path.name not in ASSETS:
                continue
            if path.name in selected:
                raise ValueError(f"Duplicate asset: {path.name}")
            if info.file_size > 64 * 1024 * 1024:
                raise ValueError(f"Asset exceeds 64 MiB: {path.name}")
            selected[path.name] = info
        # Validate every candidate before writing any asset.
        payloads = {}
        import io
        for name, info in selected.items():
            raw = source.read(info)  # ZIP CRC checked by zipfile
            digest = hashlib.sha256(raw).hexdigest()
            report = {"sha256": digest, "bytes": len(raw)}
            if not name.endswith(".mp3"):
                with Image.open(io.BytesIO(raw)) as image:
                    expected = "JPEG" if name.endswith(".jpeg") else "GIF" if name.endswith(".gif") else "PNG"
                    if image.format != expected:
                        raise ValueError(f"Wrong encoded format for {name}: {image.format}")
                    report.update(width=image.width, height=image.height,
                                  frames=getattr(image, "n_frames", 1))
                    for frame in range(report["frames"]):
                        image.seek(frame)
                        image.load()
            elif not (raw.startswith(b"ID3") or (len(raw) > 1 and raw[0] == 255 and raw[1] & 224 == 224)):
                raise ValueError(f"Not recognizable MP3: {name}")
            target = assets / name
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Refusing to overwrite different original: {name}")
            payloads[name] = raw
            reports[name] = report
        for name, raw in payloads.items():
            (assets / name).write_bytes(raw)
    original_dir = data_dir / "originals"
    original_dir.mkdir(exist_ok=True)
    archive_hash = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    backup = original_dir / f"{archive_hash}.zip"
    if not backup.exists():
        shutil.copyfile(archive, backup)
    (data_dir / "asset-report.json").write_text(json.dumps(reports, indent=2))
    return reports


def read_hotspots(data_dir):
    path = Path(data_dir) / "hotspots.json"
    return json.loads(path.read_text()) if path.exists() else {}


def validate_box(box):
    return (isinstance(box, list) and len(box) == 4
            and all(type(n) in (int, float) and 0 <= n <= 1 for n in box)
            and box[2] > 0 and box[3] > 0
            and box[0] + box[2] <= 1 and box[1] + box[3] <= 1)


def readiness(data_dir):
    data_dir = Path(data_dir)
    problems = [f"Missing asset: {name}" for name in ASSETS if not (data_dir / "assets" / name).is_file()]
    try:
        report = json.loads((data_dir / "asset-report.json").read_text())
        for name in ASSETS:
            path = data_dir / "assets" / name
            if path.is_file() and (name not in report or hashlib.sha256(path.read_bytes()).hexdigest() != report[name].get("sha256")):
                problems.append(f"Original asset checksum mismatch: {name}")
        if report.get("Level5.gif", {}).get("frames", 0) < 2:
            problems.append("Level5.gif must be animated")
    except (OSError, ValueError, TypeError, AttributeError):
        problems.append("Missing or invalid asset-report.json; re-import originals")
    try:
        hotspots = read_hotspots(data_dir)
        for name in ("door", "white_spot"):
            if not validate_box(hotspots.get(name)):
                problems.append(f"Uncalibrated hotspot: {name}")
    except (ValueError, TypeError):
        problems.append("Invalid hotspots.json")
    return problems
