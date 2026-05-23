"""
清空数据库工具
"""

import sqlite3
from pathlib import Path
import shutil
from datetime import datetime


def get_db_path():
    """获取数据库路径"""
    data_dir = Path(__file__).parent / "data"
    return data_dir / "question_bank.db"


def clear_database():
    """清空数据库所有题目"""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return False

    # 先备份
    backup_dir = Path(__file__).parent / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"question_bank_backup_{timestamp}.db"

    try:
        shutil.copy2(db_path, backup_path)
        print(f"✓ 已备份数据库到: {backup_path}")
    except Exception as e:
        print(f"⚠ 备份失败: {e}")
        confirm = input("是否继续清空? (yes/no): ")
        if confirm.lower() != "yes":
            print("已取消")
            return False

    # 清空数据库
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute("SELECT COUNT(*) FROM questions")
        count = cursor.fetchone()[0]

        conn.execute("DELETE FROM questions")
        # 重置自增计数器，让ID从1开始
        conn.execute("DELETE FROM sqlite_sequence WHERE name='questions'")
        conn.commit()
        conn.close()

        print(f"✓ 已清空数据库，共删除 {count} 道题目")
        return True

    except Exception as e:
        print(f"✗ 清空数据库失败: {e}")
        return False


def show_database_info():
    """显示数据库信息"""
    db_path = get_db_path()

    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return

    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # 总题目数
        cursor = conn.execute("SELECT COUNT(*) FROM questions")
        total = cursor.fetchone()[0]

        # 各类型题目数
        cursor = conn.execute("""
            SELECT question_type, COUNT(*) as count
            FROM questions
            GROUP BY question_type
        """)
        types = cursor.fetchall()

        # 最近更新的题目
        cursor = conn.execute("""
            SELECT question_text, answer, updated_at
            FROM questions
            ORDER BY updated_at DESC
            LIMIT 5
        """)
        recent = cursor.fetchall()

        conn.close()

        print("=" * 60)
        print("数据库信息")
        print("=" * 60)
        print(f"数据库路径: {db_path}")
        print(f"总题目数: {total}")
        print()

        if types:
            print("题目类型分布:")
            for row in types:
                print(f"  {row['question_type']}: {row['count']} 道")
            print()

        if recent:
            print("最近更新的5道题目:")
            for i, row in enumerate(recent, 1):
                text = row['question_text'][:40] + "..." if len(row['question_text']) > 40 else row['question_text']
                print(f"  {i}. {text}")
                print(f"     答案: {row['answer']} | 更新时间: {row['updated_at']}")
            print()

    except Exception as e:
        print(f"获取数据库信息失败: {e}")


if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  中石化答题助手 - 数据库管理工具")
    print("=" * 60)
    print()

    # 先显示数据库信息
    show_database_info()

    print()
    print("⚠ 警告: 此操作将删除所有题目数据！")
    print("⚠ 操作前已自动备份数据库")
    print()

    confirm = input("确认清空数据库? 输入 'CLEAR' 继续: ")

    if confirm == "CLEAR":
        clear_database()
    else:
        print("已取消")
