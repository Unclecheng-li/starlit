"""表情包入库。

用法（在 companion 目录下）：
    python -m scripts.ingest_stickers                  # 用 config 里配的目录
    python -m scripts.ingest_stickers --force          # 全量重建
    python -m scripts.ingest_stickers --dirs "C:/a,C:/b"   # 额外扫这些目录
    python -m scripts.ingest_stickers --vision         # 没情绪前缀的图调模型打标
    python -m scripts.ingest_stickers --report         # 只看统计，不写盘

## 两种入库模式

**文件名模式（默认，优先）**
    文件名形如 `害羞_8E1AA68B.gif`、`亲密_贴纸-1.gif`、`生气_22CA72A3.jpg`，
    前半段就是情绪。直接取用 —— 不调用模型，**又快又准又不花钱**。

**视觉模式（--vision，可选）**
    文件名不带情绪的（比如 `4BA1553DBE5114D32DDBC81509E8B602.gif`），
    才需要调 DeepSeek 看图。这部分通常很少。

## 关于路径

表情包**原地索引，不拷贝**。索引里存绝对路径，所以：
- 省空间
- 但移动或改名了那些文件夹，要重跑一次
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
_HERE = Path(__file__).resolve().parent
# 把 scripts/ 自己从 sys.path 摘掉，避免里面的文件名顶掉标准库
sys.path[:] = [p for p in sys.path if Path(p or ".").resolve() != _HERE]
sys.path.insert(0, str(ROOT))

from app.config import load_config                          # noqa: E402
from app.llm import LLM, _parse_json_loose, guess_mime      # noqa: E402
from app.sticker import FILENAME_EMOTION_MAP, normalize_emotion  # noqa: E402

EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
PREFIX_RE = re.compile(r"^([\u4e00-\u9fffA-Za-z]{1,6})[_\-\s]")

VISION_PROMPT = """这是一张聊天用的表情包/梗图。只输出 JSON：
{"desc": "一句话描述图里的内容与传达的情绪（30字内）",
 "emotions": ["从这些里选1~3个最贴的：开心/兴奋/得意/害羞/卖萌/亲密/温柔/感激/鼓励/平静/认真/疑惑/惊讶/无语/难过/低落/委屈/焦虑/慌张/害怕/生气/不爽/愤怒/疲惫/困倦/崩溃/中性"],
 "tags": ["3~6个检索关键词"]}
图里的字看不清就不要写，别猜。"""


def parse_emotion_from_name(filename: str) -> Tuple[Optional[str], str]:
    """从文件名里取 (情绪, 描述)。

    `害羞_8E1AA68B.gif`   -> ("害羞", "8E1AA68B")
    `亲密_贴纸-1(1).gif`  -> ("亲密", "贴纸-1(1)")
    `4BA1553...AC.gif`    -> (None,   "4BA1553...AC")
    """
    stem = Path(filename).stem
    m = PREFIX_RE.match(stem)
    if not m:
        if stem in FILENAME_EMOTION_MAP:
            return stem, ""
        return None, stem
    head, rest = m.group(1), stem[m.end():]
    if head in FILENAME_EMOTION_MAP:
        return head, rest
    return None, stem


def collect(dirs: List[Path]) -> List[Path]:
    out: List[Path] = []
    seen = set()
    for d in dirs:
        if not d.exists():
            continue
        for p in sorted(d.rglob("*")):
            if p.suffix.lower() in EXTS and str(p) not in seen:
                seen.add(str(p))
                out.append(p)
    return out


def tag_source(path: Path, root: Path) -> Dict[str, Any]:
    """来源标识：顶层目录名 + 子目录名。

    子目录名很有用 —— 比如 `blue archive/星野/` 下的图就是角色本人的表情，
    可以优先发。
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return {"source": root.name, "tags": [root.name]}
    parts = rel.parts
    source = parts[0] if len(parts) > 1 else ""
    sub = parts[1] if len(parts) > 2 else ""
    tags = [root.name]
    if source:
        tags.append(source)
    if sub:
        tags.append(sub)
    return {"source": source or root.name, "tags": tags}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="忽略已有索引，全量重建")
    ap.add_argument("--dirs", default="", help="额外目录，逗号分隔")
    ap.add_argument("--vision", action="store_true", help="无情绪前缀的图调模型打标")
    ap.add_argument("--report", action="store_true", help="只统计，不写盘")
    args = ap.parse_args()

    cfg = load_config()
    roots: List[Path] = [cfg.resolve(cfg.memory.sticker_dir)]
    roots += [Path(d) for d in cfg.sticker.extra_dirs]
    if args.dirs:
        roots += [Path(d.strip()) for d in args.dirs.split(",") if d.strip()]

    uniq: List[Path] = []
    for r in roots:
        if r not in uniq:
            uniq.append(r)

    print("扫描目录：")
    for r in uniq:
        if r.exists():
            n = sum(1 for p in r.rglob("*") if p.suffix.lower() in EXTS)
            print(f"  ✓ {r}  ({n} 张)")
        else:
            print(f"  ✗ {r}  (不存在)")

    files = collect(uniq)
    if not files:
        print("\n没找到任何图片。用 --dirs 指定目录，"
              "或在 config.yaml 的 sticker.extra_dirs 里写死。")
        return

    # 记住每张图属于哪个根目录
    root_of: Dict[str, Path] = {}
    for r in uniq:
        if r.exists():
            for p in r.rglob("*"):
                if p.suffix.lower() in EXTS:
                    root_of.setdefault(str(p), r)

    by_name = 0
    need_vision: List[Path] = []
    index: List[Dict[str, Any]] = []

    for p in files:
        raw, rest = parse_emotion_from_name(p.name)
        meta = tag_source(p, root_of.get(str(p), p.parent))
        if raw:
            by_name += 1
            index.append({
                "file": str(p),
                "desc": " ".join(x for x in (raw, rest) if x),
                "emotions": [normalize_emotion(raw)],
                "raw_emotion": raw,
                "tags": meta["tags"],
                "source": meta["source"],
            })
        elif args.vision:
            need_vision.append(p)
        else:
            # 没前缀又不打标：仍然收进来（归中性），别白丢一张图
            index.append({
                "file": str(p),
                "desc": rest or p.stem,
                "emotions": ["中性"],
                "raw_emotion": "",
                "tags": meta["tags"],
                "source": meta["source"],
            })

    print(f"\n文件名解析成功：{by_name} 张")
    extra = len(files) - by_name
    print(f"无情绪前缀：{extra} 张"
          + (f"（{len(need_vision)} 张待模型打标）" if args.vision else "（归为中性）"))

    if need_vision and not args.report:
        llm = LLM(cfg.llm)
        for i, p in enumerate(need_vision, 1):
            try:
                text = await llm.chat_with_images(
                    VISION_PROMPT, [p.read_bytes()], mimes=[guess_mime(str(p))])
                data = _parse_json_loose(text)
                emos = [normalize_emotion(x) for x in (data.get("emotions") or [])]
                meta = tag_source(p, root_of.get(str(p), p.parent))
                index.append({
                    "file": str(p),
                    "desc": str(data.get("desc", ""))[:120],
                    "emotions": emos or ["中性"],
                    "raw_emotion": " ".join(str(x) for x in (data.get("emotions") or [])),
                    "tags": meta["tags"] + [str(t) for t in (data.get("tags") or [])][:6],
                    "source": meta["source"],
                })
                print(f"  [{i}/{len(need_vision)}] {p.name} -> {emos}")
            except Exception as e:  # noqa: BLE001
                print(f"  [{i}/{len(need_vision)}] {p.name} 失败：{e}")
        await llm.close()

    index = [d for d in index if Path(str(d["file"])).exists()]

    emos = Counter(e for d in index for e in d.get("emotions", []))
    srcs = Counter(d.get("source") or "(无)" for d in index)
    print(f"\n入库合计 {len(index)} 张")
    print(f"  情绪覆盖 {len(emos)} 种：{dict(emos.most_common(12))}")
    print(f"  来源分布：{dict(srcs.most_common(8))}")

    if args.report:
        print("\n（--report 模式，未写盘）")
        return

    index_path = cfg.resolve(cfg.memory.sticker_index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写入 {index_path}")


if __name__ == "__main__":
    asyncio.run(main())
