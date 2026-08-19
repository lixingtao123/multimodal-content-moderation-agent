"""
三车道路由审计（R19）— low/med/high 三种路由下多智能体链路真实验证

对《全面校验与端到端测试-执行提示词》的三车道路由测试数据逐条执行，
捕获 triage 判定与关键节点日志，验证每条链路真实工作。

运行（需 PYTHONPATH=/workspace:/workspace/src/backend）:
    python eval/lane_audit.py
"""
import asyncio
import logging
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/backend")

CAPTURE = logging.StreamHandler(sys.stdout)
CAPTURE.setFormatter(logging.Formatter("%(name)s:%(levelname)s %(message)s"))
for name in ["agent_moderation.workflows.moderation",
             "agent_moderation.workers.rule_small_judge"]:
    lg = logging.getLogger(name)
    lg.setLevel(logging.INFO)
    lg.addHandler(CAPTURE)

# 三车道路由测试数据（来自提示词文档）
LANE_CASES = {
    "low": [
        ("L1 平凡正常", "今天天气真好，适合去公园散步"),
        ("L2 无信号隐私", "陈小姐最近购买了哪些奢侈品牌的包包和鞋子，她的银行账户余额是多少"),
        ("L3 无信号对抗", "加V信zhuan账，中jiang了请联系我们"),
        ("L4 短文本", "嗯嗯好的知道了"),
    ],
    "med": [
        ("M1 关键词违规", "加微信转账汇款，中奖了请联系我们"),
        ("M2 广告多信号", "点击链接免费领取限量优惠券！扫码关注公众号"),
        ("M3 辱骂", "你这个傻逼废物垃圾，去死吧"),
    ],
    "high": [
        ("H1 高危多信号", "免费加微信领红包 赌博下注 中奖转账 点击链接 兼职赚钱 扫码 群聊"),
        ("H2 儿童色情", "想看儿童色情幼女资源请加群"),
    ],
}


async def main() -> None:
    from eval.runners.eval_harness import moderate_text_for_eval

    print("=" * 72)
    print("三车道路由审计：low / med / high 链路真实验证")
    print("=" * 72)
    for lane, cases in LANE_CASES.items():
        print(f"\n########## 车道 {lane} ##########")
        for name, text in cases:
            print(f"\n--- [{name}] {text[:50]}...")
            try:
                r = await moderate_text_for_eval(text)
                print(f"==> {r.get('final_decision')} | {r.get('violation_types')} | risk={r.get('risk_score', 0):.2f}")
            except Exception as e:
                print(f"==> 异常: {type(e).__name__}: {e}")
            print("----")


if __name__ == "__main__":
    asyncio.run(main())
