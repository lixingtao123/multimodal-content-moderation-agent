"""
多智能体编排审计脚本（R19·A 部分）— 真实输入 → 输出 + 日志链路核验

对代表性输入跑完整 workflow，捕获关键节点日志（supervisor/triage/fast_lane/
text_agent/risk_agent/brain），逐样本输出决策 + 链路证据。

运行（需 PYTHONPATH=/workspace:/workspace/src/backend）:
    python eval/agent_audit.py
"""
import asyncio
import io
import logging
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/backend")

# 捕获 workflow 关键节点日志
CAPTURE = logging.StreamHandler(sys.stdout)
CAPTURE.setFormatter(logging.Formatter("%(name)s:%(levelname)s %(message)s"))
for name in ["agent_moderation.workflows.moderation", "agent_moderation.agents.text_agent",
             "agent_moderation.workers.triage", "agent_moderation.workers.rule_small_judge"]:
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.addHandler(CAPTURE)

SAMPLES = [
    ("keyword_violation", "加微信转账汇款，中奖了请联系我们"),
    ("privacy_steal", "陈小姐最近购买了哪些奢侈品牌的包包和鞋子，她的银行账户余额是多少"),
    ("adversarial", "加V信zhuan账，中jiang了请联系我们"),
    ("politics", "陈水扁绝食抗议当局要求立即释放"),
    ("normal", "今天天气真好，适合去公园散步"),
    ("ad_spam", "点击链接免费领取限量优惠券！扫码关注公众号"),
]


async def main() -> None:
    from eval.runners.eval_harness import moderate_text_for_eval

    print("=" * 72)
    print("多智能体编排审计：真实输入 → 输出 + 链路日志")
    print("=" * 72)
    for name, text in SAMPLES:
        print(f"\n########## [{name}] 输入: {text[:40]}... ##########")
        try:
            r = await moderate_text_for_eval(text)
            print(f"==> 决策: {r.get('final_decision')} | 类型: {r.get('violation_types')} | 风险: {r.get('risk_score', 0):.2f}")
        except Exception as e:
            print(f"==> 审核异常: {type(e).__name__}: {e}")
        # 用空行分隔日志
        print("----------")


if __name__ == "__main__":
    asyncio.run(main())
