# -*- coding: utf-8 -*-
"""第 3 步：对去重+转换后的全部图片计算 pHash 感知哈希与尺寸，
生成 ①相似图报告 ②无意义图片候选清单（只报告，不删除任何文件）。

用法：
    python step3_reports.py --root <图片根目录>

特性：断点续算（每 1000 张存档）、并查集相似分组、分块比对（numpy）。
输出：<root>/相似图报告.md、<root>/无意义图片候选清单.md、<root>/_cleanup/step3_指纹数据.json
"""
import argparse
import json
import os
import re
import sys
import time

import numpy as np
import pillow_heif
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
pillow_heif.register_heif_opener()

EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".bmp"}
THRESHOLD = 8  # pHash 64 位汉明距离阈值
OUT_DIR_NAME = "_cleanup"

_DCT_N = 32
_n = np.arange(_DCT_N)
_k = _n.reshape(-1, 1)
_DCT_M = np.cos(np.pi / _DCT_N * (_n + 0.5) * _k)
_DCT_M[:, 0] *= 1 / np.sqrt(2)


def phash(im):
    """DCT 感知哈希（pHash）：32x32 灰度 DCT，取左上 8x8 低频，按中值二值化。"""
    g = im.convert("L").resize((_DCT_N, _DCT_N), Image.LANCZOS)
    a = np.asarray(g, dtype=np.float64)
    dct = _DCT_M @ a @ _DCT_M.T
    low = dct[:8, :8].flatten()
    med = np.median(low[1:])  # 排除直流分量
    v = np.uint64(0)
    for i, b in enumerate(low > med):
        if b:
            v |= np.uint64(1) << np.uint64(i)
    return int(v)


def scan(root, out_dir):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != OUT_DIR_NAME]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in EXTS:
                p = os.path.join(dirpath, fn)
                try:
                    files.append({"path": p, "size": os.path.getsize(p)})
                except OSError:
                    pass
    return files


def popcount_matrix(x):
    """uint64 异或矩阵 -> 汉明距离矩阵（uint8）。"""
    d = np.zeros(x.shape, dtype=np.uint8)
    for _ in range(64):
        d += (x & np.uint64(1)).astype(np.uint8)
        x >>= np.uint64(1)
    return d


def main():
    ap = argparse.ArgumentParser(description="pHash 相似图报告 + 无意义图片候选清单（只报告不删除）")
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--threshold", type=int, default=THRESHOLD, help="相似判定汉明距离阈值（默认 8）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    os.makedirs(out_dir, exist_ok=True)
    similar_md = os.path.join(root, "相似图报告.md")
    meaningless_md = os.path.join(root, "无意义图片候选清单.md")
    raw_json = os.path.join(out_dir, "step3_指纹数据.json")

    t0 = time.time()
    files = scan(root, out_dir)
    print(f"扫描到 {len(files)} 个图片文件", flush=True)

    # 断点续算：读取上次已完成的指纹（pHash 版本）
    ckpt_path = os.path.join(out_dir, "step3_指纹进度_phash.json")
    done, broken = {}, []
    if os.path.exists(ckpt_path):
        try:
            with open(ckpt_path, encoding="utf-8") as f:
                prev = json.load(f)
            done = {r["path"]: r for r in prev["records"]}
            broken = prev.get("broken", [])
            print(f"续算：已有 {len(done)} 张指纹、{len(broken)} 条损坏记录", flush=True)
        except Exception as e:
            print(f"[警告] 进度文件读取失败，从头开始：{e}", flush=True)
            done = {}

    todo = [e for e in files if e["path"] not in done]
    print(f"本次需计算指纹：{len(todo)} 张", flush=True)

    new_count = 0
    for i, e in enumerate(todo):
        p = e["path"]
        try:
            with Image.open(p) as im:
                w, h = im.size
                hv = phash(im)
            done[p] = {**e, "w": w, "h": h, "hash": hv}
            new_count += 1
        except Exception as ex:
            if p in done:
                del done[p]
            broken.append({"path": p, "reason": f"{type(ex).__name__}: {ex}"})
        if new_count and new_count % 1000 == 0:
            tmp = ckpt_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"records": list(done.values()), "broken": broken}, f, ensure_ascii=False)
            os.replace(tmp, ckpt_path)
        if (i + 1) % 500 == 0:
            print(f"  指纹进度 {i+1}/{len(todo)}，{time.time()-t0:.0f}s", flush=True)
    records = list(done.values())
    broken = [b for b in broken if os.path.exists(b["path"])]  # 丢弃源文件已消失的旧记录
    print(f"指纹完成：成功 {len(records)}，损坏/无法解码 {len(broken)}，耗时 {time.time()-t0:.0f}s", flush=True)

    with open(raw_json, "w", encoding="utf-8") as f:
        json.dump({"records": records, "broken": broken}, f, ensure_ascii=False)

    # ---- 相似分组（并查集） ----
    n = len(records)
    hashes = np.array([r["hash"] for r in records], dtype=np.uint64)
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

    pair_count = 0
    CH = 512
    for s in range(0, n, CH):
        block = hashes[s:s + CH]
        x = block[:, None] ^ hashes[None, :]
        d = popcount_matrix(x)
        mask = d <= args.threshold
        ii, jj = np.nonzero(mask)
        sel = jj > s + ii  # 全局上三角：jj 是全矩阵列号，排除自身与对称重复
        for a, b in zip(ii[sel].tolist(), jj[sel].tolist()):
            union(s + a, b)
            pair_count += 1
        if (s // CH) % 10 == 0:
            print(f"  比对进度 {s}/{n}，命中相似对 {pair_count}，{time.time()-t0:.0f}s", flush=True)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    sim_groups = [g for g in groups.values() if len(g) > 1]
    sim_groups.sort(key=lambda g: (-len(g), records[g[0]]["path"]))
    print(f"相似组（≥2张，距离≤{args.threshold}）：{len(sim_groups)} 组，相似对 {pair_count}", flush=True)

    def group_dist_range(g):
        idx = np.array(g)
        x = hashes[idx][:, None] ^ hashes[idx][None, :]
        d = popcount_matrix(x)
        iu = np.triu_indices(len(g), 1)
        dd = d[iu]
        return int(dd.min()), int(dd.max())

    def fmt(r):
        return f"| `{os.path.relpath(r['path'], root)}` | {r['w']}×{r['h']} | {r['size']/1024:.0f} KB |"

    with open(similar_md, "w", encoding="utf-8") as f:
        f.write(f"# 相似图报告（pHash 感知哈希距离 ≤ {args.threshold}/64）\n\n")
        f.write(f"扫描图片 {len(records)} 张，发现疑似相似组 {len(sim_groups)} 组。")
        f.write("这些图片内容高度相似（含同一照片的不同压缩版本、连拍等），**均未删除**，请逐组决定保留哪张。")
        f.write("组内距离越小内容越接近。\n\n")
        for gi, g in enumerate(sim_groups, 1):
            dmin, dmax = group_dist_range(g)
            f.write(f"## 组 {gi}（{len(g)} 张，组内两两距离 {dmin}~{dmax}）\n\n| 文件 | 分辨率 | 大小 |\n|---|---|---|\n")
            for i in g:
                f.write(fmt(records[i]) + "\n")
            f.write("\n")

    # ---- 无意义候选 ----
    SCREEN_RE = re.compile(r"(screenshot|截图|屏幕截图|Screenshot_\d{4})", re.I)
    cats = {"trashed": [], "screen": [], "tiny_kb": [], "tiny_px": []}
    for r in records:
        name = os.path.basename(r["path"])
        if ".trashed-" in name.lower():
            cats["trashed"].append(r)
        elif SCREEN_RE.search(name):
            cats["screen"].append(r)
        elif r["size"] < 20 * 1024:
            cats["tiny_kb"].append(r)
        elif min(r["w"], r["h"]) < 200:
            cats["tiny_px"].append(r)

    trashed_all = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != OUT_DIR_NAME]
        for fn in filenames:
            if ".trashed-" in fn.lower() and os.path.splitext(fn)[1].lower() not in EXTS:
                p = os.path.join(dirpath, fn)
                trashed_all.append((p, os.path.getsize(p)))

    with open(meaningless_md, "w", encoding="utf-8") as f:
        f.write("# 无意义图片候选清单\n\n")
        f.write("以下仅为**候选**，一个都没删。请挑选后编辑本文件（保留要删除的行），再用 step4 执行删除。\n\n")
        title_map = {
            "trashed": "A. 回收站残留（.trashed- 开头，手机删除时留下的）",
            "screen": "B. 疑似截图（文件名含 Screenshot/截图）",
            "tiny_kb": "C. 超小图片（< 20KB，多为表情包/图标/缓存图）",
            "tiny_px": "D. 极小尺寸图片（最短边 < 200px，多为缩略图/贴纸）",
        }
        for key in ("trashed", "screen", "tiny_kb", "tiny_px"):
            items = cats[key]
            total_kb = sum(r["size"] for r in items) / 1024
            f.write(f"## {title_map[key]}（{len(items)} 张，共 {total_kb/1024:.1f} MB）\n\n")
            f.write("| 文件 | 分辨率 | 大小 |\n|---|---|---|\n")
            for r in items:
                f.write(fmt(r) + "\n")
            f.write("\n")
        if trashed_all:
            f.write(f"## E. 回收站残留的非图片文件（{len(trashed_all)} 个）\n\n")
            f.write("| 文件 | 大小 |\n|---|---|\n")
            for p, s in trashed_all:
                f.write(f"| `{os.path.relpath(p, root)}` | {s/1024/1024:.1f} MB |\n")
            f.write("\n")

    print(f"无意义候选：trashed={len(cats['trashed'])} 截图={len(cats['screen'])} "
          f"超小={len(cats['tiny_kb'])} 极小尺寸={len(cats['tiny_px'])} "
          f"trashed非图片={len(trashed_all)}", flush=True)
    print(f"报告已生成：\n  {similar_md}\n  {meaningless_md}")
    if broken:
        print(f"[警告] {len(broken)} 个文件无法解码，见 {raw_json}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
