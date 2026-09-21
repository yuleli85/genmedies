"""
清理 24 小时前产生的临时文件

目标目录：
  uploads/ppt/{uuid}/pdf/       — 导出中间 PDF（一次性，合成后无用）
  uploads/ppt/{uuid}/mixed/     — 混音中间片段（合并后无用）
  uploads/image_cache/          — 图片缓存
  uploads/video_cache/          — 视频缓存

不清理：
  uploads/ppt/{uuid}/slides/    — 幻灯片图片（重新生成动画时需要）
  uploads/ppt/{uuid}/audio/     — TTS 音频（用户可指定重新生成某页）
  uploads/ppt/{uuid}/anim/      — 动画片段（用户可指定重新生成某页）

运行：
  python3 utils/cleanup.py [--dry-run]

cron（每天凌晨 3 点）：
  0 3 * * * cd /path/to/backend && python3 utils/cleanup.py >> /var/log/genvoid_cleanup.log 2>&1
"""
import argparse
import logging
import shutil
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

UPLOADS   = Path(__file__).parent.parent / "uploads"
MAX_AGE_S = 24 * 3600  # 24 小时


def _expired(path: Path) -> bool:
    return (time.time() - path.stat().st_mtime) > MAX_AGE_S


def _remove(path: Path, dry_run: bool) -> int:
    try:
        if path.is_dir():
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
            if not dry_run:
                shutil.rmtree(path)
        else:
            size = path.stat().st_size
            if not dry_run:
                path.unlink()
        tag = "[dry-run]" if dry_run else "[deleted]"
        log.info(f"{tag} {path}  ({size / 1024 / 1024:.1f} MB)")
        return size
    except Exception as e:
        log.warning(f"删除失败 {path}: {e}")
        return 0


def clean_ppt_intermediates(dry_run: bool) -> int:
    """删除每个 PPT 项目下的一次性中间产物（pdf/ mixed/），保留 audio/ anim/ slides/。"""
    freed = 0
    ppt_dir = UPLOADS / "ppt"
    if not ppt_dir.exists():
        return 0
    for proj in ppt_dir.iterdir():
        if not proj.is_dir() or not _expired(proj):
            continue
        for sub in ("pdf", "mixed"):
            d = proj / sub
            if d.exists():
                freed += _remove(d, dry_run)
    return freed


def clean_cache(dry_run: bool) -> int:
    """删除图片/视频缓存中超过 24 小时的文件。"""
    freed = 0
    for cache_dir in (UPLOADS / "image_cache", UPLOADS / "video_cache"):
        if not cache_dir.exists():
            continue
        for f in cache_dir.rglob("*"):
            if f.is_file() and _expired(f):
                freed += _remove(f, dry_run)
    return freed


def main():
    parser = argparse.ArgumentParser(description="GenVoid 临时文件清理（24 小时）")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不实际删除")
    args = parser.parse_args()

    mode = "DRY-RUN" if args.dry_run else "LIVE"
    log.info(f"=== GenVoid cleanup START [{mode}] ===")

    total = 0
    total += clean_ppt_intermediates(args.dry_run)
    total += clean_cache(args.dry_run)

    log.info(f"=== cleanup DONE  释放 {total / 1024 / 1024:.1f} MB ===")


if __name__ == "__main__":
    main()
