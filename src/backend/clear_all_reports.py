"""清除所有优化报告"""
from pathlib import Path

reports_dir = Path("/workspace/skills_backups/reports")
count = 0

for f in reports_dir.glob("skill_opt_*.json"):
    print(f"删除: {f.name}")
    f.unlink()
    count += 1

print(f"\n✅ 已清理 {count} 份旧报告")
