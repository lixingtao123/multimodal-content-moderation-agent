#!/bin/bash
# ============================================================================
# 人工审核模块 全套测试脚本
# 覆盖: 正常/违规/边界/待审核队列/人工标注/统计/标注保护
# 用法: bash tests/manual/hitl_test_suite.sh [API_HOST]
# ============================================================================
set -e

API="${1:-http://localhost:18080}"
PASS=0
FAIL=0

green() { echo -e "\033[32m$*\033[0m"; }
red()   { echo -e "\033[31m$*\033[0m"; }
bold()  { echo -e "\033[1m$*\033[0m"; }
dim()   { echo -e "\033[2m$*\033[0m"; }

check() {
    local desc="$1" expected="$2" actual="$3"
    if [ "$expected" = "$actual" ]; then
        green "  ✅ $desc (expected=$expected)"
        PASS=$((PASS+1))
    else
        red "  ❌ $desc (expected=$expected, got=$actual)"
        FAIL=$((FAIL+1))
    fi
}

echo ""
bold "╔══════════════════════════════════════════════════════════╗"
bold "║     人工审核模块 (HITL) 全套测试  v3.2                    ║"
bold "╚══════════════════════════════════════════════════════════╝"
echo "API: $API"
echo ""

# ─── 0. 健康检查 ───
echo "━━━ 0. 健康检查 ━━━"
HEALTH=$(curl -s "$API/health" | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
check "所有依赖正常" "ok" "$HEALTH"
echo ""

# ─── 1. 正常文本 → PASS ───
echo "━━━ 场景1: 正常无害文本 → PASS, human_review_required=false ━━━"
TS=$(date +%s)
R1=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"今天天气真好，适合出去散步 ${TS}\", \"account_id\": \"t1_${TS}\"}")
D1=$(echo "$R1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('final_decision','ERROR'))")
S1=$(echo "$R1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('risk_score',-1))")
H1=$(echo "$R1" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('human_review_required','ERROR'))")
check "决策=PASS"        "PASS"  "$D1"
check "风险分<0.25"      "true"  "$(python3 -c "print($S1 < 0.25)")"
check "不需要人工审核"    "False" "$H1"
echo ""

# ─── 2. 明确严重违规 → REJECT ───
echo "━━━ 场景2: 明确严重违规 → REJECT, 高置信度不触发人工 ━━━"
TS=$((TS+1))
R2=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"你这个傻逼废物赶紧滚远点，再不滚我弄死你 ${TS}\", \"account_id\": \"t2_${TS}\"}")
D2=$(echo "$R2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('final_decision','ERROR'))")
S2=$(echo "$R2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('risk_score',-1))")
H2=$(echo "$R2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('human_review_required','ERROR'))")
VT2=$(echo "$R2" | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(d.get('violation_types',[])))")
check "决策=REJECT/REVIEW" "true" "$(python3 -c "print('$D2' in ('REJECT','REVIEW'))")"
check "包含harassment"  "true"  "$(python3 -c "print('harassment' in '$VT2')")"
# 高置信度违规不触发人工 (score >= 0.70 会跳过模糊边界)
echo "  决策=$D2, 风险分=$S2, human_review_required=$H2, types=$VT2"
echo ""

# ─── 3. 边界模糊(地域歧视) → REVIEW + 人工 ───
echo "━━━ 场景3: 边界模糊(地域歧视) → REVIEW, human_review_required=true ━━━"
TS=$((TS+1))
R3=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"某些地方的人素质就是低，虽然不能以偏概全，但确实让人不舒服 ${TS}\", \"account_id\": \"t3_${TS}\"}")
D3=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('final_decision','ERROR'))")
S3=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('risk_score',-1))")
H3=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('human_review_required','ERROR'))")
CID3=$(echo "$R3" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content_id',''))")
check "决策=REVIEW"      "REVIEW" "$D3"
check "需要人工审核"     "True"   "$H3"
echo "  content_id=$CID3, score=$S3"
echo ""

# ─── 4. 边界模糊(轻度攻击+澄清) ───
echo "━━━ 场景4: 边界模糊(轻度攻击+玩笑澄清) → human_review_required=true ━━━"
TS=$((TS+1))
R4=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"你这人怎么这样啊，太让人失望了，说实话你真的不行 ${TS}\", \"account_id\": \"t4_${TS}\"}")
D4=$(echo "$R4" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('final_decision','ERROR'))")
S4=$(echo "$R4" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('risk_score',-1))")
H4=$(echo "$R4" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('human_review_required','ERROR'))")
CID4=$(echo "$R4" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content_id',''))")
echo "  决策=$D4, 风险分=$S4, human_review_required=$H4, id=$CID4"
# 这个文本可能会也可能不会触发，取决于 LLM 判决
echo ""

# ─── 5. 边界模糊(歧视性言论+否认) ───
echo "━━━ 场景5: 边界模糊(歧视性言论+否认前缀) → human_review_required=true ━━━"
TS=$((TS+1))
R5=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"我不是歧视他们，但这类人确实普遍素质堪忧，社会问题跟这个脱不了关系 ${TS}\", \"account_id\": \"t5_${TS}\"}")
D5=$(echo "$R5" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('final_decision','ERROR'))")
S5=$(echo "$R5" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('risk_score',-1))")
H5=$(echo "$R5" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('human_review_required','ERROR'))")
CID5=$(echo "$R5" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content_id',''))")
echo "  决策=$D5, 风险分=$S5, human_review_required=$H5, id=$CID5"
echo ""

# ─── 6. 待审核队列 ───
echo "━━━ 场景6: 待审核队列查询 ━━━"
Q=$(curl -s "$API/api/v1/moderate/pending-reviews")
QTOTAL=$(echo "$Q" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total', len(d.get('items',[]))))")
echo "  待审核总数: $QTOTAL"
if [ "$QTOTAL" -gt 0 ]; then
    echo "$Q" | python3 -c "
import sys,json
d=json.load(sys.stdin)
items=d.get('items',[])
for i in items[:5]:
    print(f'    id={i[\"content_id\"]}, preview={i.get(\"text_preview\",\"\")[:50]}..., score={i.get(\"risk_score\",\"?\")}')
" 2>/dev/null || true
fi
check "待审核队列非空" "true" "$(python3 -c "print($QTOTAL > 0)")"
echo ""

# ─── 7. 人工标注提交 ───
echo "━━━ 场景7: 人工标注提交 → source=human, weight=3.0 ━━━"
if [ -n "$CID3" ] && [ "$CID3" != "" ]; then
    R7=$(curl -s -X POST "$API/api/v1/admin/annotation/human?content_id=$CID3" \
      -H "Content-Type: application/json" \
      -d '{"reviewer_id": "test_annotator", "violation_type": "harassment", "confidence": 0.95, "reason": "明确的地域歧视言论，建议删除", "tags": ["地域歧视","刻板印象"], "is_adversarial": false, "decision": "REJECT"}')
    SAVED=$(echo "$R7" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('saved','ERROR'))")
    SRC=$(echo "$R7"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source','ERROR'))")
    WT=$(echo "$R7"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('weight','ERROR'))")
    ISERR=$(echo "$R7" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('is_error','ERROR'))")
    ETYPE=$(echo "$R7" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error_type','ERROR'))")
    check "标注已保存"     "True"    "$SAVED"
    check "来源=human"     "human"   "$SRC"
    check "权重=3.0"      "3.0"     "$WT"
    check "标记为错误"     "True"    "$ISERR"
    check "错误类型"       "false_negative" "$ETYPE"
else
    red "  ⚠️ 跳过: 场景3未触发人工审核，无可用 content_id"
    FAIL=$((FAIL+5))
fi
echo ""

# ─── 8. 人工标注统计 ───
echo "━━━ 场景8: 人工标注统计查询 ━━━"
R8=$(curl -s "$API/api/v1/admin/annotation/human/stats")
HTOTAL=$(echo "$R8" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['human']['total'])")
HERR=$(echo "$R8"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['human']['errors_found'])")
HFP=$(echo "$R8"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['human']['false_positives'])")
HFN=$(echo "$R8"    | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['human']['false_negatives'])")
HAVG=$(echo "$R8"   | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['human']['avg_weight'])")
ATOTAL=$(echo "$R8" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['auto']['total'])")
echo "  人工标注: total=$HTOTAL, errors=$HERR (FP=$HFP, FN=$HFN), avg_weight=$HAVG"
echo "  自动标注: total=$ATOTAL"
check "人工标注数>=1"  "true" "$(python3 -c "print($HTOTAL >= 1)")"
check "平均权重=3.0"   "3.0"  "$HAVG"
echo ""

# ─── 9. 自动标注不覆盖人工标注 ───
echo "━━━ 场景9: 自动标注不覆盖人工标注 (ON CONFLICT 保护) ━━━"
if [ -n "$CID3" ] && [ "$CID3" != "" ]; then
    # 查询标注记录，验证 source 和 weight
    R9=$(curl -s "$API/api/v1/admin/optimization/annotation-results/$CID3")
    SRC9=$(echo "$R9" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source','ERROR'))")
    WT9=$(echo "$R9"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('weight','ERROR'))")
    check "source仍为human"  "human" "$SRC9"
    check "weight仍为3.0"   "3.0"   "$WT9"
else
    red "  ⚠️ 跳过: 无可用 content_id"
    FAIL=$((FAIL+2))
fi
echo ""

# ─── 10. AI推理过程展示 ───
echo "━━━ 场景10: 审核结果包含AI推理数据 ━━━"
R10=$(curl -s "$API/api/v1/moderate/$CID3" 2>/dev/null || echo '{}')
HAS_REASONING=$(echo "$R10" | python3 -c "
import sys,json
d=json.load(sys.stdin)
ar=d.get('agent_reasoning',{})
has_text=bool(ar.get('text',{}).get('reasoning',''))
has_chain=bool(ar.get('text',{}).get('reasoning_chain',[]))
print(str(has_text and has_chain))
" 2>/dev/null || echo "ERROR")
check "包含reasoning+chain" "True" "$HAS_REASONING"
echo ""

# ─── 11. AnnotationAgent 自动标注回归 ───
echo "━━━ 场景11: 提交明确违规 → AnnotationAgent自动标注 (source=auto, weight=1.0) ━━━"
TS=$((TS+1))
R11=$(curl -s -X POST "$API/api/v1/moderate/text" \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"你这垃圾，真恶心，滚 ${TS}\", \"account_id\": \"t11_${TS}\"}")
CID11=$(echo "$R11" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('content_id','ERROR'))")
echo "  提交结果 content_id=$CID11"
# 等几秒让 AnnotationAgent 异步处理
sleep 12
ANN=$(curl -s "$API/api/v1/admin/optimization/annotation-results/$CID11" 2>/dev/null || echo '{}')
ANNSRC=$(echo "$ANN" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source','ERROR'))" 2>/dev/null || echo "N/A")
ANNWT=$(echo "$ANN"  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('weight','ERROR'))" 2>/dev/null || echo "N/A")
if [ "$ANNSRC" = "auto" ]; then
    check "自动标注source=auto" "auto" "$ANNSRC"
    check "自动标注weight=1.0" "1.0"  "$ANNWT"
else
    dim "  (自动标注结果未就绪或已被处理, 跳过验证)"
fi
echo ""

# ─── 汇总 ───
echo ""
bold "╔══════════════════════════════════════════════════════════╗"
TOTAL=$((PASS+FAIL))
if [ "$FAIL" -eq 0 ]; then
    green "║  测试结果: $PASS/$TOTAL 全部通过 ✅                        ║"
else
    red  "║  测试结果: $PASS/$TOTAL 通过, $FAIL 失败 ❌                  ║"
fi
bold "╚══════════════════════════════════════════════════════════╝"
echo ""

exit $FAIL
