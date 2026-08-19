"""
快车道本地小模型（R19·M3）— qwen2.5 本地部署（Ollama）

用户决策：快车道小模型用 qwen2.5 本地部署（不用规则评分器伪小模型）。
  - qwen2.5:7b（Ollama GGUF, 4.7GB），GPU 推理 ~1.5s/短文本
  - 接口遵循 CascadeRouter.small_client 契约: async judge(text) -> dict
  - 判定 PASS 且高置信 → 直接采纳（省大模型成本）
  - 判定 REJECT/REVIEW → 直接采纳（快车道出结论）
  - 低置信/无输出 → needs_upgrade=True（升级大模型，防漏判）
"""
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_BASE_URL = "http://localhost:11434"
UPGRADE_CONFIDENCE = 0.6  # REJECT/REVIEW 低于此置信度升级大模型
PASS_CONFIDENCE = 0.8     # PASS 需高置信才直接放行（R20 防漏）

SYSTEM_PROMPT = (
    "你是一名内容安全审核员。判断以下文本是否含有违规内容。"
    "违规类型仅限：politics(政治敏感), porn(色情低俗), violence(暴力恐怖), "
    "false_info(虚假信息), harassment(辱骂骚扰), advertisement(广告引流), "
    "privacy(隐私窃取), discrimination(歧视偏见), crime(违法犯罪), "
    "ethics(道德伦理), health(身心健康), copyright(版权侵权)。"
    "只输出JSON，不要多余文字："
    '{"decision": "PASS或REJECT或REVIEW", "violation_type": "none或上面类型之一", '
    '"confidence": 0到1的小数, "reason": "10字以内理由"}'
)


class QwenLocalJudge:
    """qwen2.5 本地小模型判定器（Ollama）"""

    def __init__(self, model: str = None, base_url: str = None):
        # R20: base_url/model 改为 settings 配置驱动（可被 OLLAMA_BASE_URL/OLLAMA_MODEL
        # 环境变量覆盖），读取失败回退类默认值。
        if model is None or base_url is None:
            try:
                from common.config import get_settings
                s = get_settings()
                model = model or s.ollama_model
                base_url = base_url or s.ollama_base_url
            except Exception:
                pass
        self.model = model or DEFAULT_MODEL
        self.base_url = base_url or DEFAULT_BASE_URL

    # ---- Ollama 调用（httpx 异步） ----
    async def _generate(self, text: str) -> Optional[str]:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.base_url}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": f"{SYSTEM_PROMPT}\n\n文本：{text[:800]}",
                        "stream": False,
                        "options": {"temperature": 0.1, "num_predict": 200},
                        "keep_alive": "30m",  # 保持模型加载，避免反复重载
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "")
        except Exception as e:
            logger.warning(f"[qwen_judge] ollama 调用失败: {e}")
            return None

    @staticmethod
    def _parse(response: str) -> Optional[dict]:
        """从 ollama 响应提取 JSON（容忍前后杂散文本/代码块）"""
        if not response:
            return None
        m = re.search(r"\{.*\}", response, re.DOTALL)
        if not m:
            return None
        try:
            d = json.loads(m.group(0))
            return {
                "decision": str(d.get("decision", "")).upper(),
                "violation_type": d.get("violation_type", "none"),
                "confidence": float(d.get("confidence", 0.0)),
                "reason": str(d.get("reason", "")),
            }
        except Exception:
            return None

    async def judge(self, text: str) -> dict:
        """小模型判定。返回 CascadeRouter.small_client 契约。"""
        if not text or not text.strip():
            return {"decision": "PASS", "confidence": 0.99, "needs_upgrade": False}

        raw = await self._generate(text)
        parsed = self._parse(raw) if raw else None
        if parsed is None:
            # qwen 不可用/无输出 → 升级大模型（诚实降级，不猜测）
            return {"decision": "UNKNOWN", "confidence": 0.0, "needs_upgrade": True,
                    "reason": "qwen2.5 本地模型不可用"}

        decision = parsed["decision"]
        if decision not in ("PASS", "REJECT", "REVIEW"):
            decision = "UNKNOWN"
        confidence = parsed["confidence"]
        violation_type = parsed["violation_type"]

        # R20 防漏：7B 模型对弱信号违规（隐私/歧视/虚假信息）可能高置信误判 PASS。
        # 判安全却标了违规类型=矛盾信号 → 升级；PASS 置信不足 0.8 → 升级。
        # REJECT/REVIEW 低置信 → 升级（避免以不可靠的高风险结论直接拦截）。
        if decision == "UNKNOWN":
            needs_upgrade = True
        elif decision == "PASS":
            needs_upgrade = (confidence < PASS_CONFIDENCE) or (
                violation_type not in (None, "none"))
        else:
            needs_upgrade = confidence < UPGRADE_CONFIDENCE

        return {
            "decision": decision,
            "confidence": confidence,
            "needs_upgrade": needs_upgrade,
            "violation_type": violation_type,
            "reason": parsed["reason"],
            "model": self.model,
            "used_small": True,
        }
