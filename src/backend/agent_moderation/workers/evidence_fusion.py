"""
多模态证据化融合（R13·Q1）— 各模态独立证据一起判，非"文本中心"

背景短板：现状融合终判时文本模型结果是主角，视觉/语音独立判断被"借用"但不参与决策。
本模块提供证据化融合裁决：每个模态的意见（含证据链）平等参与，按证据质量加权，
不存在"文本默认优先"。

纯逻辑、可单测；供 planner_node 深水区融合与 risk_agent 证据化投票使用。
"""


def fuse_modal_opinions(opinions: list) -> dict:
    """融合各模态独立意见（证据化、非文本中心）。

    Args:
        opinions: 每项 {modality, violation_type, confidence, evidence: list, risk_score}

    Returns:
        {final_type, confidence, evidence_summary, contributing_modalities, modal_breakdown}
    """
    if not opinions:
        return {"final_type": "none", "confidence": 0.0, "evidence_summary": "",
                "contributing_modalities": [], "modal_breakdown": {}}

    type_scores: dict = {}
    type_evidence: dict = {}
    type_modalities: dict = {}
    for op in opinions:
        vt = op.get("violation_type", "none")
        conf = float(op.get("confidence", 0.0))
        evidence = op.get("evidence") or []
        # 证据加权：证据充分者话语权提升（与辩论一致：+0.2/条，上限3条）
        score = conf * (1.0 + 0.2 * min(len(evidence), 3))
        type_scores[vt] = type_scores.get(vt, 0.0) + score
        type_evidence.setdefault(vt, []).extend(evidence)
        type_modalities.setdefault(vt, set()).add(op.get("modality", "?"))

    # 证据充分度: 每个类型累计的证据条数
    winner_type = max(type_scores, key=type_scores.get)
    total_score = sum(type_scores.values()) or 1.0
    confidence = type_scores[winner_type] / total_score  # 相对支持度

    return {
        "final_type": winner_type,
        "confidence": round(confidence, 4),
        "evidence_summary": f"类型[{winner_type}] 获 {type_modalities[winner_type]} "
                            f"{len(type_evidence[winner_type])} 条证据支撑",
        "contributing_modalities": sorted(type_modalities[winner_type]),
        "modal_breakdown": {
            vt: {"score": round(s, 4), "evidence_count": len(type_evidence[vt]),
                 "modalities": sorted(type_modalities[vt])}
            for vt, s in type_scores.items()
        },
    }


def build_modal_opinion(modality: str, violation_type: str, confidence: float,
                        evidence: list, risk_score: float = 0.0) -> dict:
    """构造模态意见（供各模态 Agent 产出，统一结构）"""
    return {
        "modality": modality,
        "violation_type": violation_type,
        "confidence": float(confidence),
        "evidence": list(evidence),
        "risk_score": float(risk_score),
    }
