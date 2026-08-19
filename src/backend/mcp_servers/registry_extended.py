"""
MCP 扩展工具注册层（R19）— 将 37 个新工具批量注册进 MCPToolRegistry

域划分：
  - 文本安全: security_text.py  (6)
  - 视觉:     vision.py         (4)
  - 网络:     network.py        (5)
  - 媒体:     media.py          (3)
  - 账号:     account_profile.py (3)
  - RAG/记忆: memory_tools.py   (5)
  - 决策:     decision.py       (6)
  - 运维:     ops.py            (5)
合计 37 个，加上原 8 个 = 45 个 MCP tools。
"""
from typing import Dict, List

from mcp_servers.tools.security_text import (
    PIIDetectTool, LanguageDetectTool, TextFingerprintTool,
    BlackmarketSlangTool, SensitiveWordExpandTool, EmailSpamDetectTool,
)
from mcp_servers.tools.vision import (
    ImageSensitiveDetectTool, ImageViolenceDetectTool,
    ImageQualityCheckTool, ImageDedupTool,
)
from mcp_servers.tools.network import (
    ShortlinkExpandTool, DomainReputationTool, IPReputationTool,
    PhishingPatternTool, DownloadRiskTool,
)
from mcp_servers.tools.media import (
    AudioMetadataCheckTool, VideoFramePlanTool, MediaToxicEstimateTool,
)
from mcp_servers.tools.account_profile import (
    AccountBehaviorAnomalyTool, AccountDeviceRiskTool, UserReputationTool,
)
from mcp_servers.tools.memory_tools import (
    RagHybridSearchTool, SourceWeightedSearchTool, SemanticCacheProbeTool,
    KnowledgeGraphQueryTool, CaseHistoryStatsTool,
)
from mcp_servers.tools.decision import (
    TriageRouterTool, RiskGradeEvaluateTool, TerminationDoubleSignTool,
    EvidenceFusionTool, SkillRouterRouteTool, ModelCascadeRouteTool,
)
from mcp_servers.tools.ops import (
    RegressionGuardCheckTool, ToolTelemetryReportTool,
    ViolationTypeLookupTool, PolicyLookupTool, SystemHealthTool,
)


def _t(tool_cls, name, description, props: Dict, required: List[str] = None):
    """构造注册条目"""
    return {
        "tool": tool_cls(),
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": props,
            "required": required or list(props),
        },
    }


def build_extended_entries() -> List[dict]:
    """构建全部扩展工具注册条目"""
    s = lambda t, d="": {"type": t, "description": d}  # noqa: E731
    return [
        # ============ 文本安全域 ============
        _t(PIIDetectTool, "pii_detect", "检测文本中的隐私信息（手机号/身份证/银行卡/邮箱/IP）",
           {"text": s("string", "待检测文本")}, ["text"]),
        _t(LanguageDetectTool, "language_detect", "检测文本语种（中/英/日/韩/俄/阿拉伯）",
           {"text": s("string", "待检测文本")}, ["text"]),
        _t(TextFingerprintTool, "text_fingerprint", "文本指纹相似度（近似重复检测）",
           {"text": s("string"), "ref_text": s("string", "参考文本"), "threshold": s("number")}, ["text"]),
        _t(BlackmarketSlangTool, "blackmarket_slang", "黑灰产黑话/谐音隐语检测",
           {"text": s("string")}, ["text"]),
        _t(SensitiveWordExpandTool, "sensitive_word_expand", "敏感词变体生成（谐音/拆字/间隔）",
           {"words": {"type": "array", "items": s("string"), "description": "敏感词列表"}}),
        _t(EmailSpamDetectTool, "email_spam_detect", "垃圾营销/广告引流识别",
           {"text": s("string")}, ["text"]),
        # ============ 视觉域 ============
        _t(ImageSensitiveDetectTool, "image_sensitive_detect", "图像敏感内容启发式检测（肤色占比）",
           {"image_path": s("string"), "image_data": s("string", "Base64 图像")}),
        _t(ImageViolenceDetectTool, "image_violence_detect", "图像暴力/血腥启发式检测（红色高饱和占比）",
           {"image_path": s("string"), "image_data": s("string", "Base64 图像")}),
        _t(ImageQualityCheckTool, "image_quality_check", "图像基本属性检查（尺寸/格式）",
           {"image_path": s("string"), "image_data": s("string")}),
        _t(ImageDedupTool, "image_dedup", "感知哈希图像相似比对（dHash）",
           {"image_path_a": s("string"), "image_path_b": s("string"),
            "image_data_a": s("string"), "image_data_b": s("string")}),
        # ============ 网络域 ============
        _t(ShortlinkExpandTool, "shortlink_expand", "短链识别与还原风险提示",
           {"text": s("string")}, ["text"]),
        _t(DomainReputationTool, "domain_reputation", "域名信誉评估（免费 TLD/钓鱼关键词）",
           {"text": s("string")}, ["text"]),
        _t(IPReputationTool, "ip_reputation", "IP 信誉评估（私网/保留段）",
           {"text": s("string")}, ["text"]),
        _t(PhishingPatternTool, "phishing_pattern", "钓鱼模式综合检测",
           {"text": s("string")}, ["text"]),
        _t(DownloadRiskTool, "download_risk", "下载链接风险（可执行/压缩包）",
           {"text": s("string")}, ["text"]),
        # ============ 媒体域 ============
        _t(AudioMetadataCheckTool, "audio_metadata_check", "音频元数据解析（时长/采样率）",
           {"audio_path": s("string"), "file_bytes": s("string")}),
        _t(VideoFramePlanTool, "video_frame_plan", "视频抽帧策略生成",
           {"duration_sec": s("number", "视频时长秒"), "frame_count": s("integer")}),
        _t(MediaToxicEstimateTool, "media_toxic_estimate", "媒体违规概率启发式估计",
           {"filename": s("string"), "transcript": s("string", "转写文本")}),
        # ============ 账号域 ============
        _t(AccountBehaviorAnomalyTool, "account_behavior_anomaly", "账号行为异常评分",
           {"posts_last_hour": s("integer"), "posts_per_day_avg": s("number"),
            "night_ratio": s("number"), "account_age_days": s("integer"), "daily_posts": s("number")}),
        _t(AccountDeviceRiskTool, "account_device_risk", "设备风险信号评估",
           {"is_jailbroken": s("boolean"), "is_emulator": s("boolean"),
            "multi_open": s("boolean"), "ip_shared_count": s("integer"), "new_device": s("boolean")}),
        _t(UserReputationTool, "user_reputation", "用户信誉分综合计算",
           {"violation_count": s("integer"), "content_count": s("integer"),
            "manual_confirm_bad": s("integer"), "manual_confirm_good": s("integer"),
            "account_age_days": s("integer")}),
        # ============ RAG/记忆域 ============
        _t(RagHybridSearchTool, "rag_hybrid_search", "混合检索（BM25+向量+重排序）",
           {"query": s("string"), "top_k": s("integer"), "use_rerank": s("boolean")}, ["query"]),
        _t(SourceWeightedSearchTool, "source_weighted_search", "来源加权检索（confirmed 优先）",
           {"query": s("string"), "top_k": s("integer")}, ["query"]),
        _t(SemanticCacheProbeTool, "semantic_cache_probe", "语义缓存查询",
           {"text": s("string")}, ["text"]),
        _t(KnowledgeGraphQueryTool, "knowledge_graph_query", "违规类型知识图谱查询",
           {"violation_types": {"type": "array", "items": s("string")}}, ["violation_types"]),
        _t(CaseHistoryStatsTool, "case_history_stats", "案例库统计（Chroma 案例数）", {}),
        # ============ 决策域 ============
        _t(TriageRouterTool, "triage_router", "三车道分诊（low/med/high）",
           {"text": s("string"), "content_type": s("string")}, ["text"]),
        _t(RiskGradeEvaluateTool, "risk_grade_evaluate", "风险定级（分→级别）",
           {"risk_score": s("number")}),
        _t(TerminationDoubleSignTool, "termination_double_sign", "终止双签校验",
           {"risk_score": s("number"),
            "violation_types": {"type": "array", "items": s("string")},
            "agent_agree": s("boolean"), "risk_agent_score": s("number")}),
        _t(EvidenceFusionTool, "evidence_fusion", "多模态证据融合",
           {"opinions": {"type": "array", "items": s("object")}}, ["opinions"]),
        _t(SkillRouterRouteTool, "skill_router_route", "技能三级路由",
           {"task_description": s("string"), "top_n": s("integer")}, ["task_description"]),
        _t(ModelCascadeRouteTool, "model_cascade_route", "模型级联路由决策",
           {"text": s("string"), "small_confidence": s("number")}, ["text"]),
        # ============ 运维域 ============
        _t(RegressionGuardCheckTool, "regression_guard_check", "优化回归守卫判定",
           {"before_score": s("number"), "after_score": s("number"), "threshold": s("number")}),
        _t(ToolTelemetryReportTool, "tool_telemetry_report", "工具遥测质量报告",
           {"tool_name": s("string")}),
        _t(ViolationTypeLookupTool, "violation_type_lookup", "违规类型字典查询",
           {"category": s("string")}),
        _t(PolicyLookupTool, "policy_lookup", "生效策略查询",
           {"policy_type": s("string")}),
        _t(SystemHealthTool, "system_health", "系统组件健康状态", {}),
    ]


def register_extended(registry) -> int:
    """批量注册扩展工具到 registry，返回注册数量"""
    count = 0
    for entry in build_extended_entries():
        registry.register(entry["name"], entry["tool"], {
            "name": entry["name"],
            "description": entry["description"],
            "inputSchema": entry["inputSchema"],
        })
        count += 1
    return count
