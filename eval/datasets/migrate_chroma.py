"""
Chroma v1→v2 迁移（R19）— 统一 embedding 维度 512→1024

背景：旧 collection 为 512 维（历史 embedding 建立），当前系统 embedding 为
1024 维，导致写入报 "expecting 512 got 1024"。
方案：新建 v2 collection（1024 维），将旧 collection 数据导出后重新嵌入灌入。
旧 collection 保留不删（模拟数据不清空的硬约束）。

运行（需 PYTHONPATH=/workspace:/workspace/src/backend）:
    python eval/datasets/migrate_chroma.py
"""
import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "backend"))
os.chdir(PROJECT_ROOT)


async def main() -> None:
    from memory.chroma_service import get_chroma_service
    import chromadb

    svc = get_chroma_service()
    client = svc.client if svc.client else None
    if client is None:
        from chromadb import PersistentClient
        client = PersistentClient(path=os.path.join(PROJECT_ROOT, "data", "chroma"))
    await svc.connect()

    for old_name, new_name in [("moderation_cases", "moderation_cases_v2"),
                               ("core_memory", "core_memory_v2")]:
        try:
            old = client.get_collection(old_name)
        except Exception:
            logging.info(f"旧 collection {old_name} 不存在，跳过")
            continue
        count = old.count()
        logging.info(f"迁移 {old_name} → {new_name}: {count} 条")
        if count == 0:
            continue
        # 分批读取全部文档与 metadata
        batch = 100
        for offset in range(0, count, batch):
            got = old.get(limit=batch, offset=offset, include=["documents", "metadatas"])
            ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
            if not ids:
                continue
            # 清洗 metadata：去除 Chroma 不允许的非法类型
            clean_metas = []
            for m in metas:
                cm = {k: v for k, v in (m or {}).items() if isinstance(v, (str, int, float, bool)) or v is None}
                clean_metas.append(cm)
            new_coll = client.get_or_create_collection(new_name, embedding_function=svc.embedding_fn)
            new_coll.upsert(ids=ids, documents=docs, metadatas=clean_metas)
        logging.info(f"  {old_name} 迁移完成 → {client.get_collection(new_name).count()} 条")

    # 最终验证
    v2 = client.get_collection("moderation_cases_v2")
    core2 = client.get_collection("core_memory_v2")
    logging.info(f"v2 最终状态: moderation_cases_v2={v2.count()}  core_memory_v2={core2.count()}")


if __name__ == "__main__":
    asyncio.run(main())
