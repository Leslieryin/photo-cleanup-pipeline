# -*- coding: utf-8 -*-
"""第 1 步：扫描全部图片，按 SHA-256 找出字节级完全相同的副本，按优先级保留一份，其余删除。

用法：
    python step1_dedup.py --root <图片根目录> [--prefer 子串 ...] [--dry-run]

- --prefer   可多次给出；路径包含该子串的副本优先保留（例如你信任的相册目录名）
- --dry-run  只记录将要删除的文件，不实际删除
输出：<root>/_cleanup/step1_去重日志.csv、step2_保留图片清单.json
"""
import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp"}
OUT_DIR_NAME = "_cleanup"
MESSY_RE = re.compile(r"(\(\d+\)\.\w+$|副本|copy|_copy|- copy)", re.I)


def scan(root, out_dir):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if os.path.normcase(os.path.join(dirpath, d)) != os.path.normcase(out_dir)]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in EXTS:
                p = os.path.join(dirpath, fn)
                try:
                    files.append((p, os.path.getsize(p), os.path.getmtime(p)))
                except OSError as e:
                    print(f"[跳过] 无法访问: {p} ({e})", flush=True)
    return files


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_keep_key(prefer_substrings):
    """越小越优先保留：优先目录 > 非回收站残留 > 文件名干净 > 修改时间早。"""

    def keep_key(entry):
        path, size, mtime = entry
        prefer_rank = 0 if any(s in path for s in prefer_substrings) else 1
        trashed_rank = 0 if ".trashed-" not in os.path.basename(path).lower() else 1
        messy_rank = 1 if MESSY_RE.search(os.path.basename(path)) else 0
        return (prefer_rank, trashed_rank, messy_rank, mtime, path)

    return keep_key


def main():
    ap = argparse.ArgumentParser(description="按 SHA-256 去重图片（字节级相同）")
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--prefer", action="append", default=[],
                    help="路径包含该子串的副本优先保留，可多次给出")
    ap.add_argument("--dry-run", action="store_true", help="只记录不删除")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    os.makedirs(out_dir, exist_ok=True)
    log_csv = os.path.join(out_dir, "step1_去重日志.csv")
    manifest = os.path.join(out_dir, "step2_保留图片清单.json")

    t0 = time.time()
    files = scan(root, out_dir)
    print(f"共扫描到 {len(files)} 个图片文件，耗时 {time.time()-t0:.1f}s", flush=True)

    by_size = {}
    for e in files:
        by_size.setdefault(e[1], []).append(e)
    need_hash = [g for g in by_size.values() if len(g) > 1]
    print(f"按大小初筛：{len(need_hash)} 组需要哈希比对", flush=True)

    t1 = time.time()
    dup_groups = []
    for i, group in enumerate(need_hash):
        by_hash = {}
        for e in group:
            by_hash.setdefault(sha256(e[0]), []).append(e)
        for members in by_hash.values():
            if len(members) > 1:
                dup_groups.append(members)
        if (i + 1) % 200 == 0:
            print(f"  哈希进度 {i+1}/{len(need_hash)} 组，{time.time()-t1:.0f}s", flush=True)
    print(f"哈希完成，发现 {len(dup_groups)} 组重复，耗时 {time.time()-t1:.1f}s", flush=True)

    keep_key = make_keep_key(args.prefer)
    deleted, freed, kept_rows = [], 0, []
    with open(log_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["动作", "文件路径", "大小(字节)", "备注"])
        for members in dup_groups:
            members_sorted = sorted(members, key=keep_key)
            keep = members_sorted[0]
            kept_rows.append(keep[0])
            w.writerow(["保留", keep[0], keep[1], f"重复组{len(members)}份"])
            for dup in members_sorted[1:]:
                if args.dry_run:
                    w.writerow(["待删除(dry-run)", dup[0], dup[1], ""])
                    continue
                try:
                    os.remove(dup[0])
                    deleted.append(dup[0])
                    freed += dup[1]
                    w.writerow(["删除", dup[0], dup[1], ""])
                except OSError as e:
                    w.writerow(["删除失败", dup[0], dup[1], str(e)])
                    print(f"[失败] {dup[0]}: {e}", flush=True)

    # 大小唯一的文件 + 每组保留的那份 = 进入后续流程的图片
    groups_with_dup = {e[0] for g in dup_groups for e in g}
    survivors = [e for e in files if e[0] not in groups_with_dup] + \
                [(p, os.path.getsize(p), os.path.getmtime(p)) for p in kept_rows if os.path.exists(p)]
    with open(manifest, "w", encoding="utf-8") as f:
        json.dump([{"path": p, "size": s, "mtime": m} for p, s, m in survivors],
                  f, ensure_ascii=False)

    print("=" * 60, flush=True)
    print(f"扫描图片总数 : {len(files)}")
    print(f"重复组数量   : {len(dup_groups)}")
    if args.dry_run:
        print(f"dry-run：未删除任何文件，待删清单见 {log_csv}")
    else:
        print(f"已删除副本   : {len(deleted)} 个，释放 {freed/2**30:.2f} GiB")
    print(f"保留图片总数 : {len(survivors)}")
    print(f"日志: {log_csv}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
