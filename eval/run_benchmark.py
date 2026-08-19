"""
Benchmark CLI — 运行 7 Track 评测并固化 baseline（R5·P1 配套入口）

用法（在项目根目录）:
    PYTHONPATH=src/backend python eval/run_benchmark.py                # 全部 track
    PYTHONPATH=src/backend python eval/run_benchmark.py --tracks T1_intent T3_rag
    PYTHONPATH=src/backend python eval/run_benchmark.py --smoke         # 小规模冒烟（快）

输出:
    eval/baselines/latest.json   本轮实测报告
    eval/baselines/baseline.json 基线（--save-baseline 时覆盖）
"""
import argparse
import asyncio
import json
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)  # 使 `eval` 包可导入
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src", "backend"))

# R22: 本地 eval 从 src/backend/.env 加载真实密钥与连接地址（与 uvicorn 同源）。
# 否则 config.py 在 /workspace 运行时读根目录 .env（Docker 模式占位符），
# 导致 QWEN_VL_API_KEY 为占位符 → VL 401 → T5 多模态拦截率失真。
# 仅当环境变量未显式设置时注入，显式 env 优先。
_BACKEND_ENV = os.path.join(PROJECT_ROOT, "src", "backend", ".env")
if os.path.exists(_BACKEND_ENV):
    for line in open(_BACKEND_ENV, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and v and not os.environ.get(k):
            os.environ.setdefault(k, v)

os.chdir(PROJECT_ROOT)


async def main(args: argparse.Namespace) -> None:
    from eval.runners.harness_v2 import EvalContext, EvalHarnessV2
    from eval.runners.tracks_v2 import build_default_tracks
    from eval.runners.eval_harness import moderate_text_for_eval

    if not os.environ.get("DEEPSEEK_API_KEY"):
        logging.warning("DEEPSEEK_API_KEY 未设置，T1 将降级为 skipped")

    ctx = EvalContext(
        moderate_func=moderate_text_for_eval,
        sample_per_cat=args.sample_per_cat,
        negative_count=args.negative_count,
        config={
            "t3_candidates": args.t3_candidates,
            "t3_queries": args.t3_queries,
            "t3_lang": args.t3_lang,
            "t3_dense": True,
            "t3_rerank": True,
        },
    )
    harness = EvalHarnessV2(context=ctx)
    harness.register_tracks(build_default_tracks())

    tracks = args.tracks or None
    logging.info(f"运行 Tracks: {tracks or '全部'}")
    results = await harness.run(track_filter=tracks)

    # 机读报告
    report = harness.report(results)
    os.makedirs(os.path.join(PROJECT_ROOT, "eval", "baselines"), exist_ok=True)
    latest_path = os.path.join(PROJECT_ROOT, "eval", "baselines", "latest.json")
    harness.save_report(results, latest_path)
    logging.info(f"报告已写入 {latest_path}")

    # 与基线对比
    baseline_path = os.path.join(PROJECT_ROOT, "eval", "baselines", "baseline.json")
    if os.path.exists(baseline_path):
        baseline = harness.load_baseline(baseline_path)
        cmp = harness.compare(results, baseline)
        logging.info(f"回归检测: {len(cmp['regressions'])} 处回退")
        for reg in cmp["regressions"]:
            logging.warning(f"  ✗ {reg}")
        if args.save_baseline:
            harness.save_baseline(results, baseline_path)
            logging.info("已覆盖 baseline.json")
    elif args.save_baseline:
        harness.save_baseline(results, baseline_path)
        logging.info(f"首次基线已写入 {baseline_path}")

    # 汇总输出
    print()
    print("=" * 70)
    print("Benchmark 汇总")
    print("=" * 70)
    for name in sorted(results):
        r = results[name]
        if r.status == "ok":
            flat = {k: (round(v, 4) if isinstance(v, float) else v)
                    for k, v in r.metrics.items() if isinstance(v, (int, float))}
            print(f"  ✅ {name}  samples={r.samples}  {flat}")
        else:
            print(f"  ⚠️ {name}  status={r.status}  note={r.note}")
    print(f"\n总耗时: {sum(r.duration for r in results.values()):.1f}s")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Benchmark CLI")
    p.add_argument("--tracks", nargs="*", default=None, help="要运行的 track 名")
    p.add_argument("--all", action="store_true", help="运行全部 track（默认行为，与 --tracks 互斥）")
    p.add_argument("--sample-per-cat", type=int, default=20, help="T1 每类抽样数")
    p.add_argument("--negative-count", type=int, default=200, help="T1 负样本数")
    p.add_argument("--t3-candidates", type=int, default=20)
    p.add_argument("--t3-queries", type=int, default=3)
    p.add_argument("--t3-lang", default="zh")
    p.add_argument("--smoke", action="store_true", help="冒烟模式（极小样本）")
    p.add_argument("--save-baseline", action="store_true", help="覆盖 baseline.json")
    args = p.parse_args()

    if args.smoke:
        args.sample_per_cat = 2
        args.negative_count = 8
        args.t3_candidates = 5
        args.t3_queries = 2

    asyncio.run(main(args))
