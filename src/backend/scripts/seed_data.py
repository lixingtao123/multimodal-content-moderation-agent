"""
种子数据生成器 — 为系统各模块生成历史数据，方便直接查看效果

生成:
  1. 标注结果 (moderation:annotation:results) — 16条，含正确+误判+漏判+类型错误
  2. 优化报告 (moderation:annotation:reports) — 3条历史报告
  3. 更新统计计数器 (moderation:annotation:stats)
"""
import asyncio
import json
import time
import sys
sys.path.insert(0, '/workspace/src/backend')

from memory.redis_service import get_redis_service
from optimization.annotation_queue import (
    RESULTS_KEY, BUFFER_KEY, STATS_KEY, REPORTS_KEY
)


def _make_anno(cid, is_err, etype, edetail, rverdict, rdetail, lverdict, lreason,
               cflag, atypes, aconf, ptime, atime, ctype, ainput,
               mdecision, mconf, mvtypes, mreason, mrisk,
               rkeywords, rrules, rwhite, radv, llam):
    """Helper to build a full annotation dict with all fields."""
    return {
        "content_id": cid, "is_error": is_err, "error_type": etype,
        "error_detail": edetail,
        "rule_verdict": rverdict, "rule_detail": rdetail,
        "llm_verdict": lverdict, "llm_reason": lreason,
        "contradiction_flag": cflag,
        "annotated_violation_types": atypes, "annotated_confidence": aconf,
        "processing_time_ms": ptime,
        "annotated_at": atime, "content_type": ctype,
        "annotation_input": ainput,
        "model_decision": mdecision, "model_confidence": mconf,
        "model_violation_types": mvtypes, "model_reason": mreason,
        "model_risk_score": mrisk,
        "rule_matched_keywords": rkeywords, "rule_matched_rules": rrules,
        "rule_whitelist_hit": rwhite, "rule_adversarial_hit": radv,
        "llm_called": llam,
    }


SEED_ANNOTATIONS = [
    # === 正确 (模型判断正确) — 6条 ===
    _make_anno("mod_abc1001", False, "correct",
        "模型判定正确, 与标注验证一致",
        "violation", "命中 2 个违规规则: keyword:violence, keyword:harassment | 关键词: 杀人, 去死",
        "violation", "内容包含明确暴力威胁和人身攻击",
        False, ["violence", "harassment"], 0.92, 1230.5,
        "2026-07-22T10:15:30Z", "text",
        "我要杀了你，你这个废物！滚蛋吧",
        "REJECT", 0.88, ["violence", "harassment"], "内容包含暴力威胁和侮辱性言论", 0.85,
        ["杀人", "废物"], ["keyword:violence", "keyword:harassment"], False, False, True),
    _make_anno("mod_abc1002", False, "correct",
        "模型判定正确, 内容为正常讨论",
        "normal", "无违规规则命中",
        "", "",
        False, [], 0.0, 1.2,
        "2026-07-22T10:16:00Z", "text",
        "今天天气真好，适合出去玩",
        "PASS", 0.95, [], "内容为日常闲聊，无违规", 0.05,
        [], [], False, False, False),
    _make_anno("mod_abc1003", False, "correct",
        "模型判定正确, 内容为正常技术讨论",
        "normal", "命中白名单模式: 技术讨论",
        "", "",
        False, [], 0.0, 0.8,
        "2026-07-22T10:16:30Z", "text",
        "Python 的异步编程使用 asyncio 库实现协程",
        "PASS", 0.97, [], "内容为技术讨论", 0.03,
        [], [], True, False, False),
    _make_anno("mod_abc1004", False, "correct",
        "模型正确判定为广告内容",
        "violation", "命中 1 个违规规则: keyword:advertisement | 关键词: 加微信",
        "violation", "内容包含诱导添加联系方式，判定为广告引流",
        False, ["advertisement"], 0.88, 2100.0,
        "2026-07-22T10:17:00Z", "text",
        "加微信免费领取大礼包，名额有限先到先得",
        "REJECT", 0.85, ["advertisement"], "内容包含引导添加微信进行推广", 0.78,
        ["加微信"], ["keyword:advertisement"], False, False, True),
    _make_anno("mod_abc1005", False, "correct",
        "模型正确判定为政治敏感内容",
        "violation", "命中 1 个违规规则: keyword:politics | 关键词: 反动",
        "violation", "内容包含政治敏感言论",
        False, ["politics"], 0.95, 1850.0,
        "2026-07-22T10:17:30Z", "text",
        "我们要推翻现有的反动统治，建立新的秩序",
        "REJECT", 0.92, ["politics"], "内容包含推翻政府等反动言论", 0.90,
        ["反动", "推翻"], ["keyword:politics"], False, False, True),
    _make_anno("mod_abc1006", False, "correct",
        "模型正确判定为色情低俗内容",
        "violation", "命中 2 个违规规则: keyword:porn | 关键词: 裸聊, 色情",
        "violation", "内容包含色情描述和低俗暗示",
        False, ["porn"], 0.91, 2450.0,
        "2026-07-22T10:18:00Z", "text",
        "深夜裸聊激情视频，色情直播在线观看",
        "REJECT", 0.93, ["porn"], "内容包含色情直播宣传", 0.88,
        ["裸聊", "色情"], ["keyword:porn", "keyword:porn"], False, False, True),

    # === 误判 (模型判违规，实际正常) — 3条 ===
    _make_anno("mod_abc2001", True, "false_positive",
        "模型判定为 [REJECT]; 规则复核: 命中白名单模式, 无违规规则命中; LLM独立审核: 内容为正常医学健康教育讨论 (verdict=normal); 矛盾检测: 判定为porn但reason描述医学/教育内容; 结论: 【误判】模型判为违规, 但标注认为内容正常; 建议: 降低对医学术语的敏感度, 增加白名单规则",
        "normal", "命中白名单模式: 医疗健康, 无违规规则命中",
        "normal", "内容为正常的医学教育和生理知识科普",
        True, [], 0.15, 3200.0,
        "2026-07-22T10:20:00Z", "text",
        "青春期生理卫生教育：了解生殖系统的构造和功能是健康素养的基础",
        "REJECT", 0.72, ["porn"], "内容涉及生殖系统描述，疑似色情内容", 0.70,
        [], [], True, False, True),
    _make_anno("mod_abc2002", True, "false_positive",
        "模型判定为 [REVIEW]; 规则复核: 无违规规则命中; LLM独立审核: 内容为正常新闻报道 (verdict=normal); 结论: 【误判】模型判为违规, 实际为正常新闻; 建议: 降低对新闻内容的误判率",
        "normal", "命中白名单模式: 新闻报道, 无违规规则命中",
        "normal", "内容是正常的新闻报道，不应被判定为违规",
        False, [], 0.12, 2800.0,
        "2026-07-22T10:20:30Z", "text",
        "新华社报道：今日召开新闻发布会，通报最新政策调整",
        "REVIEW", 0.55, ["politics"], "内容涉及政策调整，需要人工判断是否有政治敏感", 0.55,
        [], [], True, False, True),
    _make_anno("mod_abc2003", True, "false_positive",
        "模型判定为 [REJECT]; 规则复核: 仅命中 1 个违规规则, 不足以判定; LLM独立审核: 无明确违规信号 (verdict=normal); 结论: 【误判】过度敏感, 将正常讨论误判; 建议: 调整暴力类关键词匹配阈值",
        "uncertain", "仅命中 1 个违规规则: keyword:violence | 不足以判定",
        "normal", "内容为虚拟作品讨论，无真实暴力威胁",
        False, [], 0.20, 3100.0,
        "2026-07-22T10:21:00Z", "text",
        "这个电影里的打斗场面太精彩了，主角差点被杀死但最后反杀了",
        "REJECT", 0.65, ["violence"], "内容包含杀死等暴力词汇", 0.67,
        ["杀死"], ["keyword:violence"], False, False, True),

    # === 漏判 (模型判正常，实际违规) — 4条 ===
    _make_anno("mod_abc3001", True, "false_negative",
        "模型判定为 [PASS]; 规则复核: 命中 2 个违规规则: keyword:violence, keyword:harassment | 关键词: 弄死, 废物; LLM独立审核: 内容包含明显的人身威胁 (verdict=violation); 结论: 【漏判】模型判为正常, 但标注发现违规信号; 建议: 提高对混合式威胁语言的敏感度",
        "violation", "命中 2 个违规规则: keyword:violence, keyword:harassment | 关键词: 弄死, 废物",
        "violation", "内容包含明显的威胁和侮辱性语言",
        True, ["violence", "harassment"], 0.85, 3450.0,
        "2026-07-22T10:25:00Z", "text",
        "你等着，我迟早弄死你，废物",
        "PASS", 0.80, [], "内容可能是朋友间的玩笑话", 0.15,
        ["弄死", "废物"], ["keyword:violence", "keyword:harassment"], False, False, True),
    _make_anno("mod_abc3002", True, "false_negative",
        "模型判定为 [PASS]; 规则复核: 命中 1 个违规规则: keyword:advertisement | 关键词: 扫码进群, 代理; LLM独立审核: 内容为明显的广告引流 (verdict=violation); 结论: 【漏判】模型判为正常, 但标注发现广告特征; 建议: 补充广告引流相关关键词",
        "violation", "命中 1 个违规规则: keyword:advertisement | 关键词: 扫码进群, 代理",
        "violation", "内容包含明显的广告引流和拉群行为",
        False, ["advertisement"], 0.82, 2900.0,
        "2026-07-22T10:25:30Z", "text",
        "扫码进群免费领资料，招代理日赚500",
        "PASS", 0.75, [], "内容未检测到明显违规特征", 0.25,
        ["扫码进群", "代理"], ["keyword:advertisement"], False, False, True),
    _make_anno("mod_abc3003", True, "false_negative",
        "模型判定为 [PASS]; 规则复核: 命中 1 个违规规则: keyword:politics | 关键词: 颠覆; LLM独立审核: 内容有政治风险暗示 (verdict=violation); 结论: 【漏判】模型判为正常, 但标注发现政治敏感信号; 建议: 提高政治敏感内容的检测阈值",
        "violation", "命中 1 个违规规则: keyword:politics | 关键词: 颠覆",
        "violation", "内容暗示对国家体制的不满，具有政治风险",
        False, ["politics"], 0.78, 3650.0,
        "2026-07-22T10:26:00Z", "text",
        "这种错误的决策迟早会颠覆整个行业的发展方向",
        "PASS", 0.82, [], "内容是行业讨论，未涉及政治敏感", 0.18,
        ["颠覆"], ["keyword:politics"], False, False, True),
    _make_anno("mod_abc3004", True, "false_negative",
        "模型判定为 [PASS]; 规则复核: 命中 2 个违规规则: keyword:false_info | 关键词: 赚钱秘籍, 日赚; LLM独立审核: 内容为典型的虚假诈骗信息 (verdict=violation); 结论: 【漏判】; 建议: 增加诈骗类关键词覆盖",
        "violation", "命中 2 个违规规则: keyword:false_info | 关键词: 赚钱秘籍, 日赚",
        "violation", "内容为典型的虚假信息诈骗话术",
        False, ["false_info"], 0.90, 3300.0,
        "2026-07-22T10:26:30Z", "text",
        "分享一个赚钱秘籍，在家躺着日赚1000不是梦",
        "PASS", 0.78, [], "未检测到明显的虚假信息特征", 0.22,
        ["赚钱秘籍", "日赚"], ["keyword:false_info", "keyword:false_info"], False, False, True),

    # === 类型错误 (判了违规但类型不对) — 3条 ===
    _make_anno("mod_abc4001", True, "wrong_violation_type",
        "模型判定为 [REJECT], 类型=[advertisement]; 规则复核: 实际命中关键词为 violence 类; 结论: 【类型错误】违规类型判定为advertisement, 实际为violence; 建议: 强化violence和advertisement的区分",
        "violation", "命中 2 个违规规则: keyword:violence | 但模型判为advertisement",
        "violation", "内容包含暴力威胁，不应归类为广告",
        True, ["violence"], 0.88, 4100.0,
        "2026-07-22T10:30:00Z", "text",
        "不买我的东西我就杀了你全家，加微信转账",
        "REJECT", 0.82, ["advertisement"], "内容包含强制推销和加微信的广告行为", 0.80,
        ["杀了", "加微信"], ["keyword:violence", "keyword:advertisement"], False, False, True),
    _make_anno("mod_abc4002", True, "wrong_violation_type",
        "模型判定为 [REVIEW], 类型=[harassment]; 实际应为politics; 结论: 【类型错误】; 建议: 区分政治敏感与辱骂的交叉案例",
        "violation", "命中 1 个违规规则: keyword:politics | 但模型判为harassment",
        "violation", "内容核心是政治攻击，辱骂只是表达方式",
        False, ["politics", "harassment"], 0.75, 3800.0,
        "2026-07-22T10:30:30Z", "text",
        "这个卖国贼是个傻逼，应该被抓起来法办",
        "REVIEW", 0.60, ["harassment"], "内容包含辱骂性语言", 0.60,
        ["傻逼"], ["keyword:harassment"], False, False, True),
    _make_anno("mod_abc4003", True, "wrong_violation_type",
        "模型判定为 [REVIEW], 类型=[false_info]; 实际应为advertisement; 结论: 【类型错误】将广告引流误判为虚假信息; 建议: 加强广告和虚假信息的区分指引",
        "violation", "命中 1 个违规规则: keyword:advertisement | 但模型判为false_info",
        "violation", "内容主要是广告引流，虚假信息是次要特征",
        False, ["advertisement"], 0.80, 3500.0,
        "2026-07-22T10:31:00Z", "text",
        "最后3天！限时福利免费领，稳赚不赔的投资机会，加微信了解",
        "REVIEW", 0.58, ["false_info"], "内容声称稳赚不赔，疑似虚假宣传", 0.55,
        ["加微信", "稳赚"], ["keyword:advertisement", "keyword:false_info"], False, False, True),
]

SEED_REPORTS = [
    {
        "report_id": "opt_seed00001",
        "timestamp": "2026-07-21T14:30:00Z",
        "trigger": "auto",
        "total_samples": 100,
        "error_distribution": {"false_positive": 35, "false_negative": 48, "wrong_violation_type": 17},
        "pattern_analysis": "本轮错误主要集中在漏判(false_negative)上，占48%。分析发现模型对隐蔽性较强的广告引流和混合式威胁语言检测能力不足。关键词库中advertisement类仅覆盖7个关键词，导致大量变体广告无法被规则引擎捕获。此外，部分政治隐喻内容被模型判定为正常讨论，反映出Prompt中对隐性政治风险的指引不够明确。",
        "optimization_actions": [
            {"action_type": "prompt_update", "target": "text_moderation",
             "description": "在Prompt中增加对隐性广告引流和变体政治表达的判断指引，强调注意同音字替换和语境包装",
             "reason": "48条漏判案例中有27条与变体广告和政治隐喻相关"},
            {"action_type": "keyword_update", "target": "advertisement + politics",
             "description": "新增广告类关键词15个, 政治类关键词8个",
             "reason": "大量漏判案例涉及关键词库未覆盖的变体表达"},
            {"action_type": "rag_case_add", "target": "core_memory",
             "description": "将5个典型漏判案例加入ChromaDB知识库作为RAG检索参考",
             "reason": "这些案例具有代表性，可作为未来相似案例的参考"}
        ],
        "estimated_impact": "预计漏判率降低15-20%, 对变体广告和隐晦政治内容的敏感度显著提升",
        "before": {
            "prompts": {"text_moderation": {"version": "1.2", "snippet": "你是一个内容审核专家..."}},
            "keywords_stats": {"violence": 14, "porn": 18, "politics": 8, "false_info": 13, "harassment": 7, "advertisement": 7},
            "thresholds": {"review": 0.35, "reject": 0.75}
        },
        "after": {
            "prompts": {"text_moderation": {"version": "1.3", "snippet": "...v1.3新增隐性广告和变体政治判断指引..."}},
            "keywords_stats": {"violence": 14, "porn": 18, "politics": 16, "false_info": 13, "harassment": 7, "advertisement": 22},
            "thresholds": {"review": 0.35, "reject": 0.75}
        }
    },
    {
        "report_id": "opt_seed00002",
        "timestamp": "2026-07-22T09:15:00Z",
        "trigger": "manual",
        "total_samples": 52,
        "error_distribution": {"false_positive": 28, "false_negative": 15, "wrong_violation_type": 9},
        "pattern_analysis": "手动触发优化。本轮误判(false_positive)占比最高(53.8%)，主要问题集中在医疗健康领域的正常讨论被误判为色情低俗。模型对医学术语过于敏感，未能区分医学教育和色情内容。",
        "optimization_actions": [
            {"action_type": "prompt_update", "target": "text_moderation",
             "description": "修改色情低俗判断指引，明确区分医学/教育场景与色情内容。新增医学健康内容豁免条款",
             "reason": "28条误判案例中19条为医学教育内容被误判为色情"},
            {"action_type": "keyword_update", "target": "porn",
             "description": "从色情关键词库中移除'私密'、'敏感部位'等医学术语",
             "reason": "这些词在医疗语境下完全正常"},
            {"action_type": "threshold_adjust", "target": "porn",
             "description": "色情类REJECT阈值从0.75提升至0.80",
             "reason": "减少医学教育类内容的误判"}
        ],
        "estimated_impact": "预计误判率降低25-30%, 色情类审核准确度提升",
        "before": {
            "prompts": {"text_moderation": {"version": "1.3", "snippet": "...v1.3..."}},
            "keywords_stats": {"violence": 14, "porn": 18, "politics": 16, "false_info": 13, "harassment": 7, "advertisement": 22},
            "thresholds": {"review": 0.35, "reject": 0.75}
        },
        "after": {
            "prompts": {"text_moderation": {"version": "1.4", "snippet": "...v1.4增加了医学豁免条款..."}},
            "keywords_stats": {"violence": 14, "porn": 16, "politics": 16, "false_info": 13, "harassment": 7, "advertisement": 22},
            "thresholds": {"review": 0.35, "reject": 0.80}
        }
    },
    {
        "report_id": "opt_seed00003",
        "timestamp": "2026-07-23T00:30:00Z",
        "trigger": "auto",
        "total_samples": 105,
        "error_distribution": {"false_positive": 18, "false_negative": 52, "wrong_violation_type": 35},
        "pattern_analysis": "自动触发。本轮问题集中在违规类型判定不准确(wrong_violation_type占33%)和漏判(49.5%)。大量案例中广告引流被误判为虚假信息，暴力威胁被误判为辱骂骚扰。提示词对各类违规的区分边界不够清晰。",
        "optimization_actions": [
            {"action_type": "prompt_update", "target": "text_moderation + image_moderation",
             "description": "新增违规类型判定优先级规则，明确当内容同时涉及多种违规时如何选择主要违规类型。增加对抗文本检测提醒",
             "reason": "35条类型错误案例表明类型边界模糊"},
            {"action_type": "rag_case_add", "target": "core_memory",
             "description": "将8个典型对抗文本案例加入ChromaDB",
             "reason": "漏判案例中有大量对抗文本变体"}
        ],
        "estimated_impact": "预计类型判定准确度提升20%，对抗文本检出率提升15%",
        "before": {
            "prompts": {"text_moderation": {"version": "1.4", "snippet": "...v1.4..."}},
            "keywords_stats": {"violence": 14, "porn": 16, "politics": 16, "false_info": 13, "harassment": 7, "advertisement": 22},
            "thresholds": {"review": 0.35, "reject": 0.80}
        },
        "after": {
            "prompts": {"text_moderation": {"version": "1.5", "snippet": "...v1.5新增优先级规则和对抗文本提醒..."}},
            "keywords_stats": {"violence": 16, "porn": 16, "politics": 16, "false_info": 13, "harassment": 9, "advertisement": 22},
            "thresholds": {"review": 0.33, "reject": 0.80}
        }
    },
]


async def seed():
    svc = get_redis_service()
    await svc.connect()
    client = svc.client

    # === 1. 标注结果 ===
    await client.delete(RESULTS_KEY)
    await client.delete(BUFFER_KEY)

    total = 0
    errors = 0
    stats_counts = {"correct": 0, "false_positive": 0, "false_negative": 0, "wrong_violation_type": 0}

    for item in SEED_ANNOTATIONS:
        data = json.dumps(item, ensure_ascii=False)
        await client.lpush(RESULTS_KEY, data)
        total += 1
        if item["is_error"]:
            errors += 1
            await client.lpush(BUFFER_KEY, data)
        stats_counts[item["error_type"]] = stats_counts.get(item["error_type"], 0) + 1

    await client.ltrim(RESULTS_KEY, 0, 499)
    print(f"✅ Seeded {total} annotation results ({errors} errors)")

    # === 2. 统计计数器 ===
    await client.hset(STATS_KEY, mapping={
        "total_processed": str(total),
        "total_errors": str(errors),
        "correct": str(stats_counts.get("correct", 0)),
        "false_positives": str(stats_counts.get("false_positive", 0)),
        "false_negatives": str(stats_counts.get("false_negative", 0)),
        "wrong_types": str(stats_counts.get("wrong_violation_type", 0)),
        "last_annotation_time": str(int(time.time())),
        "last_optimization_time": str(int(time.time())),
    })
    print(f"✅ Stats updated: {stats_counts}")

    # === 3. 优化报告 ===
    await client.delete(REPORTS_KEY)
    for report in SEED_REPORTS:
        await client.lpush(REPORTS_KEY, json.dumps(report, ensure_ascii=False))
    await client.ltrim(REPORTS_KEY, 0, 49)
    print(f"✅ Seeded {len(SEED_REPORTS)} optimization reports")

    await svc.disconnect()
    print("\n🎉 Seed data generation complete!")


if __name__ == "__main__":
    asyncio.run(seed())
