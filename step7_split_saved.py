# -*- coding: utf-8 -*-
"""第 7 步：细分「保存的图片」——按来源（小红书 / 微信 / 抖音 / 聊天图 / 网图 / 导入图 / 其他）
分类，带日期的再按年分组。

默认只打印统计（预演，不动任何文件），加 --apply 才真正移动。
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

RE_EPOCH13 = re.compile(r"^(1[3-9]\d{11})")            # 13 位毫秒时间戳开头
RE_HEX = re.compile(r"^[0-9a-f]{32,64}(\s*\(\d+\)|_raw|\.\d+)?\.\w+$", re.I)
RE_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.", re.I)
RE_XHS_EPOCH = re.compile(r"^(?:Camera_)?XHS_(1[3-9]\d{11})")

NO_YEAR = ("微信", "抖音", "导入图", "其他")   # 这些来源不再按年拆子目录


def classify(path):
    """返回 (来源, 年份或 None)。"""
    name = os.path.basename(path)
    lower = name.lower()

    if lower.startswith("camera_") or lower.startswith("xhs_"):
        m = RE_XHS_EPOCH.search(name)
        if m:
            return ("小红书", datetime.fromtimestamp(int(m.group(1)) / 1000).year)
        return ("小红书", None)
    if lower.startswith("mmexport") or lower.startswith("mm_facetoface"):
        return ("微信", None)
    if lower.startswith("douyin"):
        return ("抖音", None)
    m = RE_EPOCH13.match(name)
    if m:
        return ("聊天图", datetime.fromtimestamp(int(m.group(1)) / 1000).year)
    if RE_HEX.match(name):
        return ("网图", None)
    if RE_UUID.match(name):
        return ("导入图", None)
    return ("其他", None)


def unique_dst(dst):
    if not os.path.exists(dst):
        return dst
    stem, ext = os.path.splitext(dst)
    n = 1
    while os.path.exists("%s_%d%s" % (stem, n, ext)):
        n += 1
    return "%s_%d%s" % (stem, n, ext)


def main():
    ap = argparse.ArgumentParser(description="按来源细分「保存的图片」（默认预演）")
    ap.add_argument("--root", required=True, help="相册根目录")
    ap.add_argument("--dir", default="保存的图片", help="待细分的子目录（相对 root），默认「保存的图片」")
    ap.add_argument("--apply", action="store_true", help="真正执行移动（默认只预演）")
    args = ap.parse_args()

    t0 = time.time()
    root = os.path.abspath(args.root)
    base = os.path.join(root, args.dir) if not os.path.isabs(args.dir) else args.dir
    out_dir = os.path.join(root, OUT_DIR_NAME)
    log_csv = os.path.join(out_dir, "step7_细分日志.csv")

    if not os.path.isdir(base):
        sys.exit("目录不存在：%s" % base)

    entries = []
    for f in os.listdir(base):
        p = os.path.join(base, f)
        if not os.path.isfile(p):
            continue
        cat, year = classify(p)
        if year is None:  # 无文件名日期 → 用修改时间年份
            try:
                year = datetime.fromtimestamp(os.path.getmtime(p)).year
            except OSError:
                continue
        try:
            size = os.path.getsize(p)
        except OSError:
            continue
        entries.append((p, cat, year, size))

    cnt, size = Counter(), Counter()
    for _, cat, year, s in entries:
        key = cat if cat in NO_YEAR else "%s\\%s" % (cat, year)
        cnt[key] += 1
        size[key] += s

    print("待细分目录：%s" % base)
    print("共 %d 个文件，扫描 %.1fs" % (len(entries), time.time() - t0))
    print("%-20s%7s%9s" % ("目标位置", "数量", "大小MB"))
    for key in sorted(cnt):
        print("%-20s%7d%9.1f" % (key, cnt[key], size[key] / 2 ** 20))

    if not args.apply:
        print("\n[试运行] 未做任何改动。加 --apply 执行移动。")
        return

    os.makedirs(out_dir, exist_ok=True)
    moved, failed = 0, []
    with open(log_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["原路径", "新路径"])
        for p, cat, year, _ in entries:
            sub = cat if cat in NO_YEAR else os.path.join(cat, str(year))
            dst_dir = os.path.join(base, sub)
            os.makedirs(dst_dir, exist_ok=True)
            dst = unique_dst(os.path.join(dst_dir, os.path.basename(p)))
            try:
                os.rename(p, dst)
                moved += 1
                w.writerow([p, dst])
            except OSError as e:
                failed.append((p, str(e)))
                w.writerow([p, "失败: %s" % e])

    print("\n已移动 %d 个文件，失败 %d 个，耗时 %.0fs" % (moved, len(failed), time.time() - t0))
    for p, e in failed[:10]:
        print("  [失败] %s: %s" % (p, e))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
