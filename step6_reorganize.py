# -*- coding: utf-8 -*-
"""第 6 步：相册全量重排——打散旧目录，按「类型 + 年月」移入新分类结构。

默认只打印统计（预演，不动任何文件），加 --apply 才真正移动并清理空目录。

源目录用 --source 指定（可多次），不指定时自动取 --root 下所有不属于目标分类的一级目录。
"""
import argparse
import csv
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime

OUT_DIR_NAME = "_cleanup"

IMG_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp", ".dng"}
VID_EXT = {".mp4", ".mov", ".avi", ".mkv", ".3gp", ".flv", ".ts", ".webm", ".m4v"}

# 这些是重排后的目标分类目录，不会被当作源目录扫描
TARGET_DIRS = {"照片", "截图", "表情包", "保存的图片", "手机视频", "收藏视频", "其他文件"}

RE_CAM_IMG = re.compile(r"^IMG[ _]?(20\d{6})", re.I)
RE_CAM_VID = re.compile(r"^VID[ _]?(20\d{6})", re.I)
RE_EPOCH_VID = re.compile(r"^Video_(\d{13})", re.I)


def classify(path):
    """返回 (分类, 年月或 None)。"""
    name = os.path.basename(path)
    lower = name.lower()
    _, ext = os.path.splitext(name)
    ext_l = ext.lower()

    if "screenshot" in lower or "截图" in name:
        return ("截图", None)
    if ext_l == ".gif":
        return ("表情包", None)
    if ext_l in IMG_EXT:
        m = RE_CAM_IMG.match(name)
        if m:
            d = m.group(1)
            return ("照片", "%s-%s" % (d[:4], d[4:6]))
        return ("保存的图片", None)
    if ext_l in VID_EXT:
        m = RE_CAM_VID.match(name)
        if m:
            d = m.group(1)
            return ("手机视频", "%s-%s" % (d[:4], d[4:6]))
        m = RE_EPOCH_VID.match(name)
        if m:
            dt = datetime.fromtimestamp(int(m.group(1)) / 1000)
            return ("手机视频", dt.strftime("%Y-%m"))
        return ("收藏视频", None)
    return ("其他文件", None)


def discover_sources(root):
    """root 下所有不属于目标分类的一级目录。"""
    found = []
    for entry in os.scandir(root):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in TARGET_DIRS or entry.name == OUT_DIR_NAME:
            continue
        found.append(entry.path)
    return found


def collect(sources):
    items = []
    for base in sources:
        for dp, _, fn in os.walk(base):
            for f in fn:
                p = os.path.join(dp, f)
                try:
                    size = os.path.getsize(p)
                except OSError:
                    continue
                cat, month = classify(p)
                items.append((p, cat, month, size))
    return items


def unique_dst(dst):
    if not os.path.exists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    n = 1
    while os.path.exists("%s_%d%s" % (stem, n, ext)):
        n += 1
    return "%s_%d%s" % (stem, n, ext)


def main():
    ap = argparse.ArgumentParser(description="按「类型+年月」重排相册目录（默认预演）")
    ap.add_argument("--root", required=True, help="相册根目录")
    ap.add_argument("--source", action="append", default=[],
                    help="待打散的旧目录，可多次指定；省略则自动取 root 下所有非分类目录")
    ap.add_argument("--apply", action="store_true", help="真正执行移动（默认只预演）")
    args = ap.parse_args()

    t0 = time.time()
    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    log_csv = os.path.join(out_dir, "step6_移动日志.csv")

    if args.source:
        sources = [os.path.abspath(s) if os.path.isabs(s) else os.path.join(root, s)
                   for s in args.source]
    else:
        sources = discover_sources(root)

    if not sources:
        sys.exit("没有找到需要打散的目录。用 --source 显式指定，或确认 --root 是否正确。")

    print("源目录：")
    for s in sources:
        print("  %s" % s)

    items = collect(sources)
    cnt, size = Counter(), Counter()
    for _, cat, month, s in items:
        key = "%s\\%s" % (cat, month) if month else cat
        cnt[key] += 1
        size[key] += s

    print("\n共 %d 个文件，%.1f GiB，扫描 %.1fs"
          % (len(items), sum(size.values()) / 2 ** 30, time.time() - t0))
    print("%-24s%7s%10s" % ("目标位置", "数量", "大小GiB"))
    for key in sorted(cnt):
        print("%-24s%7d%10.2f" % (key, cnt[key], size[key] / 2 ** 30))

    if not args.apply:
        print("\n[试运行] 未做任何改动。加 --apply 执行移动。")
        return

    os.makedirs(out_dir, exist_ok=True)
    moved, failed = 0, []
    with open(log_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["原路径", "新路径", "大小(字节)"])
        for p, cat, month, s in items:
            sub = os.path.join(cat, month) if month else cat
            dst_dir = os.path.join(root, sub)
            os.makedirs(dst_dir, exist_ok=True)
            dst = unique_dst(os.path.join(dst_dir, os.path.basename(p)))
            try:
                os.rename(p, dst)
                moved += 1
                w.writerow([p, dst, s])
            except OSError as e:
                failed.append((p, str(e)))
                w.writerow([p, "", "失败: %s" % e])

    print("\n已移动 %d 个文件，失败 %d 个，耗时 %.0fs" % (moved, len(failed), time.time() - t0))
    for p, e in failed[:10]:
        print("  [失败] %s: %s" % (p, e))

    # 清理空掉的旧目录（自底向上，只删空目录）
    removed = 0
    for base in sources:
        for dp, _, _ in list(os.walk(base, topdown=False)):
            try:
                if not os.listdir(dp):
                    os.rmdir(dp)
                    removed += 1
            except OSError as e:
                print("  [跳过] %s: %s" % (dp, e))
    print("已删除空文件夹 %d 个" % removed)
    for base in sources:
        if os.path.exists(base):
            print("[提示] %s 仍存在（未空，请检查）" % base)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
