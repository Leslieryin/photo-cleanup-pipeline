# photo-cleanup-pipeline · 手机照片整理流水线

把「从手机搬出来的几千张杂乱照片」整理干净的四步流水线：**去重 → HEIC 转换 → 相似图报告 → 人工裁决后删除**。每一步都有日志与安全设计，先报告、后动手，绝不静默删你的照片。

> 这个工具来自一次真实整理：两台手机 + 多年导出的照片混在一起，有字节级重复、HEIC 与「假 JPG」、截图表情包缩略图混杂。跑完一遍，混乱的照片目录变成了一份可读的相册。

## 设计原则

1. **能校验的都校验**：HEIC 转 JPG 后重新解码验证完整性与分辨率，通过才删原文件
2. **先报告后删除**：第 3 步只生成 Markdown 报告（相似图组 / 截图 / 超小图候选），第 4 步按你编辑后的清单执行，全程 CSV 日志
3. **可断点续算**：感知哈希每 1000 张存档，中断后重跑自动续
4. **dry-run 常备**：删除类步骤都支持 `--dry-run` 先预演

## 四步流程

| 步骤 | 脚本 | 做什么 | 删除行为 |
|---|---|---|---|
| 1 | `step1_dedup.py` | SHA-256 找字节级重复，按优先级（`--prefer` 目录 > 非回收站 > 文件名干净 > 最早）保留一份 | 直接删副本（支持 `--dry-run`） |
| 2 | `step2_convert.py` | HEIC/HEIF → JPG（质量 95，保 EXIF/ICC），逐张校验 | 校验通过才删原 HEIC |
| 2b | `step2b_misnamed_heic.py` | 自动识别「扩展名是 .jpg 但内容是 HEIC」的文件并原地转正 | 原地替换（先写临时文件再 rename） |
| 3 | `step3_reports.py` | pHash（DCT）感知哈希 + 并查集分组，生成相似图报告与无意义图片候选清单 | **不删除任何文件** |
| 4 | `step4_delete_candidates.py` | 按你编辑后的候选清单删除，可按类别（A~E）筛选 | 按清单删（支持 `--dry-run`） |

## 快速开始

```bash
pip install -r requirements.txt

# 建议先复制一份照片目录做试验，确认无误后再对真目录操作

python step1_dedup.py --root "D:\手机照片" --dry-run        # 预演去重
python step1_dedup.py --root "D:\手机照片"                  # 执行去重
python step2_convert.py --root "D:\手机照片" --limit 20     # 先转 20 张试试
python step2_convert.py --root "D:\手机照片"                # 全量转换
python step2b_misnamed_heic.py --root "D:\手机照片" --dry-run
python step3_reports.py --root "D:\手机照片"                # 生成两份报告（这一步耗时最长）
#   → 编辑 生成的「无意义图片候选清单.md」：删掉你不想删的行
python step4_delete_candidates.py --root "D:\手机照片" --dry-run
python step4_delete_candidates.py --root "D:\手机照片"      # 真正删除
```

所有输出集中在你照片根目录的 `_cleanup/` 下（日志 CSV、清单 JSON、指纹数据），相似图报告与候选清单生成在根目录，方便直接阅读。

## 依赖

- Python 3.10+
- Pillow、pillow-heif（HEIC 解码）、numpy（哈希批量比对）

## 注意

- 第 1、2、2b、4 步会删除/替换文件，**务必先 `--dry-run`，并确认你有备份**
- `.trashed-` 开头（安卓回收站残留）与 `Screenshot/截图` 文件名等规则可在脚本头部调整
- pHash 阈值（默认 8/64）可按报告微调：值越大分组越宽松

## License

MIT
