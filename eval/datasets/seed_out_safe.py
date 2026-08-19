"""
OutSafe 真实案例增量灌入 Chroma（R4·G1）

设计（用户硬约束）：
- **绝不清空已有模拟数据**（clear_first 默认 False）
- 真实案例 metadata 标记 source_dataset="out_safe" / ground_truth="confirmed" / no_decay=True
  → 检索时来源加权优先（confirmed > out_safe > simulated），且不随时间衰减

v1 范围：文本样本（4200 条：中文 1800 + 英文 2400）。模态（图/视/音）在 R5 用预标注文本灌入。

运行（需 PYTHONPATH=/workspace:/workspace/src/backend）:
    python eval/datasets/seed_out_safe.py --limit 100
"""
import argparse
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def build_metadata(
    violation_type: str,
    modality: str = "text",
    language: str = "zh",
    decision: str = "REVIEW",
) -> dict:
    """组装 Chroma metadata（供单测与灌入共用）"""
    return {
        "violation_type": violation_type,
        "decision": decision,
        "modality": modality,
        "language": language,
        # G1/G2/G3: 真实数据优先 + 不衰减
        # R19 修复: 补 source 字段（来源加权按 metadata.source 匹配）
        "source": "out_safe",
        "source_dataset": "out_safe",
        "ground_truth": "confirmed",
        "no_decay": True,
        "timestamp": time.time(),
    }


def collect_text_samples(
    root_dir: str,
    limit_per_lang: Optional[int] = None,
) -> list:
    """读取 OutSafe 中文+英文文本，组装灌入样本（含 metadata）。"""
    from eval.datasets.out_safe_loader import OutSafeDatasetLoader

    loader = OutSafeDatasetLoader(root_dir)
    samples = []
    for lang in ("zh", "en"):
        texts = loader.load_text(lang)
        if limit_per_lang:
            # 按类别均匀抽样
            from collections import defaultdict
            by_cat = defaultdict(list)
            for s in texts:
                by_cat[s.category].append(s)
            picked = []
            for cat, lst in by_cat.items():
                picked.extend(lst[: max(1, limit_per_lang // max(len(by_cat), 1))])
            texts = picked
        for s in texts:
            samples.append({
                "id": s.id,
                "content": s.content,
                "metadata": build_metadata(s.violation_type, modality="text", language=s.language),
            })
    return samples


async def import_to_chromadb(
    root_dir: str,
    limit_per_lang: Optional[int] = None,
    clear_first: bool = False,
    batch_size: int = 100,
) -> int:
    """增量灌入文本案例到 Chroma（默认保留模拟数据）。返回灌入条数。"""
    from memory.chroma_service import get_chroma_service

    chroma = get_chroma_service()
    await chroma.connect()

    if clear_first and chroma.collection is not None:
        ids = chroma.collection.get(limit=100000).get("ids", [])
        if ids:
            chroma.collection.delete(ids=ids)
            logger.warning(f"⚠️ 已清空 {len(ids)} 条现有案例（仅当 clear_first=True）")

    samples = collect_text_samples(root_dir, limit_per_lang)
    if not samples:
        logger.warning("无样本可灌入，请检查 root_dir")
        return 0

    count = 0
    for i in range(0, len(samples), batch_size):
        batch = samples[i:i + batch_size]
        chroma.collection.add(
            ids=[s["id"] for s in batch],
            documents=[s["content"] for s in batch],
            metadatas=[s["metadata"] for s in batch],
        )
        count += len(batch)
        logger.info(f"已灌入 {count}/{len(samples)} 条 (source=out_safe)")
    logger.info(f"完成：共灌入 {count} 条真实文本案例到 moderation_cases（模拟数据保留）")
    return count


def main():
    parser = argparse.ArgumentParser(description="OutSafe 真实案例增量灌入 Chroma")
    parser.add_argument("--root", default=None, help="OutSafe-Bench 根目录（默认自动定位）")
    parser.add_argument("--limit", type=int, default=None, help="每种语言限制条数（按类别均匀抽样）")
    parser.add_argument("--clear-first", action="store_true", help="⚠️ 危险：先清空现有案例（默认保留模拟）")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.clear_first:
        confirm = input("确认要清空现有 Chroma 案例吗？输入 yes 继续: ")
        if confirm != "yes":
            print("已取消")
            return
    n = asyncio.run(import_to_chromadb(args.root, limit_per_lang=args.limit, clear_first=args.clear_first))
    print(f"灌入完成：{n} 条")


if __name__ == "__main__":
    main()
