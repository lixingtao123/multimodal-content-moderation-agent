"""清理旧的优化建议数据"""
import asyncio
from pathlib import Path


async def main():
    reports_dir = Path("/workspace/skills_backups/reports")

    if not reports_dir.exists():
        print(f"报告目录不存在: {reports_dir}")
        return

    print(f"清理旧报告...")
    count = 0

    for report_file in reports_dir.glob("*.json"):
        print(f"删除: {report_file.name}")
        report_file.unlink()
        count += 1

    print(f"\n✅ 共清理 {count} 份报告")


if __name__ == "__main__":
    asyncio.run(main())
