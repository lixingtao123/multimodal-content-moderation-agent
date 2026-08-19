#!/usr/bin/env python3
"""下载 OutSafe-Bench 数据集到本地（绕过 HF snapshot 缓存的超长文件名问题）。

背景：
  数据集 Dttt-chowhound/OutSafe-Bench 中有 10 个文件的文件名 UTF-8 编码
  超过 Linux 单文件名 255 字节上限，官方 snapshot_download 会在 .cache
  中创建 "<name>.<hash>.incomplete" 临时文件，必然触发 OSError: File name too long。

方案：
  用 requests 直接 HTTP 流式下载到最终目标路径（不经过 HF 缓存），
  已存在的文件自动跳过（支持断点续传）。对超长文件名的文件做截断命名，
  并记录原路径 -> 本地路径映射到 outsafe_bench_rename_map.json。
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from huggingface_hub import HfApi, hf_hub_url

REPO_ID = "Dttt-chowhound/OutSafe-Bench"
REPO_TYPE = "dataset"
REVISION = "main"
LOCAL_DIR = "/workspace/data/OutSafe-Bench"
RENAME_MAP_FILE = os.path.join(LOCAL_DIR, "_rename_map.json")

# Linux 单文件名上限 255 字节，留安全余量
MAX_NAME_BYTES = 200
# 扩展名最长长度（如 .jpeg = 5）
MAX_EXT_BYTES = 10

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OutSafe-Bench-downloader"})


def truncate_name(orig_path: str) -> str:
    """对超长文件名的文件做截断，保留目录与扩展名。"""
    parts = orig_path.split("/")
    dirname = "/".join(parts[:-1])
    fname = parts[-1]
    ext = os.path.splitext(fname)[1]
    stem = fname[: -len(ext)]
    ext = ext[:MAX_EXT_BYTES]

    # 二分收缩 stem 直到满足字节限制
    lo, hi = 0, len(stem)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = stem[:mid] + ext
        if len(candidate.encode("utf-8")) <= MAX_NAME_BYTES:
            lo = mid
        else:
            hi = mid - 1
    new_name = stem[:lo] + ext
    return f"{dirname}/{new_name}" if dirname else new_name


def download_one(args) -> tuple[str, str | None]:
    """下载单个文件，返回 (repo_path, local_path 或 None)。

    None 表示跳过（已存在）或最终失败（抛出时由外层处理）。
    """
    repo_path, local_path = args

    # 已存在则跳过（断点续传）
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return (repo_path, None)

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    url = hf_hub_url(REPO_ID, repo_path, repo_type=REPO_TYPE, revision=REVISION)

    # 临时文件用短名，避免超长
    tmp_path = local_path + ".part"
    for attempt in range(3):
        try:
            with SESSION.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
            os.replace(tmp_path, local_path)
            return (repo_path, local_path)
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return (repo_path, None)


def main() -> None:
    api = HfApi()
    files = [
        f for f in api.list_repo_files(REPO_ID, repo_type=REPO_TYPE, revision=REVISION)
        if f != ".gitattributes"
    ]
    print(f"远端共 {len(files)} 个文件")

    jobs = []
    rename_map = {}
    for repo_path in files:
        local_path = os.path.join(LOCAL_DIR, repo_path)
        # 纯文件名（basename）超过 Linux 255 字节上限：截断
        if len(repo_path.rsplit("/", 1)[-1].encode("utf-8")) > MAX_NAME_BYTES:
            new_rel = truncate_name(repo_path)
            local_path = os.path.join(LOCAL_DIR, new_rel)
            rename_map[repo_path] = new_rel
        jobs.append((repo_path, local_path))

    if rename_map:
        with open(RENAME_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(rename_map, f, ensure_ascii=False, indent=2)
        print(f"⚠️  超长文件名 {len(rename_map)} 个，映射表已写入 {RENAME_MAP_FILE}")

    done = 0
    failed = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures = {pool.submit(download_one, j): j[0] for j in jobs}
        for fut in as_completed(futures):
            repo_path = futures[fut]
            try:
                repo_path, local_path = fut.result()
                done += 1
                if done % 50 == 0:
                    print(f"  进度 {done}/{len(jobs)}", flush=True)
            except Exception as e:
                failed.append((repo_path, str(e)))

    print(f"\n完成：成功 {done}/{len(jobs)}")
    if failed:
        print("失败文件：")
        for p, e in failed[:20]:
            print(f"  {p}: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
