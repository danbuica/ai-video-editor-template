"""After the final: copy it next to the original recordings (export/), then free the laptop of the big
regenerable files (renders, proxies, working audio/video). Small edit files (edl, transcripts, decisions,
motion plan, layout) stay, so the video can be re-rendered later from the originals.

Safety: export only creates NEW files inside an `export/` folder (never overwrites, never an original);
clean only deletes media inside projects/<name>/ (never inputs/, never symlinks, never originals) and refuses
until the export is verified on the drive."""
from __future__ import annotations

import glob
import os
import shutil
import tempfile
from pathlib import Path

from .common import Project, ensure_writable, ffprobe, load_json, save_json

MEDIA = {".mp4", ".mov", ".m4a", ".wav", ".npy"}


def _final(project: Project) -> Path:
    return project.out / f"{project.name}_final_4k.mp4"


def _duration(path: Path) -> float:
    return float(ffprobe(path)["format"]["duration"])


def export(project: Project, src: Path | None = None, dest_dir: Path | None = None) -> list[Path]:
    src = Path(src) if src else _final(project)
    if not src.exists():
        raise SystemExit(f"Nothing to export: {src} does not exist (render + master the final first).")
    originals = {p.resolve() for p in project.originals()}
    dest_dir = Path(dest_dir) if dest_dir else project.talking.resolve().parent / "export"
    if dest_dir.name != "export":
        raise SystemExit(f"Export folder must be named 'export' (got {dest_dir}).")
    dest_dir.mkdir(exist_ok=True)
    files = [src] + [project.out / n for n in ("youtube_chapters.txt", "description.md") if (project.out / n).exists()]
    done = []
    for f in files:
        dst = dest_dir / f.name
        k = 2
        while dst.exists():  # never overwrite: <name>_final_4k_2.mp4, …
            dst = dest_dir / f"{f.stem}_{k}{f.suffix}"
            k += 1
        if dst.resolve() in originals:
            raise SystemExit(f"Refusing to write onto an original recording: {dst}")
        part = dst.with_name(dst.name + ".part")
        shutil.copyfile(f, part)
        if part.stat().st_size != f.stat().st_size:
            part.unlink()
            raise SystemExit(f"Copy size mismatch for {f.name}; nothing exported.")
        part.rename(dst)
        if f.suffix == ".mp4" and abs(_duration(dst) - _duration(f)) > 0.05:
            raise SystemExit(f"Exported {dst} does not play back at the same length as {f}.")
        print(f"[export] {f.name} → {dst} ({f.stat().st_size / 1e9:.2f} GB)")
        done.append(dst)
    save_json(project.out / "export.json", {"video": str(done[0]), "size": src.stat().st_size, "files": [str(d) for d in done]})
    return done


def _frames_dir(project: Project, p: Path) -> Path | None:
    """The `*_frames` folder (raw frame dumps, e.g. work/demos/demo_acme_frames) a file sits in, if any."""
    for parent in p.relative_to(project.dir).parents:
        if parent.name.endswith("_frames"):
            return project.dir / parent
    return None


def _cleanable(project: Project) -> list[Path]:
    originals = {p.resolve() for p in project.originals()}
    found = []
    for root, dirs, names in os.walk(project.dir):
        dirs[:] = [d for d in dirs if d != "inputs"]
        for n in names:
            p = Path(root) / n
            if p.is_symlink() or p.resolve() in originals:
                continue
            if p.suffix.lower() not in MEDIA and _frames_dir(project, p) is None:
                continue
            ensure_writable(p)  # inside projects/, not inputs/, not an original
            found.append(p)
    return sorted(found, key=lambda p: -p.stat().st_size)


def clean(project: Project, yes: bool = False, skip_export_check: bool = False) -> int:
    if not skip_export_check:
        rec = project.out / "export.json"
        if not rec.exists():
            raise SystemExit("No export.json: run `vcut export` first (or pass --skip-export-check).")
        e = load_json(rec)
        v = Path(e["video"])
        if not v.exists() or v.stat().st_size != e["size"]:
            raise SystemExit(f"The exported final is missing or a different size on the drive: {v}. Not cleaning.")
        print(f"[clean] export verified: {v}")
    files = _cleanable(project)
    temps = [Path(d) for d in glob.glob(os.path.join(tempfile.gettempdir(), "react-motion-render*"))]
    total = sum(p.stat().st_size for p in files)
    frame_dirs: dict[Path, list[Path]] = {}
    for p in files:
        d = _frames_dir(project, p)
        if d is not None:
            frame_dirs.setdefault(d, []).append(p)
        else:
            print(f"  {p.stat().st_size / 1e6:9.0f} MB  {p.relative_to(project.dir)}")
    for d, fs in sorted(frame_dirs.items()):
        print(f"  {sum(f.stat().st_size for f in fs) / 1e6:9.0f} MB  {d.relative_to(project.dir)}/ ({len(fs)} frames)")
    if temps:
        print(f"  + {len(temps)} leftover Remotion temp folder(s)")
    print(f"[clean] {len(files)} files, {total / 1e9:.1f} GB {'deleted' if yes else "would be deleted (dry run). Watch the exported file before passing --yes"}")
    if yes:
        for p in files:
            p.unlink()
        for d in temps:
            shutil.rmtree(d, ignore_errors=True)
        proxy = project.out / "proxy"
        if proxy.exists() and not any(proxy.iterdir()):
            proxy.rmdir()
        for d in sorted(frame_dirs, key=lambda d: -len(d.parts)):  # emptied frame dumps go too
            for sub in sorted(d.rglob("*"), key=lambda s: -len(s.parts)):
                if sub.is_dir() and not any(sub.iterdir()):
                    sub.rmdir()
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
    return total
