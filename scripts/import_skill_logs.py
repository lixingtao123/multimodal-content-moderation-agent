#!/usr/bin/env python3
"""
导入 Skill 路由日志到数据库
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
import asyncio

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent / ".." / "src" / "backend"))


async def import_logs():
    print("""
╔══════════════════════════════════════════════════════════╗
║  📥 导入 Skill 路由日志到数据库                         ║
╚══════════════════════════════════════════════════════════╝
    """)

    from db.connection import init_db, get_session_factory
    from db.models import SkillRoutingLog

    # 初始化数据库
    await init_db()

    # 读取日志文件
    logs_file = Path("/workspace/skill_demo_data/skill_routing_logs.jsonl")

    if not logs_file.exists():
        print(f"❌ 日志文件不存在: {logs_file}")
        return

    logs_to_import = []
    with open(logs_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    log_data = json.loads(line)
                    logs_to_import.append(log_data)
                except Exception as e:
                    print(f"⚠️ 解析失败: {e}")

    print(f"✅ 读取到 {len(logs_to_import)} 条日志")

    # 导入到数据库
    session_factory = get_session_factory()
    imported_count = 0

    async with session_factory() as session:
        # 检查是否已有数据
        from sqlalchemy import select, func
        result = await session.execute(select(func.count(SkillRoutingLog.id)))
        existing_count = result.scalar()
        print(f"📊 数据库现有日志: {existing_count} 条")

        for log_data in logs_to_import:
            # 解析时间戳
            ts = log_data.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(timezone.utc)

            # 字段兼容性处理：支持 filtered/selected/ranked 或 filtered_skills/ranked_skills/selected_skills
            filtered = log_data.get("filtered_skills", log_data.get("filtered", []))
            ranked = log_data.get("ranked_skills", log_data.get("ranked", []))
            selected = log_data.get("selected_skills", log_data.get("selected", []))

            log_entry = SkillRoutingLog(
                content_id=log_data.get("content_id", ""),
                agent=log_data.get("agent", "text_agent"),
                query=log_data.get("query", ""),
                content_type=log_data.get("content_type", "text"),
                filtered_skills=filtered,
                ranked_skills=ranked,
                selected_skills=selected,
                timestamp=timestamp,
                created_at=datetime.now(timezone.utc)
            )
            session.add(log_entry)
            imported_count += 1

        await session.commit()

    print(f"✅ 成功导入 {imported_count} 条日志")

    # 统计使用情况
    print(f"\n{'=' * 60}")
    print("📊 Skill 使用统计")
    print('=' * 60)

    skill_count = {}
    for log_data in logs_to_import:
        selected = log_data.get("selected_skills", log_data.get("selected", []))
        for skill in selected:
            skill_count[skill] = skill_count.get(skill, 0) + 1

    if skill_count:
        for skill, count in sorted(skill_count.items(), key=lambda x: -x[1]):
            print(f"  {skill:25s}: {count:3d} 次")
    else:
        print("  (无 Skill 使用数据)")

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  🎉 导入完成！                                           ║
║                                                           ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！           ║
║  在「路由日志」标签页可以查看 Filter → Rank → Select 过程  ║
╚══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    asyncio.run(import_logs())
