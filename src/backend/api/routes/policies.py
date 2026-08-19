"""
策略管理 API v1.0 — 审核规则配置化

提供策略的增删改查, 使运营人员可以界面化配置审核规则,
无需改代码重新部署。

策略类型:
  - keyword:    关键词检测规则
  - regex:      正则表达式规则
  - sensitivity: 违规类型灵敏度配置
  - threshold:  决策阈值配置 (REVIEW/REJECT分数线)
  - model_route: 模型路由规则 (Tier1/Tier2/Tier3)
"""
import json
import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/admin/policies", tags=["policies"])


class PolicyCreate(BaseModel):
    name: str
    policy_type: str  # keyword / regex / sensitivity / threshold / model_route
    description: str = ""
    rule_config: dict
    enabled: bool = True
    priority: int = 5
    created_by: str = "admin"


class PolicyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_config: Optional[dict] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None


# ===== CRUD =====

@router.get("")
async def list_policies(
    policy_type: Optional[str] = Query(None),
    enabled_only: bool = False,
):
    """列出所有策略"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as session:
            where_clauses = []
            params = {}

            if policy_type:
                where_clauses.append("policy_type = :policy_type")
                params["policy_type"] = policy_type
            if enabled_only:
                where_clauses.append("enabled = true")

            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            sql = f"""
                SELECT id, name, policy_type, description, rule_config,
                       enabled, priority, created_by, created_at, updated_at
                FROM moderation_policies
                {where_sql}
                ORDER BY priority DESC, created_at DESC
            """

            result = await session.execute(text(sql), params)
            rows = result.fetchall()

            return {
                "total": len(rows),
                "policies": [
                    {
                        "id": str(r[0]), "name": r[1], "policy_type": r[2],
                        "description": r[3], "rule_config": r[4],
                        "enabled": r[5], "priority": r[6],
                        "created_by": r[7],
                        "created_at": str(r[8]) if r[8] else "",
                        "updated_at": str(r[9]) if r[9] else "",
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        # 降级: 返回空列表 (数据库不可用时)
        return {
            "total": 0,
            "policies": [],
            "error": f"数据库不可用: {str(e)[:100]}",
        }


@router.get("/{policy_id}")
async def get_policy(policy_id: str):
    """获取单条策略详情"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text("SELECT * FROM moderation_policies WHERE id = :id"),
                {"id": policy_id},
            )
            row = result.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="策略不存在")

            return {
                "id": str(row[0]), "name": row[1], "policy_type": row[2],
                "description": row[3], "rule_config": row[4],
                "enabled": row[5], "priority": row[6],
                "created_by": row[7],
                "created_at": str(row[8]) if row[8] else "",
                "updated_at": str(row[9]) if row[9] else "",
            }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)[:200]}")


@router.post("")
async def create_policy(policy: PolicyCreate):
    """创建新策略"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        if not policy.name or not policy.rule_config:
            raise HTTPException(status_code=400, detail="name和rule_config不能为空")

        valid_types = {"keyword", "regex", "sensitivity", "threshold", "model_route"}
        if policy.policy_type not in valid_types:
            raise HTTPException(status_code=400, detail=f"policy_type必须是: {valid_types}")

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text("""
                    INSERT INTO moderation_policies
                        (name, policy_type, description, rule_config, enabled, priority, created_by)
                    VALUES (:name, :type, :desc, :config, :enabled, :priority, :created_by)
                    RETURNING id
                """),
                {
                    "name": policy.name,
                    "type": policy.policy_type,
                    "desc": policy.description,
                    "config": json.dumps(policy.rule_config, ensure_ascii=False),
                    "enabled": policy.enabled,
                    "priority": policy.priority,
                    "created_by": policy.created_by,
                },
            )
            await session.commit()
            new_id = result.fetchone()[0]

            # 策略变更后刷新 ModelRouter 缓存
            _reload_policy_cache()

            return {"status": "created", "id": str(new_id), "name": policy.name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)[:200]}")


@router.put("/{policy_id}")
async def update_policy(policy_id: str, updates: PolicyUpdate):
    """更新策略 (支持部分更新)"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        set_parts = []
        params = {}

        if updates.name is not None:
            set_parts.append("name = :name")
            params["name"] = updates.name
        if updates.description is not None:
            set_parts.append("description = :desc")
            params["desc"] = updates.description
        if updates.rule_config is not None:
            set_parts.append("rule_config = :config")
            params["config"] = json.dumps(updates.rule_config, ensure_ascii=False)
        if updates.enabled is not None:
            set_parts.append("enabled = :enabled")
            params["enabled"] = updates.enabled
        if updates.priority is not None:
            set_parts.append("priority = :priority")
            params["priority"] = updates.priority

        if not set_parts:
            raise HTTPException(status_code=400, detail="没有提供要更新的字段")

        set_parts.append("updated_at = NOW()")
        set_sql = ", ".join(set_parts)
        params["pid"] = policy_id

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(f"UPDATE moderation_policies SET {set_sql} WHERE id = :pid"),
                params,
            )
            await session.commit()

        _reload_policy_cache()
        return {"status": "updated", "id": policy_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)[:200]}")


@router.delete("/{policy_id}")
async def delete_policy(policy_id: str):
    """删除策略"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM moderation_policies WHERE id = :id"),
                {"id": policy_id},
            )
            await session.commit()

        _reload_policy_cache()
        return {"status": "deleted", "id": policy_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)[:200]}")


@router.get("/cache/reload")
async def reload_cache():
    """手动刷新策略缓存"""
    await _reload_policy_cache_sync()
    cache = _policy_cache
    return {
        "status": "reloaded",
        "total_rules": len(cache.get("rules", [])),
        "types": list(cache.get("by_type", {}).keys()),
    }


async def _reload_policy_cache_sync():
    """同步刷新策略缓存（可 await）"""
    global _policy_cache
    rules = await _load_policies_from_db()
    by_type = {}
    for r in rules:
        pt = r["policy_type"]
        if pt not in by_type:
            by_type[pt] = []
        by_type[pt].append(r)
    _policy_cache = {
        "rules": rules,
        "by_type": by_type,
        "loaded_at": time.time(),
    }


# ===== 策略缓存 (避免每次请求都查DB) =====

_policy_cache: dict = {"rules": [], "by_type": {}, "loaded_at": 0}


async def _load_policies_from_db() -> list:
    """从数据库加载所有启用的策略"""
    try:
        from db.connection import get_session_factory
        from sqlalchemy import text

        factory = get_session_factory()
        async with factory() as session:
            result = await session.execute(
                text("""
                    SELECT id, name, policy_type, rule_config, enabled, priority
                    FROM moderation_policies
                    WHERE enabled = true
                    ORDER BY priority DESC
                """)
            )
            rows = result.fetchall()
            # SELECT 返回: id, name, policy_type, rule_config, enabled, priority (索引 0..5)
            return [
                {
                    "id": str(r[0]), "name": r[1], "policy_type": r[2],
                    "rule_config": r[3], "enabled": r[4], "priority": r[5],
                }
                for r in rows
            ]
    except Exception:
        return []


def _reload_policy_cache():
    """刷新策略缓存 (同步等待版本, 供 CRUD 端点使用)"""
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_reload_policy_cache_sync())
    except RuntimeError:
        asyncio.run(_reload_policy_cache_sync())


def get_policy_cache() -> dict:
    """获取当前策略缓存"""
    return _policy_cache


def get_active_threshold_config() -> dict:
    """
    获取当前生效的阈值配置，供 RiskAgent/TextAgent 等工作流组件使用。

    返回:
      {
        "review_threshold": 0.35,
        "reject_threshold": 0.75,
        "keyword_weight": 0.3,
        "semantic_weight": 0.5,
        "case_weight": 0.2,
      }
    如果数据库中没有阈值策略或缓存为空，返回默认值。
    """
    cache = get_policy_cache()
    threshold_policies = cache.get("by_type", {}).get("threshold", [])

    if threshold_policies:
        # 取优先级最高的已启用阈值策略
        best = threshold_policies[0]
        config = best.get("rule_config", {})
        if isinstance(config, str):
            import json as _json
            try:
                config = _json.loads(config)
            except Exception:
                config = {}
        return {
            "review_threshold": float(config.get("review_threshold", 0.35)),
            "reject_threshold": float(config.get("reject_threshold", 0.75)),
            "keyword_weight": float(config.get("keyword_weight", 0.3)),
            "semantic_weight": float(config.get("semantic_weight", 0.5)),
            "case_weight": float(config.get("case_weight", 0.2)),
        }

    # 默认值
    return {
        "review_threshold": 0.35,
        "reject_threshold": 0.75,
        "keyword_weight": 0.3,
        "semantic_weight": 0.5,
        "case_weight": 0.2,
    }


def get_active_keywords() -> list:
    """
    获取所有启用的敏感词策略中的关键词列表，供 keyword_check 工具使用。

    返回: ["关键词1", "关键词2", ...]
    """
    cache = get_policy_cache()
    keyword_policies = cache.get("by_type", {}).get("keyword", [])

    all_keywords = []
    for p in keyword_policies:
        config = p.get("rule_config", {})
        if isinstance(config, str):
            import json as _json
            try:
                config = _json.loads(config)
            except Exception:
                continue
        keywords = config.get("keywords", [])
        if isinstance(keywords, list):
            all_keywords.extend(keywords)

    return list(set(all_keywords))  # 去重
