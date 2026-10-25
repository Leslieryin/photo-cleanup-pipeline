# -*- coding: utf-8 -*-
"""第 4 步：按你的裁决，删除《无意义图片候选清单.md》中的文件。

用法：
    python step4_delete_candidates.py --root <图片根目录> [--sections AB] [--dry-run]

- --sections  只处理指定类别（A~E 的子集，如 "AC"），默认全部
- --dry-run   只列出将删除的文件，不实际删除

安全设计：本脚本只删「清单里列出的文件」；请先编辑清单、删掉不想删除的行，再执行。
输出：<root>/_cleanup/step4_删除日志.csv
"""
import argparse
import csv
import os
import re
import sys

OUT_DIR_NAME = "_cleanup"


def main():
    ap = argparse.ArgumentParser(description="按清单删除无意义图片（附日志）")
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--sections", default="ABCDE", help="要处理的类别子集（A~E），默认全部")
    ap.add_argument("--dry-run", action="store_true", help="只列出，不删除")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    report = os.path.join(root, "无意义图片候选清单.md")
    log = os.path.join(root, OUT_DIR_NAME, "step4_删除日志.csv")

    with open(report, encoding="utf-8") as f:
        lines = f.readlines()

    targets, section = [], None
    for ln in lines:
        m = re.match(r"^## ([A-E])\.", ln.strip())
        if m:
            section = m.group(1)
            continue
        if section and section in args.sections.upper() and ln.strip().startswith("| `"):
            rel = ln.split("`")[1]
            targets.append((section, os.path.join(root, rel)))

    print(f"从报告解析到 {len(targets)} 个待删除文件", flush=True)
    deleted, freed, failed = 0, 0, []
    with open(log, "w", newline="", encoding="utf-8-sig") as lf:
        w = csv.writer(lf)
        w.writerow(["类别", "文件", "大小(字节)", "结果"])
        for sec, p in targets:
            if not os.path.exists(p):
                w.writerow([sec, p, "", "不存在，跳过"])
                continue
            if args.dry_run:
                w.writerow([sec, p, os.path.getsize(p), "待删除(dry-run)"])
                continue
            try:
                size = os.path.getsize(p)
                os.remove(p)
                deleted += 1
                freed += size
                w.writerow([sec, p, size, "已删除"])
            except OSError as e:
                failed.append((p, str(e)))
                w.writerow([sec, p, "", f"失败: {e}"])

    if args.dry_run:
        print(f"dry-run：未删除任何文件，清单见 {log}")
    else:
        print(f"已删除 {deleted} 个文件，释放 {freed/2**20:.1f} MB")
    if failed:
        print(f"失败 {len(failed)} 个：")
        for p, e in failed:
            print(f"  {p}: {e}")
    print(f"日志: {log}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
