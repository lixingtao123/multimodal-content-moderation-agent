#!/usr/bin/env python3
"""
导入 Skill 路由日志到数据库 (同步版本，直接用 psycopg2)
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone
import psycopg2
from psycopg2.extras import execute_values


def import_logs():
    print("""
╔══════════════════════════════════════════════════════════╗
║  📥 导入 Skill 路由日志到数据库                         ║
╚══════════════════════════════════════════════════════════╝
    """)

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

    # 连接数据库
    conn = psycopg2.connect(
        dbname="moderation",
        user="postgres",
        password="postgres",
        host="localhost",
        port=15432
    )

    try:
        cur = conn.cursor()

        # 检查是否已有数据
        cur.execute("SELECT COUNT(*) FROM skill_routing_logs")
        existing_count = cur.fetchone()[0]
        print(f"📊 数据库现有日志: {existing_count} 条")

        # 准备插入数据
        rows = []
        for log_data in logs_to_import:
            # 解析时间戳
            ts = log_data.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now(timezone.utc)

            # 字段兼容性处理
            filtered = log_data.get("filtered_skills", log_data.get("filtered", []))
            ranked = log_data.get("ranked_skills", log_data.get("ranked", []))
            selected = log_data.get("selected_skills", log_data.get("selected", []))

            rows.append((
                log_data.get("content_id", ""),
                log_data.get("agent", "text_agent"),
                log_data.get("query", ""),
                log_data.get("content_type", "text"),
                filtered,
                ranked,
                selected,
                timestamp
            ))

        # 批量插入
        execute_values(
            cur,
            """
            INSERT INTO skill_routing_logs
            (content_id, agent, query, content_type, filtered_skills, ranked_skills, selected_skills, timestamp)
            VALUES %s
            """,
            rows
        )

        imported_count = cur.rowcount
        conn.commit()
        print(f"✅ 成功导入 {imported_count} 条日志")

        # 统计使用情况
        print(f"\n{'=' * 60}")
        print("📊 Skill 使用统计")
        print('=' * 60)

        cur.execute("""
            SELECT unnest(selected_skills) as skill, COUNT(*) as cnt
            FROM skill_routing_logs
            GROUP BY skill
            ORDER BY cnt DESC
        """)

        for skill, count in cur.fetchall():
            print(f"  {skill:25s}: {count:3d} 次")

        cur.close()

    except Exception as e:
        conn.rollback()
        print(f"❌ 导入失败: {e}")
        raise
    finally:
        conn.close()

    print(f"""
╔══════════════════════════════════════════════════════════╗
║  🎉 导入完成！                                           ║
║                                                           ║
║  现在可以访问前端 Skill 管理页面查看使用统计了！           ║
║  在「路由日志」标签页可以查看 Filter → Rank → Select 过程  ║
╚══════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    import_logs()
