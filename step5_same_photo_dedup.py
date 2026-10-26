# -*- coding: utf-8 -*-
"""第 5 步：相似图保守清理——只删「同一张照片的不同版本」（组内距离 ≤ SAME_T 的子簇），
每个子簇保留画质最好的一张；连拍的不同瞬间全部保留。清理后重写相似图报告。

依赖第 3 步产出的 `_cleanup/step3_指纹数据.json`，必须先跑 step3_reports.py。
"""
import argparse
import csv
import json
import os
import sys
import time

import numpy as np

OUT_DIR_NAME = "_cleanup"
GROUP_T = 8   # 相似组阈值：距离 ≤ 8 视为同一场景
SAME_T = 4    # 「同一张照片的不同版本」阈值：距离 ≤ 4 才认为是同一张


def dist_matrix(hashes):
    x = hashes[:, None] ^ hashes[None, :]
    d = np.zeros(x.shape, dtype=np.uint8)
    for _ in range(64):
        d += (x & np.uint64(1)).astype(np.uint8)
        x >>= np.uint64(1)
    return d


def main():
    ap = argparse.ArgumentParser(
        description="清理同一张照片的不同版本（保守：只处理组内距离 ≤ %d 的子簇）" % SAME_T
    )
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--prefer", action="append", default=[],
                    help="优先保留的目录关键字，可多次指定，如 --prefer \"精选\"")
    ap.add_argument("--dry-run", action="store_true", help="只记录不删除，也不重写报告")
    args = ap.parse_args()

    t0 = time.time()
    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    fp_json = os.path.join(out_dir, "step3_指纹数据.json")
    log_csv = os.path.join(out_dir, "step5_同图版本清理日志.csv")
    similar_md = os.path.join(root, "相似图报告.md")

    if not os.path.exists(fp_json):
        sys.exit("找不到指纹数据：%s\n请先运行 step3_reports.py 生成指纹。" % fp_json)

    with open(fp_json, encoding="utf-8") as f:
        data = json.load(f)
    records = [r for r in data["records"] if os.path.exists(r["path"])]
    print("现存图片 %d 张（指纹数据中原 %d 张）" % (len(records), len(data["records"])), flush=True)

    n = len(records)
    hashes = np.array([r["hash"] for r in records], dtype=np.uint64)

    # ---- 第一层：距离 ≤ GROUP_T 并查集分组（分块全对比，只取全局上三角） ----
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    CH = 512
    for s in range(0, n, CH):
        x = hashes[s:s + CH][:, None] ^ hashes[None, :]
        d = np.zeros(x.shape, dtype=np.uint8)
        for _ in range(64):
            d += (x & np.uint64(1)).astype(np.uint8)
            x >>= np.uint64(1)
        ii, jj = np.nonzero(d <= GROUP_T)
        sel = jj > s + ii
        for a, b in zip(ii[sel].tolist(), jj[sel].tolist()):
            union(s + a, b)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    sim_groups = [g for g in groups.values() if len(g) > 1]
    print("相似组（距离 ≤ %d）：%d 组，耗时 %.0fs" % (GROUP_T, len(sim_groups), time.time() - t0), flush=True)

    # ---- 第二层：组内距离 ≤ SAME_T 聚出「同一张照片的不同版本」子簇 ----
    prefer = [p.lower() for p in args.prefer]

    def keep_key(r):
        """优先级：--prefer 命中的目录 > 分辨率 > 文件大小 > 路径。"""
        rank = 0 if any(k in r["path"].lower() for k in prefer) else 1
        return (rank, -(r["w"] * r["h"]), -r["size"], r["path"])

    to_delete, cluster_count = [], 0
    with open(log_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["动作", "文件", "分辨率", "大小(字节)", "备注"])
        for g in sim_groups:
            gi = np.array(g)
            d = dist_matrix(hashes[gi])
            pp = list(range(len(g)))
            for a in range(len(g)):
                for b in range(a + 1, len(g)):
                    if d[a, b] <= SAME_T:
                        ra, rb = pp[a], pp[b]
                        if ra != rb:
                            pp[max(ra, rb)] = min(ra, rb)
            sub = {}
            for k in range(len(g)):
                r = k
                while pp[r] != r:
                    r = pp[r]
                sub.setdefault(r, []).append(g[k])
            for members in sub.values():
                if len(members) < 2:
                    continue
                cluster_count += 1
                members_sorted = sorted(members, key=lambda i: keep_key(records[i]))
                keep = members_sorted[0]
                w.writerow(["保留", records[keep]["path"],
                            "%dx%d" % (records[keep]["w"], records[keep]["h"]),
                            records[keep]["size"], "子簇 %d 张" % len(members)])
                for i in members_sorted[1:]:
                    p = records[i]["path"]
                    if args.dry_run:
                        to_delete.append(p)
                        w.writerow(["待删除", p, "%dx%d" % (records[i]["w"], records[i]["h"]),
                                    records[i]["size"], ""])
                        continue
                    try:
                        os.remove(p)
                        to_delete.append(p)
                        w.writerow(["删除", p, "%dx%d" % (records[i]["w"], records[i]["h"]),
                                    records[i]["size"], ""])
                    except OSError as e:
                        w.writerow(["删除失败", p, "", records[i]["size"], str(e)])

    verb = "待删除" if args.dry_run else "已删除"
    print("同图不同版本子簇：%d 个，%s %d 张" % (cluster_count, verb, len(to_delete)), flush=True)

    if args.dry_run:
        print("\n[试运行] 未删除任何文件，日志已写入 %s" % log_csv)
        print("确认无误后去掉 --dry-run 重跑。报告未重写。")
        return

    # ---- 重写相似图报告（删除后的现存状态） ----
    gone = set(to_delete)
    records = [r for r in records if r["path"] not in gone]
    hashes = np.array([r["hash"] for r in records], dtype=np.uint64)
    n = len(records)
    parent = list(range(n))

    def find2(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for s in range(0, n, CH):
        x = hashes[s:s + CH][:, None] ^ hashes[None, :]
        d = np.zeros(x.shape, dtype=np.uint8)
        for _ in range(64):
            d += (x & np.uint64(1)).astype(np.uint8)
            x >>= np.uint64(1)
        ii, jj = np.nonzero(d <= GROUP_T)
        sel = jj > s + ii
        for a, b in zip(ii[sel].tolist(), jj[sel].tolist()):
            ra, rb = find2(s + a), find2(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

    groups = {}
    for i in range(n):
        groups.setdefault(find2(i), []).append(i)
    sim_groups = [g for g in groups.values() if len(g) > 1]
    sim_groups.sort(key=lambda g: (-len(g), records[g[0]]["path"]))

    with open(similar_md, "w", encoding="utf-8") as f:
        f.write("# 相似图报告（pHash 距离 ≤ %d/64，同图不同版本已清理后重建）\n\n" % GROUP_T)
        f.write("现存图片 %d 张，剩余疑似相似组 %d 组（均为连拍/同场景多张），" % (n, len(sim_groups)))
        f.write("**均未删除**。组内距离越小内容越接近。\n\n")
        for gi, g in enumerate(sim_groups, 1):
            idx = np.array(g)
            d = dist_matrix(hashes[idx])
            iu = np.triu_indices(len(g), 1)
            dd = d[iu]
            f.write("## 组 %d（%d 张，组内两两距离 %d~%d）\n\n"
                    "| 文件 | 分辨率 | 大小 |\n|---|---|---|\n"
                    % (gi, len(g), int(dd.min()), int(dd.max())))
            for i in g:
                r = records[i]
                rel = os.path.relpath(r["path"], root)
                f.write("| `%s` | %d×%d | %.0f KB |\n"
                        % (rel, r["w"], r["h"], r["size"] / 1024))
            f.write("\n")
    print("报告已重写：剩余相似组 %d 组，耗时 %.0fs" % (len(sim_groups), time.time() - t0))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
