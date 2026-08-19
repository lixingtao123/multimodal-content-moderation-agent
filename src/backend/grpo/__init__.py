"""
GRPO (Group Relative Policy Optimization) 模块

大厂级内容风控强化学习优化框架：
- 多智能体辩论产生相对排名
- 相对排名作为奖励信号
- PPO/GRPO 优化审核策略
- A/B 测试验证效果

参考：
- DeepSeek GRPO 论文
- 字节跳动内容安全强化学习框架
- 阿里安全「对抗攻防 + 强化学习」双轮驱动
"""
from .grpo_service import get_grpo_service, GRPOService

__all__ = ["get_grpo_service", "GRPOService"]
