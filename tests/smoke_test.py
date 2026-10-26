"""流水线冒烟测试：在临时目录里造一份小照片集，跑真实脚本，检查它是否做到承诺的事。

只测「安全承诺」和「核心能力」，不测每一步的全部细节：
1. step1 --dry-run 能找出字节级重复，且**一个文件都不删**
2. step1 真跑时只删重复的那份，保留一份
3. step3 能生成两份报告，且报告里确实写进了相似组

断言尽量基于 CSV 日志与文件系统，而不是 stdout 的中文文案——
避免不同平台的编码差异把测试弄成假红。
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

pass_count = 0
fail_count = 0


def ok(name, cond, extra=""):
    global pass_count, fail_count
    if cond:
        pass_count += 1
        print(f"  PASS  {name}" + (f"  [{extra}]" if extra else ""))
    else:
        fail_count += 1
        print(f"  FAIL  {name}" + (f"  [{extra}]" if extra else ""))


def make_images(root: Path):
    """造 3 张字节完全相同 + 2 张各不相同的图，不依赖 Pillow：

    第 1 步只看 SHA-256，不解析内容，所以纯字节也能覆盖它的核心逻辑。
    """
    payload = (b"\xff\xd8\xff\xe0JFIF" + bytes(range(256)) * 40 + b"\xff\xd9")
    (root / "DCIM").mkdir(parents=True, exist_ok=True)
    (root / "Weixin").mkdir(parents=True, exist_ok=True)

    (root / "DCIM" / "IMG_001.jpg").write_bytes(payload)
    (root / "Weixin" / "mmexport001.jpg").write_bytes(payload)
    (root / "Weixin" / "IMG_001(1).jpg").write_bytes(payload)

    (root / "DCIM" / "IMG_002.jpg").write_bytes(payload + b"aaa")
    (root / "DCIM" / "IMG_003.jpg").write_bytes(payload + b"bbb")


def run(script, *args):
    return subprocess.run(
        [PY, str(REPO / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(REPO),
    )


def read_log(root: Path, name):
    p = root / "_cleanup" / name
    if not p.exists():
        return None
    with p.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


print("[step1 --dry-run：找出重复但不删]")
tmp = Path(tempfile.mkdtemp(prefix="pc-test-"))
try:
    root = tmp / "photos"
    root.mkdir()
    make_images(root)
    # 只数图片：_cleanup/ 里的日志和指纹数据是脚本自己写的，不该算进来
    def count_imgs():
        return sorted(p.relative_to(root) for p in root.rglob("*")
                      if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"})

    before = count_imgs()
    r = run("step1_dedup.py", "--root", str(root), "--dry-run")

    ok("退出码为 0", r.returncode == 0, f"rc={r.returncode}")
    rows = read_log(root, "step1_去重日志.csv")
    ok("生成了去重日志", rows is not None)
    if rows:
        kept = [x for x in rows if x.get("动作") == "保留"]
        pending = [x for x in rows if x.get("动作", "").startswith("待删除")]
        ok("识别出 1 组重复（1 保留 + 2 待删）", len(kept) == 1 and len(pending) == 2,
           f"保留 {len(kept)} / 待删 {len(pending)}")
        ok("待删条目标注了 dry-run", all("dry-run" in x["动作"] for x in pending))

    after = count_imgs()
    ok("dry-run 一个图片都没删", len(before) == len(after),
       f"{len(before)} → {len(after)}")

    print("\n[step1 真跑：只删重复的那两份]")
    r = run("step1_dedup.py", "--root", str(root))
    ok("退出码为 0", r.returncode == 0, f"rc={r.returncode}")
    imgs = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() == ".jpg"]
    ok("5 张图剩下 3 张", len(imgs) == 3, f"剩 {len(imgs)} 张")
    ok("保留的那份还在", (root / "DCIM" / "IMG_001.jpg").exists())

    print("\n[step3：生成两份报告]")
    # step3 需要真实可解码图片，这里换成 Pillow 生成的
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("  SKIP  未安装 Pillow，跳过 step3（CI 里会装）")
    else:
        shutil.rmtree(root)
        root.mkdir()
        (root / "DCIM").mkdir()
        for i in range(3):
            im = Image.new("RGB", (320, 240), (40 + i * 10, 90, 140))
            dr = ImageDraw.Draw(im)
            dr.rectangle([20, 20, 200 + i * 10, 160], fill=(200, 120, 60))
            dr.ellipse([120, 100, 300, 220], fill=(60, 160, 200))
            im.save(root / "DCIM" / f"P{i}.jpg", quality=90)
        # 同一张图的缩小版，应当被归入相似组
        im = Image.open(root / "DCIM" / "P0.jpg")
        im.resize((160, 120)).save(root / "DCIM" / "P0_small.jpg", quality=90)

        r = run("step3_reports.py", "--root", str(root))
        ok("退出码为 0", r.returncode == 0, f"rc={r.returncode}")
        rep_sim = root / "相似图报告.md"
        rep_cand = root / "无意义图片候选清单.md"
        ok("生成了相似图报告", rep_sim.exists())
        ok("生成了候选清单", rep_cand.exists())
        if rep_sim.exists():
            text = rep_sim.read_text(encoding="utf-8")
            ok("报告里写进了相似组", "组 1" in text, f"{len(text)} 字符")
            ok("报告声明了未删除", "未删除" in text)

    print("\n[step2 --dry-run：转换但不删原 HEIC]")
    try:
        import pillow_heif
        from PIL import Image, ImageDraw
        pillow_heif.register_heif_opener()
    except ImportError:
        print("  SKIP  未安装 pillow-heif，跳过 step2")
    else:
        shutil.rmtree(root)
        root.mkdir()
        for i in range(3):
            im = Image.new("RGB", (320, 240), (50 + i * 30, 100, 150))
            ImageDraw.Draw(im).ellipse([60, 40, 240, 200], fill=(220, 140, 60))
            im.save(root / f"H{i}.heic", format="HEIF", quality=90)

        run("step1_dedup.py", "--root", str(root), "--dry-run")
        heic_before = sorted(p.name for p in root.glob("*.heic"))
        r = run("step2_convert.py", "--root", str(root), "--dry-run")
        heic_after = sorted(p.name for p in root.glob("*.heic"))
        jpgs = sorted(p.name for p in root.rglob("*.jpg"))

        ok("退出码为 0", r.returncode == 0, f"rc={r.returncode}")
        ok("dry-run 保留了全部原 HEIC", heic_before == heic_after,
           f"{len(heic_before)} → {len(heic_after)}")
        ok("JPG 已正常生成", len(jpgs) == 3, f"{jpgs}")
        ok("输出里提示了原文件保留", "全部保留" in r.stdout)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n结果：{pass_count} 通过 / {fail_count} 失败\n")
sys.exit(1 if fail_count else 0)
