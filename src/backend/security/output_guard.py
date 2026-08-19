"""
Output Guard v1.0 — LLM 输出安全防护

检测LLM输出中的异常:
  1. 格式异常: 返回了非 JSON 内容 (可能被注入操纵)
  2. 置信度异常: 违规判定但置信度为0 (矛盾)
  3. 内容异常: LLM输出中包含注入指令回显
  4. 跳变异常: 短时间内违规类型频繁跳变 (批量攻击)

技术参考:
  - Garak (NVIDIA, 2024): LLM Vulnerability Scanner
  - NeMo Guardrails (NVIDIA, 2024): LLM Output Guardrails
"""
import re
import logging
from typing import Dict, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


@dataclass
class OutputGuardResult:
    """输出安全检测结果"""
    is_valid: bool
    anomaly_type: str     # none / format_error / confidence_contradiction / content_leak / pattern_burst
    detail: str = ""
    corrected_output: Optional[Dict] = None


class OutputGuard:
    """
    LLM 输出安全卫士

    在每次 LLM 调用后检测输出异常并修正.
    纯规则驱动, 0额外API开销.
    """

    # 输出格式异常检测
    INJECTION_ECHO_PATTERNS = [
        # 注入指令回显
        r"(?:忽略(?:之前的)?指令|新的系统指令|新的任务|DAN\s*mode)",
        r"<\|im_start\|>|<\|im_end\|>",
        r"\[SYSTEM\].*\[/SYSTEM\]",
        # 奇怪的判定行为
        r"violation_type.{0,10}:\s*none.*confidence.{0,10}:\s*0\.(?:99|98|97)",
    ]

    # 置信度矛盾模式
    CONTRADICTION_PATTERNS = [
        # violation_type 不是 none，但 confidence 接近0 (矛盾)
        (r'"violation_type"\s*:\s*"(?!none)[^"]*"\s*,\s*"confidence"\s*:\s*0\.0[0-2]', "high_violation_zero_conf"),
        # violation_type 是 none，但 confidence 很高 (矛盾)
        (r'"violation_type"\s*:\s*"none".*"confidence"\s*:\s*0\.(?:8|9)', "none_with_high_conf"),
    ]

    def __init__(self):
        # 防批量攻击: 跟踪违规类型跳变频率
        self._type_history: Dict[str, list] = defaultdict(list)
        self._max_history = 100

    def validate(
        self,
        raw_output: str,
        parsed_result: Dict,
        content_id: str = "",
    ) -> OutputGuardResult:
        """
        验证 LLM 输出安全性

        Args:
            raw_output: LLM原始输出文本
            parsed_result: 解析后的结构化结果
            content_id: 内容ID (用于跳变追踪)

        Returns:
            OutputGuardResult
        """
        # 1. 格式异常检测
        format_check = self._check_format(raw_output)
        if not format_check["valid"]:
            return OutputGuardResult(
                is_valid=False,
                anomaly_type="format_error",
                detail=format_check["detail"],
            )

        # 2. 置信度矛盾检测
        conf_check = self._check_confidence_contradiction(raw_output)
        if conf_check:
            return OutputGuardResult(
                is_valid=False,
                anomaly_type="confidence_contradiction",
                detail=conf_check,
                corrected_output=self._correct_contradiction(parsed_result, conf_check),
            )

        # 3. 注入回显检测
        echo_check = self._check_injection_echo(raw_output)
        if echo_check:
            logger.warning(f"OutputGuard: injection echo detected — {echo_check}")
            return OutputGuardResult(
                is_valid=False,
                anomaly_type="content_leak",
                detail=echo_check,
            )

        # 4. 跳变检测
        if content_id:
            burst_check = self._check_pattern_burst(parsed_result, content_id)
            if burst_check:
                logger.warning(f"OutputGuard: pattern burst detected — {burst_check}")

        return OutputGuardResult(is_valid=True, anomaly_type="none")

    def _check_format(self, raw: str) -> Dict:
        """检测输出格式是否正常"""
        if not raw or len(raw) < 5:
            return {"valid": False, "detail": "空输出或输出过短"}

        # 检查是否明显被注入操纵 (输出了纯文本而非JSON)
        if not any(c in raw for c in "{}"):
            # 不是 JSON — 可能被注入
            return {"valid": False, "detail": "输出不含JSON结构，可能被注入操纵"}

        return {"valid": True, "detail": ""}

    def _check_confidence_contradiction(self, raw: str) -> Optional[str]:
        """检测置信度与判定结果的矛盾"""
        for pattern, desc in self.CONTRADICTION_PATTERNS:
            if re.search(pattern, raw, re.IGNORECASE):
                return f"置信度矛盾: {desc}"
        return None

    def _check_injection_echo(self, raw: str) -> Optional[str]:
        """检测输出中是否有注入指令回显"""
        for pattern in self.INJECTION_ECHO_PATTERNS:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                return f"注入回显: 检测到 '{match.group(0)[:60]}'"
        return None

    def _check_pattern_burst(self, result: Dict, content_id: str) -> Optional[str]:
        """
        检测短时间内的违规类型跳变 (批量攻击)
        如果相同 violation_type 在短时间内反复出现，可能是攻击者在试探边界
        """
        vt = result.get("violation_type", "none")
        if vt == "none":
            return None

        now = datetime.now()
        self._type_history[vt].append((now, content_id))

        # 清理旧记录 (超过5分钟)
        cutoff = now - timedelta(minutes=5)
        self._type_history[vt] = [
            (t, cid) for t, cid in self._type_history[vt] if t > cutoff
        ]
        # 限制历史长度
        if len(self._type_history[vt]) > self._max_history:
            self._type_history[vt] = self._type_history[vt][-self._max_history:]

        # 短时间内同一类型超过阈值 → 可能批量攻击
        recent = len(self._type_history[vt])
        if recent >= 20 and vt not in ("advertisement",):
            return f"短时间大批量检测: {vt} 类型 {recent} 次/5分钟 (疑似批量攻击)"

        return None

    def _correct_contradiction(self, result: Dict, contradiction: str) -> Dict:
        """纠正置信度矛盾"""
        corrected = dict(result)
        vt = corrected.get("violation_type", "none")
        conf = corrected.get("confidence", 0.0)

        if vt != "none" and conf < 0.1:
            # 有违规但置信度极低 → 降低违规判定
            logger.info(f"OutputGuard: correcting contradiction — {vt} conf={conf:.3f} → none")
            corrected["violation_type"] = "none"
            corrected["confidence"] = max(0.0, conf)
            corrected["outputguard_corrected"] = True
        elif vt == "none" and conf > 0.8:
            # 正常但置信度极高 → 这是矛盾的(正常不需要高置信度)
            logger.info(f"OutputGuard: correcting contradiction — none conf={conf:.3f} → capped")
            corrected["confidence"] = min(0.3, conf)
            corrected["outputguard_corrected"] = True

        return corrected


# 全局单例
_output_guard: Optional[OutputGuard] = None


def get_output_guard() -> OutputGuard:
    global _output_guard
    if _output_guard is None:
        _output_guard = OutputGuard()
    return _output_guard
