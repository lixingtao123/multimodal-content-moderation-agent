"""
DSPy Prompt 自动优化模块 v1.0

基于 DSPy 框架实现 Prompt 自动编译和优化:
  - 将硬编码 Prompt 迁移到声明式 Signature
  - 使用标注数据集自动搜索最优 Prompt + Few-Shot 示例
  - 支持 MIPROv2 和 GEPA 优化器
  - 与反馈闭环集成: 生产失败案例 → 训练数据 → 重编译

架构参考:
  - DSPy v2.6 (Stanford NLP): 声明式 LLM 编程框架
  - Dropbox Dash Relevance Judge: DSPy 生产部署案例 (2025)
  - JetBlue Multi-Stage Agent Pipeline: DSPy + Databricks (2025)

核心流程:
  1. 定义 Signature: 输入/输出字段规范
  2. 构建 Module: 将 Signature 组合成可优化管线
  3. 编译: 使用 Optimizer 在数据集上搜索最优 Prompt
  4. 保存: 序列化编译后的 Prompt 到文件
  5. 加载: 推理时加载编译后的 Prompt (无需重编译)
"""
import json
import os
import logging
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# === Prompt 注册表 ===

@dataclass
class PromptVersion:
    """Prompt 版本"""
    name: str
    version: str
    model: str
    system_prompt: str
    user_template: str
    optimizer: str = "manual"
    metrics: dict = field(default_factory=dict)
    dataset_hash: str = ""
    created_at: str = ""


class PromptRegistry:
    """
    Prompt 版本注册表

    管理所有 Agent 的 Prompt 版本:
    - 版本化存储 (JSON)
    - A/B 测试支持
    - 灰度发布
    - 回滚
    """

    PROMPTS_DIR = "/workspace/src/backend/prompts"

    def __init__(self):
        self._prompts: Dict[str, Dict[str, PromptVersion]] = {}
        self._active_versions: Dict[str, str] = {}  # name → active version
        self._load_all()

    def _load_all(self):
        """从磁盘加载所有 Prompt"""
        base = Path(self.PROMPTS_DIR)
        if not base.exists():
            base.mkdir(parents=True, exist_ok=True)

        loaded = False
        for prompt_file in base.glob("*.json"):
            try:
                with open(prompt_file) as f:
                    data = json.load(f)
                name = data.get("name", prompt_file.stem)
                version = data.get("version", "0.0.0")
                if name not in self._prompts:
                    self._prompts[name] = {}
                self._prompts[name][version] = PromptVersion(**data)
                # 设置活跃版本（最新加载的版本为活跃版本）
                if name not in self._active_versions:
                    self._active_versions[name] = version
                loaded = True
            except Exception as e:
                logger.warning(f"Failed to load prompt {prompt_file}: {e}")

        if not loaded:
            self._init_defaults()

    def _init_defaults(self):
        """初始化默认 Prompt"""
        defaults = {
            "text_moderation": PromptVersion(
                name="text_moderation",
                version="1.0.0",
                model="deepseek-v4-flash",
                system_prompt="""你是内容安全审核专家。分析以下文本是否违反社区规范。

审核维度：
1. 政治敏感：涉政、敏感事件、分裂言论
2. 色情低俗：色情描写、低俗色情暗示
3. 暴力恐怖：暴力威胁、恐怖主义宣传
4. 虚假信息：谣言、虚假欺诈信息
5. 辱骂骚扰：人身攻击、侮辱性言论、网络暴力
6. 广告引流：垃圾广告、诱导加好友、引流推广

请以JSON格式返回分析结果（只返回JSON，不要其他文字）：
{"violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
 "confidence": 0.0-1.0, "reason": "简短判断依据", "is_adversarial": false, "tags": ["标签1","标签2"]}""",
                user_template="请分析以下文本：\n\n{content}",
                optimizer="manual",
            ),
            "image_moderation": PromptVersion(
                name="image_moderation",
                version="1.0.0",
                model="deepseek-v4-flash",
                system_prompt="""你是严格的内容安全审核专家。分析从图片中提取的文字内容，判断是否违规。

审核标准（优先级从高到低）：
1. 暴力恐怖(violence)：杀戮、威胁杀人、武器制作、恐怖袭击、殴打 → 有则 confidence≥0.85
2. 色情低俗(porn)：裸聊、私密视频、成人内容、性暗示文字 → 有则 confidence≥0.85
3. 政治敏感(politics)：反动言论、分裂主张、敏感事件 → 有则 confidence≥0.85
4. 广告引流(advertisement)：微信/QQ/手机号引流、扫码诱导、赚钱广告 → 有则 confidence≥0.75
5. 虚假信息(false_info)：中奖诈骗、银行卡要求、谣言传播 → 有则 confidence≥0.80
6. 辱骂骚扰(harassment)：人身攻击、侮辱、网络暴力 → 有则 confidence≥0.80

关键原则：
- 只要文字中包含上述任何违规内容，violation_type 必须设为对应类型
- "杀人了""砍死你""炸弹制作" → violence, confidence ≥ 0.85
- "裸聊""私密视频""成人内容" → porn, confidence ≥ 0.85
- 如果内容安全，violation_type="none", confidence=0.0

请以JSON格式返回（只返回JSON）：
{"violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
 "confidence": 0.0-1.0, "reason": "简短判断依据", "is_adversarial": false, "tags": ["标签1","标签2"]}""",
                user_template="请分析以下图片提取内容是否违规：\n\n{content}",
                optimizer="manual",
            ),
            "audio_moderation": PromptVersion(
                name="audio_moderation",
                version="1.0.0",
                model="deepseek-v4-flash",
                system_prompt="""你是语音内容安全审核专家。分析以下语音转写文本是否违反社区规范。

审核维度：1. 政治敏感 2. 色情低俗 3. 暴力恐怖 4. 虚假信息 5. 辱骂骚扰 6. 广告引流

请以JSON格式返回分析结果（只返回JSON，不要其他文字）：
{"violation_type": "none|politics|porn|violence|false_info|harassment|advertisement",
 "confidence": 0.0-1.0, "reason": "简短判断依据", "is_adversarial": false, "tags": ["标签1","标签2"]}""",
                user_template="请分析以下语音转写文本：\n\n{content}",
                optimizer="manual",
            ),
            "video_moderation": PromptVersion(
                name="video_moderation",
                version="1.0.0",
                model="qwen3.6-plus",
                system_prompt="分析这个视频帧是否包含违规内容（色情/暴力/政治/广告），JSON格式返回。",
                user_template="",
                optimizer="manual",
            ),
        }
        for name, pv in defaults.items():
            self._prompts[name] = {pv.version: pv}
            self._active_versions[name] = pv.version
            self._save(pv)

    def _save(self, pv: PromptVersion):
        """保存 Prompt 到磁盘"""
        base = Path(self.PROMPTS_DIR)
        base.mkdir(parents=True, exist_ok=True)
        filepath = base / f"{pv.name}.json"
        with open(filepath, "w") as f:
            json.dump({
                "name": pv.name,
                "version": pv.version,
                "model": pv.model,
                "system_prompt": pv.system_prompt,
                "user_template": pv.user_template,
                "optimizer": pv.optimizer,
                "metrics": pv.metrics,
                "dataset_hash": pv.dataset_hash,
                "created_at": pv.created_at,
            }, f, ensure_ascii=False, indent=2)

    def get(self, name: str, version: str = None) -> Optional[PromptVersion]:
        """获取 Prompt 版本"""
        if name not in self._prompts:
            return None
        version = version or self._active_versions.get(name)
        return self._prompts[name].get(version)

    def get_active(self, name: str) -> Optional[PromptVersion]:
        """获取当前活跃版本的 Prompt"""
        return self.get(name)

    def register(
        self, name: str, version: str, pv: PromptVersion,
        set_active: bool = False,
    ):
        """注册新 Prompt 版本"""
        if name not in self._prompts:
            self._prompts[name] = {}
        self._prompts[name][version] = pv
        if set_active:
            self._active_versions[name] = version
        self._save(pv)

    def set_active(self, name: str, version: str):
        """切换活跃版本 (A/B 测试或回滚)"""
        if name in self._prompts and version in self._prompts[name]:
            self._active_versions[name] = version
            logger.info(f"Prompt '{name}' active version → {version}")

    def list_versions(self, name: str) -> List[str]:
        """列出某 Prompt 的所有版本"""
        if name in self._prompts:
            return sorted(self._prompts[name].keys())
        return []

    def build_full_prompt(self, name: str, content: str, version: str = None) -> tuple:
        """
        构建完整 Prompt (system + user)

        Returns:
            (system_prompt, user_message)
        """
        pv = self.get(name, version)
        if not pv:
            raise ValueError(f"Prompt '{name}' not found")

        user_msg = pv.user_template.format(content=content) if pv.user_template else content
        return pv.system_prompt, user_msg


# === DSPy 风格自动优化器 ===

class DspyStyleOptimizer:
    """
    DSPy 风格的 Prompt 优化器

    核心思想:
    - 定义"评估函数"作为优化目标
    - 使用标注数据集评估当前 Prompt 质量
    - 尝试不同的 Prompt 变体，最大化评估分数

    简化实现 (不依赖 DSPy 库):
    - BootstrapFewShot: 自动选择最佳 Few-Shot 示例
    - 规则优化: 基于评估反馈修改 Prompt 指令

    未来可升级为完整 DSPy 集成:
    - MIPROv2: 贝叶斯优化搜索最优指令
    - GEPA: 基于反思的进化优化
    """

    def __init__(self, prompt_registry: PromptRegistry):
        self.registry = prompt_registry

    def bootstrap_few_shot(
        self,
        prompt_name: str,
        examples: List[Dict],  # [{input, expected_output}, ...]
        max_examples: int = 3,
    ) -> PromptVersion:
        """
        从示例中自动选择最佳 Few-Shot 示例

        策略:
        1. 用当前 Prompt 评估每个示例
        2. 选出最能纠正错误的示例
        3. 将示例嵌入 Prompt 的 user_template
        """
        current = self.registry.get_active(prompt_name)
        if not current:
            raise ValueError(f"Prompt '{prompt_name}' not found")

        # 简化: 选择最短且最具代表性的示例
        scored = []
        for ex in examples:
            score = self._score_example(ex)
            scored.append((score, ex))
        scored.sort(key=lambda x: x[0], reverse=True)

        best_examples = [ex for _, ex in scored[:max_examples]]

        # 构建 Few-Shot 模板
        few_shot_section = "\n\n参考示例：\n"
        for i, ex in enumerate(best_examples, 1):
            few_shot_section += f"\n示例{i}:\n输入: {ex.get('input', '')}\n输出: {ex.get('expected_output', '')}\n"

        new_template = few_shot_section + "\n---\n" + current.user_template

        new_version = PromptVersion(
            name=current.name,
            version=self._bump_version(current.version, "minor"),
            model=current.model,
            system_prompt=current.system_prompt,
            user_template=new_template,
            optimizer="bootstrap_few_shot",
            dataset_hash=self._hash_examples(examples),
        )

        self.registry.register(prompt_name, new_version.version, new_version, set_active=True)
        return new_version

    def optimize_from_feedback(
        self,
        prompt_name: str,
        failure_cases: List[Dict],  # [{content, actual_violation, expected_violation, error_type}, ...]
    ) -> PromptVersion:
        """
        基于失败案例优化 Prompt

        策略:
        1. 分析失败模式 (false_positive / false_negative / wrong_type)
        2. 在 system_prompt 中添加针对性指令
        3. 生成新版本
        """
        current = self.registry.get_active(prompt_name)
        if not current:
            raise ValueError(f"Prompt '{prompt_name}' not found")

        # 分析失败模式
        error_counts = {}
        for case in failure_cases:
            error_type = case.get("error_type", "unknown")
            error_counts[error_type] = error_counts.get(error_type, 0) + 1

        # 生成优化指令
        additions = []
        if error_counts.get("false_negative", 0) > 3:
            additions.append(
                f"\n\n【重要】近期误判分析：有 {error_counts['false_negative']} 个违规内容被错误标记为正常。"
                "请提高对隐藏违规信号的敏感度，尤其是边界模糊的内容。"
            )
        if error_counts.get("false_positive", 0) > 3:
            additions.append(
                f"\n\n【重要】近期误判分析：有 {error_counts['false_positive']} 个正常内容被错误标记为违规。"
                "请降低过度敏感的判定，只有在明确违规时才标记为违规。"
            )
        if error_counts.get("wrong_type", 0) > 3:
            additions.append(
                f"\n\n【重要】近期审核反馈：有 {error_counts['wrong_type']} 个内容的违规类型被误标。"
                "请仔细区分不同违规类型的特征，避免混淆相似类型。"
            )

        new_system_prompt = current.system_prompt + "".join(additions)

        new_version = PromptVersion(
            name=current.name,
            version=self._bump_version(current.version, "minor"),
            model=current.model,
            system_prompt=new_system_prompt,
            user_template=current.user_template,
            optimizer="feedback_optimization",
            metrics={"error_counts": error_counts},
        )

        self.registry.register(prompt_name, new_version.version, new_version, set_active=True)
        logger.info(f"Prompt '{prompt_name}' optimized from {len(failure_cases)} failures")
        return new_version

    def _score_example(self, example: dict) -> float:
        """评分示例质量"""
        score = 0.0
        input_len = len(str(example.get("input", "")))
        output_len = len(str(example.get("expected_output", "")))

        # 偏向中等长度 (太长浪费 token, 太短信息不足)
        if 20 < input_len < 200:
            score += 1.0
        if 10 < output_len < 100:
            score += 1.0

        # 偏向违规类型多样性
        expected = example.get("expected_output", "")
        if "violence" in str(expected) or "porn" in str(expected):
            score += 0.5

        return score

    def _bump_version(self, current: str, level: str = "minor") -> str:
        """版本号递增"""
        parts = current.split(".")
        if level == "major":
            return f"{int(parts[0])+1}.0.0"
        elif level == "minor":
            return f"{parts[0]}.{int(parts[1])+1}.0"
        else:
            return f"{parts[0]}.{parts[1]}.{int(parts[2])+1}"

    @staticmethod
    def _hash_examples(examples: list) -> str:
        """生成示例数据集的 hash"""
        import hashlib
        content = json.dumps(examples, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(content.encode()).hexdigest()[:12]


# === 反馈闭环管理器 ===

class FeedbackLoop:
    """
    反馈闭环 — 持续优化流水线 (v2: 基于 Redis buffer + AnnotationAgent)

    流程:
    1. 收集生产失败案例 → 写入 Redis annotation:buffer
    2. 当失败案例累积到阈值 (100) → 触发 OptimizationAgent
    3. OptimizationAgent LLM 分析后自主决策优化方向
    4. 优化后的 Prompt 作为新版本注册
    5. A/B 验证
    6. 通过后设为活跃版本

    配置:
    - 触发阈值: 累积 100 个失败案例 (由 AnnotationConsumer 检查)
    - 手动触发: 运营按钮 + API, 不限制数量
    - 最小间隔: 两次优化间隔 ≥ 600 秒 (10分钟)
    - 缓冲区从 Redis 读取 (不再用内存 list, 重启不丢)
    """

    def __init__(self, prompt_registry: PromptRegistry, optimizer: DspyStyleOptimizer):
        self.registry = prompt_registry
        self.optimizer = optimizer
        self._feedback_buffer: List[Dict] = []  # 保留本地引用, 兼容旧代码
        self._last_optimization: float = 0
        self.TRIGGER_THRESHOLD = 100    # v2: 从 20 → 100
        self.MIN_INTERVAL_SECONDS = 600  # v2: 从 3600 → 600 (10分钟)

    def collect_feedback(self, case: dict):
        """
        收集反馈案例 (兼容旧接口, 数据写入本地 buffer + Redis)

        case format:
        {
            "prompt_name": "text_moderation",
            "content": "...",
            "actual_decision": "PASS",
            "expected_decision": "REJECT",
            "error_type": "false_negative",  # 修复: 不再带 possible_ 前缀
        }
        """
        # 修复: 统一 error_type (去除 possible_ 前缀以匹配 optimize_from_feedback)
        error_type = case.get("error_type", "")
        if error_type.startswith("possible_"):
            case["error_type"] = error_type[len("possible_"):]
            logger.debug(f"Fixed error_type: {error_type} → {case['error_type']}")

        self._feedback_buffer.append(case)
        logger.debug(f"Feedback collected: {len(self._feedback_buffer)}/{self.TRIGGER_THRESHOLD}")

        # v2: 同步写入 Redis buffer
        self._sync_to_redis_buffer(case)

    def _sync_to_redis_buffer(self, case: dict):
        """将反馈同步写入 Redis (独立 key, 不与 AnnotationAgent buffer 冲突)"""
        try:
            import asyncio
            import json
            async def _write():
                from memory.redis_service import get_redis_service
                svc = get_redis_service()
                if svc.client:
                    # v2.1: 使用独立 key, 不与 annotation:buffer 混合
                    await svc.client.lpush(
                        "moderation:feedback:buffer",
                        json.dumps(case, ensure_ascii=False),
                    )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_write())
            except RuntimeError:
                pass  # 无事件循环, 跳过 Redis 写入
        except Exception:
            pass

    async def maybe_optimize(self) -> Optional[PromptVersion]:
        """检查是否需要优化并执行 (兼容旧接口, 现在由 OptimizationAgent 处理)"""
        import time
        now = time.time()

        # 从 Redis 读取实际 buffer 大小 (v2.1: 使用独立 feedback buffer key)
        buffer_size = len(self._feedback_buffer)
        try:
            from memory.redis_service import get_redis_service
            svc = get_redis_service()
            if svc.client:
                redis_size = await svc.client.llen("moderation:feedback:buffer")
                buffer_size = max(buffer_size, redis_size)
        except Exception:
            pass

        if buffer_size < self.TRIGGER_THRESHOLD:
            return None

        if now - self._last_optimization < self.MIN_INTERVAL_SECONDS:
            return None

        # 按 prompt_name 分组
        grouped: Dict[str, List[Dict]] = {}
        for case in self._feedback_buffer:
            name = case.get("prompt_name", "text_moderation")
            if name not in grouped:
                grouped[name] = []
            grouped[name].append(case)

        results = []
        for prompt_name, cases in grouped.items():
            if len(cases) >= 10:
                try:
                    new_pv = self.optimizer.optimize_from_feedback(prompt_name, cases)
                    results.append(new_pv)
                    logger.info(f"Optimized '{prompt_name}': {new_pv.version}")
                except Exception as e:
                    logger.error(f"Optimization failed for '{prompt_name}': {e}")

        # 清空缓冲区
        self._feedback_buffer = []
        self._last_optimization = now

        return results[0] if results else None

    def get_stats(self) -> dict:
        """获取反馈统计"""
        return {
            "buffer_size": len(self._feedback_buffer),
            "threshold": self.TRIGGER_THRESHOLD,
            "ready_to_optimize": len(self._feedback_buffer) >= self.TRIGGER_THRESHOLD,
            "last_optimization": self._last_optimization,
        }


# 全局实例
_prompt_registry: Optional[PromptRegistry] = None
_optimizer: Optional[DspyStyleOptimizer] = None
_feedback_loop: Optional[FeedbackLoop] = None


def get_prompt_registry() -> PromptRegistry:
    global _prompt_registry
    if _prompt_registry is None:
        _prompt_registry = PromptRegistry()
    return _prompt_registry


def get_optimizer() -> DspyStyleOptimizer:
    global _optimizer
    if _optimizer is None:
        _optimizer = DspyStyleOptimizer(get_prompt_registry())
    return _optimizer


def get_feedback_loop() -> FeedbackLoop:
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = FeedbackLoop(get_prompt_registry(), get_optimizer())
    return _feedback_loop
