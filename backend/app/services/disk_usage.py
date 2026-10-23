"""Collect usage for local disks and any mounted volume used by NovelFlow."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

from app.core.config import get_settings
from app.core.database import engine
from app.services.file_storage import file_storage


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _mount_point(path: Path) -> Path:
    """Find the filesystem containing a project path, including not-yet-created dirs."""
    current = path.resolve()
    while not current.exists() and current != current.parent:
        current = current.parent
    while not os.path.ismount(current) and current != current.parent:
        current = current.parent
    return current


def _local_mounts() -> set[Path]:
    if os.name == "nt":
        return {Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").is_dir()}

    mounts: set[Path] = set()
    try:
        result = subprocess.run(["mount"], capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return mounts
    for line in result.stdout.splitlines():
        match = re.match(r"^(\S+) on (.+?)(?: type \S+)? \(", line)
        if not match or not match.group(1).startswith("/dev/"):
            continue
        mount_path = Path(match.group(2))
        # APFS helper volumes share the startup disk's capacity and should not repeat it.
        if sys.platform == "darwin" and str(mount_path).startswith("/System/Volumes/"):
            continue
        if mount_path.is_dir():
            mounts.add(mount_path)
    return mounts


def get_disk_usage() -> list[dict]:
    settings = get_settings()
    project_paths = [PROJECT_ROOT, file_storage.base_dir, Path(settings.OUTPUT_DIR)]
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        project_paths.append(Path(engine.url.database))

    mounts = _local_mounts()
    mounts.update(_mount_point(path) for path in project_paths)
    disks = []
    seen_devices: set[int] = set()
    for mount_path in sorted(mounts, key=lambda path: (str(path) != "/", str(path).lower())):
        try:
            device = mount_path.stat().st_dev
            if device in seen_devices:
                continue
            usage = shutil.disk_usage(mount_path)
        except OSError:
            continue  # A removable disk may have been unplugged since enumeration.
        if usage.total <= 0:
            continue
        seen_devices.add(device)
        disks.append({
            "mount_point": str(mount_path),
            "name": mount_path.name or str(mount_path),
            "total_bytes": usage.total,
            "used_bytes": usage.used,
            "used_percent": round(usage.used / usage.total * 100, 1),
        })
    return disks
