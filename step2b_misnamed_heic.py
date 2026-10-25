# -*- coding: utf-8 -*-
"""第 2b 步：把扩展名是 .jpg/.png 但内容实际是 HEIC/HEIF 的文件转成真正的 JPG。

有些手机导出/同步工具会产生「假 JPG」——扩展名是 .jpg，文件头却是 HEIC，
普通看图软件能打开，但归档后 EXIF 与兼容性都会出问题。本脚本自动扫描识别并原地转换。

用法：
    python step2b_misnamed_heic.py --root <图片根目录> [--dry-run]
"""
import argparse
import os
import sys
import time
from io import BytesIO

import pillow_heif
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
pillow_heif.register_heif_opener()

OUT_DIR_NAME = "_cleanup"
QUALITY = 95


def convert_in_place(p):
    """原地转换：先写临时文件，校验通过后再替换原文件。返回 (True, 新大小KB) 或 (False, 原因)。"""
    tmp = p + ".tmp_converting"
    try:
        with Image.open(p) as im:
            if im.format not in ("HEIF", "HEIC"):
                return False, f"格式不符: {im.format}"
            exif, icc = im.info.get("exif"), im.info.get("icc_profile")
            im.load()
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            buf = BytesIO()
            kw = {"format": "JPEG", "quality": QUALITY, "subsampling": 1}
            if exif:
                kw["exif"] = exif
            if icc:
                kw["icc_profile"] = icc
            im.save(buf, **kw)
            src_size = im.size
        buf.seek(0)
        with Image.open(buf) as chk:
            chk.verify()
        buf.seek(0)
        with Image.open(buf) as chk:
            if chk.size != src_size:
                return False, "分辨率不一致"
        with open(tmp, "wb") as f:
            f.write(buf.getvalue())
        os.replace(tmp, p)
        return True, os.path.getsize(p) // 1024
    except Exception as e:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False, f"{type(e).__name__}: {e}"


def main():
    ap = argparse.ArgumentParser(description="把内容为 HEIC 但扩展名为 .jpg/.png 的文件原地转为真 JPG")
    ap.add_argument("--root", required=True, help="图片根目录")
    ap.add_argument("--dry-run", action="store_true", help="只识别报告，不转换")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    out_dir = os.path.join(root, OUT_DIR_NAME)
    suspects, converted, failed = [], [], []
    t0 = time.time()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != OUT_DIR_NAME]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() not in (".jpg", ".jpeg", ".png"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with Image.open(p) as im:
                    fmt = im.format
            except Exception:
                continue
            if fmt not in ("HEIF", "HEIC"):
                continue
            suspects.append(p)
            if args.dry_run:
                print(f"[假JPG] {p}")
                continue
            ok, info = convert_in_place(p)
            if ok:
                converted.append(p)
                print(f"[OK] {fn} -> 真 JPG（{info} KB）", flush=True)
            else:
                failed.append((p, info))
                print(f"[失败] {p} | {info}", flush=True)

    print("=" * 60, flush=True)
    print(f"扫描完成，耗时 {time.time()-t0:.0f}s")
    print(f"识别为「假 JPG」（实为 HEIC）：{len(suspects)} 个")
    if args.dry_run:
        print("dry-run：未转换任何文件")
    else:
        print(f"转换成功: {len(converted)}，失败: {len(failed)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
