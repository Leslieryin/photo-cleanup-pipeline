# -*- coding: utf-8 -*-
"""第 2 步：HEIC/HEIF -> JPG（质量 95，保留 EXIF/ICC），逐张校验通过后才删除原 HEIC。

用法：
    python step2_convert.py --root <图片根目录> [--limit N] [--test]

- --test     自检模式：只打印前几张带方向标记文件的信息，不转换不删除
- --limit N  只处理前 N 张（试跑）
输出：<root>/_cleanup/step2_转换结果.json
"""
import argparse
import json
import os
import sys
import time
from io import BytesIO

import pillow_heif
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
pillow_heif.register_heif_opener()

EXIF_ORIENTATION_TAG = 274
OUT_DIR_NAME = "_cleanup"
QUALITY = 95


def convert_one(src):
    """返回 (状态, 信息)。状态: ok / fail"""
    dst = os.path.splitext(src)[0] + ".jpg"
    n = 1
    while os.path.exists(dst):
        n += 1
        dst = os.path.splitext(src)[0] + f"_{n}.jpg"
    with Image.open(src) as im:
        exif = im.info.get("exif")
        icc = im.info.get("icc_profile")
        im.load()
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = BytesIO()
        save_kw = {"format": "JPEG", "quality": QUALITY, "subsampling": 1}
        if exif:
            save_kw["exif"] = exif
        if icc:
            save_kw["icc_profile"] = icc
        im.save(buf, **save_kw)
        src_size = im.size
    # 校验：重新解码 JPEG，确认完整且分辨率一致
    buf.seek(0)
    with Image.open(buf) as chk:
        chk.verify()
    buf.seek(0)
    with Image.open(buf) as chk:
        if chk.size != src_size:
            return "fail", f"分辨率不一致 {chk.size} != {src_size}"
    with open(dst, "wb") as f:
        f.write(buf.getvalue())
    return "ok", dst


def self_check(heics):
    """方向自检：报告前 8 张带非默认方向标记的文件，解码尺寸 vs 原始(未摆正)尺寸。"""
    checked = 0
    for p in heics:
        try:
            hf = pillow_heif.open_heif(p)
            img_elem = hf.primary_image if hf.primary_image is not None else hf[0]
            undirected = img_elem.undirected_size
            directed = img_elem.size
            with Image.open(p) as im:
                plugin_size = im.size
                ori = im.getexif().get(EXIF_ORIENTATION_TAG, 1)
            if ori == 1:
                continue
            print(f"{os.path.basename(p)}: EXIF方向={ori} 插件解码={plugin_size} "
                  f"原始={undirected} 摆正后={directed}", flush=True)
            checked += 1
            if checked >= 8:
                break
        except Exception as e:
            print(f"[自检失败] {p}: {e}", flush=True)
            break


def main():
    ap = argparse.ArgumentParser(description="HEIC/HEIF 转 JPG（校验通过后才删原文件）")
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 张（0=全部）")
    ap.add_argument("--test", action="store_true", help="自检模式，不转换不删除")
    ap.add_argument("--dry-run", action="store_true",
                    help="转换并校验，但保留原 HEIC（先确认转换结果再决定删不删）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    manifest_in = os.path.join(out_dir, "step2_保留图片清单.json")
    result = os.path.join(out_dir, "step2_转换结果.json")

    with open(manifest_in, encoding="utf-8") as f:
        entries = json.load(f)
    heics = [e["path"] for e in entries
             if os.path.splitext(e["path"])[1].lower() in (".heic", ".heif")
             and ".trashed-" not in os.path.basename(e["path"]).lower()]
    print(f"待转换 HEIC/HEIF：{len(heics)} 张（已排除 .trashed- 残留）", flush=True)

    if args.test:
        self_check(heics)
        return

    if args.limit:
        heics = heics[: args.limit]

    ok, fail = [], []
    t0 = time.time()
    for i, p in enumerate(heics):
        try:
            status, info = convert_one(p)
            if status == "ok":
                if not args.dry_run:
                    os.remove(p)
                ok.append({"src": p, "dst": info, "bytes": os.path.getsize(info),
                           "src_deleted": not args.dry_run})
            else:
                fail.append({"src": p, "reason": info})
        except Exception as e:
            fail.append({"src": p, "reason": f"{type(e).__name__}: {e}"})
        if (i + 1) % 200 == 0:
            print(f"  进度 {i+1}/{len(heics)}，成功{len(ok)} 失败{len(fail)}，"
                  f"{time.time()-t0:.0f}s", flush=True)
    with open(result, "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "fail": fail, "quality": QUALITY}, f, ensure_ascii=False)
    print("=" * 60, flush=True)
    if args.dry_run:
        print(f"转换成功: {len(ok)} 张（dry-run：原 HEIC 全部保留）")
        print("确认 JPG 无误后，去掉 --dry-run 再跑一次，才会删除原文件")
    else:
        print(f"转换成功: {len(ok)} 张（原 HEIC 已删除）")
    print(f"转换失败: {len(fail)} 张（原文件保留，见 {result}）")
    print(f"耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
