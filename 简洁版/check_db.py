"""
错题诊断与修复工具
功能：
1. 检查数据库中所有题目答案的格式是否正确
2. 识别多选题答案格式错误（只存了单字母）
3. 检查相似题目可能导致匹配错误
4. 修复错误的答案数据
"""

import sys
import sqlite3
from pathlib import Path
from difflib import SequenceMatcher

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from utils import normalize_answer, normalize_text


def get_db_path():
    """获取数据库路径"""
    data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "questions.db"


def diagnose_database():
    """诊断数据库中的问题"""
    db_path = get_db_path()
    if not db_path.exists():
        print(f"数据库不存在: {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.execute("SELECT COUNT(*) FROM questions")
    total = cursor.fetchone()[0]
    print(f"=" * 60)
    print(f"数据库诊断报告")
    print(f"=" * 60)
    print(f"数据库路径: {db_path}")
    print(f"总题目数: {total}")
    print()

    # 1. 检查多选题答案格式问题
    print("【1】多选题答案格式检查")
    print("-" * 40)
    cursor = conn.execute("""
        SELECT id, question_text, question_type, answer
        FROM questions
        WHERE question_type LIKE '%多选%'
    """)
    multi_questions = cursor.fetchall()

    format_errors = []
    for row in multi_questions:
        answer = row["answer"] or ""
        # 多选题答案应该包含多个字母（A,B,C,D组合）
        letters = [c for c in answer.upper() if c in "ABCDEF"]
        if len(letters) <= 1 and "多选" in (row["question_type"] or ""):
            format_errors.append({
                "id": row["id"],
                "question": row["question_text"][:50],
                "current_answer": answer,
                "expected_format": "多字母组合如: ACD"
            })

    if format_errors:
        print(f"发现 {len(format_errors)} 道多选题答案格式可能有问题:")
        for err in format_errors[:10]:  # 只显示前10条
            print(f"  ID={err['id']}: {err['question']}...")
            print(f"    当前答案: '{err['current_answer']}' (应为多字母如 'ACD')")
            print()
        if len(format_errors) > 10:
            print(f"  ... 还有 {len(format_errors) - 10} 条")
    else:
        print("未发现多选题答案格式问题")
    print()

    # 2. 检查判断题答案格式
    print("【2】判断题答案格式检查")
    print("-" * 40)
    cursor = conn.execute("""
        SELECT id, question_text, question_type, answer
        FROM questions
        WHERE question_type LIKE '%判断%'
    """)
    judge_questions = cursor.fetchall()

    judge_errors = []
    for row in judge_questions:
        answer = (row["answer"] or "").strip()
        if answer not in ["正确", "错误", ""]:
            judge_errors.append({
                "id": row["id"],
                "question": row["question_text"][:50],
                "current_answer": answer,
                "expected": "正确 或 错误"
            })

    if judge_errors:
        print(f"发现 {len(judge_errors)} 道判断题答案格式可能有问题:")
        for err in judge_errors[:10]:
            print(f"  ID={err['id']}: {err['question']}...")
            print(f"    当前答案: '{err['current_answer']}' (应为 '正确' 或 '错误')")
            print()
    else:
        print("未发现判断题答案格式问题")
    print()

    # 3. 检查相似题目（可能导致匹配错误）
    print("【3】相似题目检查（同一题有多个版本）")
    print("-" * 40)

    # 按题目文本分组，查找相似题目
    all_questions = conn.execute("""
        SELECT id, question_text, question_text_normalized, answer, updated_at
        FROM questions
        ORDER BY question_text_normalized
    """).fetchall()

    similar_groups = []
    for i in range(len(all_questions)):
        for j in range(i + 1, len(all_questions)):
            q1 = all_questions[i]
            q2 = all_questions[j]
            # 如果标准化后的文本相似度很高
            score = SequenceMatcher(
                None,
                q1["question_text_normalized"] or "",
                q2["question_text_normalized"] or ""
            ).ratio()
            if score > 0.85:  # 相似度超过85%
                # 但不是完全相同
                if q1["question_text_normalized"] != q2["question_text_normalized"]:
                    similar_groups.append({
                        "q1_id": q1["id"],
                        "q1_text": q1["question_text"][:40],
                        "q1_answer": q1["answer"],
                        "q2_id": q2["id"],
                        "q2_text": q2["question_text"][:40],
                        "q2_answer": q2["answer"],
                        "similarity": score
                    })

    if similar_groups:
        print(f"发现 {len(similar_groups)} 组相似题目（可能互相覆盖）:")
        for group in similar_groups[:5]:  # 只显示前5组
            print(f"  题目1 (ID={group['q1_id']}): {group['q1_text']}...")
            print(f"    答案: {group['q1_answer']}")
            print(f"  题目2 (ID={group['q2_id']}): {group['q2_text']}...")
            print(f"    答案: {group['q2_answer']}")
            print(f"  相似度: {group['similarity']:.2%}")
            print()
    else:
        print("未发现明显相似的重复题目")
    print()

    # 4. 检查答案格式不规范
    print("【4】答案格式综合检查")
    print("-" * 40)
    cursor = conn.execute("SELECT id, question_text, question_type, answer FROM questions")
    all_questions = cursor.fetchall()

    irregular_answers = []
    for row in all_questions:
        answer = row["answer"] or ""
        qtype = row["question_type"] or ""

        # 判断题应该是"正确"或"错误"
        if "判断" in qtype:
            if answer not in ["正确", "错误", ""]:
                irregular_answers.append({
                    "id": row["id"],
                    "type": "判断题",
                    "answer": answer,
                    "issue": f"判断题答案应为'正确'或'错误'，实际为'{answer}'"
                })
        # 单选题应该是单个字母
        elif "单选" in qtype:
            letters = [c for c in answer.upper() if c in "ABCDEF"]
            if len(letters) != 1:
                irregular_answers.append({
                    "id": row["id"],
                    "type": "单选题",
                    "answer": answer,
                    "issue": f"单选题答案应为单个字母，实际为'{answer}'"
                })
        # 多选题应该是多个字母组合
        elif "多选" in qtype:
            letters = [c for c in answer.upper() if c in "ABCDEF"]
            if len(letters) < 2:
                irregular_answers.append({
                    "id": row["id"],
                    "type": "多选题",
                    "answer": answer,
                    "issue": f"多选题答案应为多字母组合，实际为'{answer}'"
                })

    if irregular_answers:
        print(f"发现 {len(irregular_answers)} 道题目答案格式不规范:")
        for err in irregular_answers[:15]:
            print(f"  ID={err['id']} ({err['type']}): {err['issue']}")
            print()
        if len(irregular_answers) > 15:
            print(f"  ... 还有 {len(irregular_answers) - 15} 条")
    else:
        print("所有题目答案格式均正确")
    print()

    # 5. 统计汇总
    print("=" * 60)
    print("诊断汇总")
    print("=" * 60)
    print(f"总题目数: {total}")
    print(f"多选题格式问题: {len(format_errors)}")
    print(f"判断题格式问题: {len(judge_errors)}")
    print(f"相似题目组数: {len(similar_groups)}")
    print(f"不规范答案总数: {len(irregular_answers)}")
    print()

    conn.close()
    return {
        "total": total,
        "multi_errors": format_errors,
        "judge_errors": judge_errors,
        "similar_groups": similar_groups,
        "irregular_answers": irregular_answers
    }


def fix_database():
    """尝试修复数据库中的问题（谨慎操作）"""
    print()
    print("=" * 60)
    print("数据库修复模式")
    print("=" * 60)
    print("警告：此操作会修改数据库，请先备份！")
    print()

    db_path = get_db_path()
    if not db_path.exists():
        print("数据库不存在")
        return

    confirm = input("是否继续修复? (yes/no): ")
    if confirm.lower() != "yes":
        print("已取消")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    fixed_count = 0

    # 1. 修复判断题答案
    print("正在修复判断题答案...")
    cursor = conn.execute("""
        SELECT id, answer FROM questions
        WHERE question_type LIKE '%判断%'
        AND answer NOT IN ('正确', '错误', '')
    """)
    for row in cursor.fetchall():
        old_answer = row["answer"] or ""
        # 尝试转换
        new_answer = ""
        if old_answer in ["对", "√", "T", "true", "True"]:
            new_answer = "正确"
        elif old_answer in ["错", "×", "F", "false", "False"]:
            new_answer = "错误"
        else:
            # 无法识别，保留原样
            continue

        conn.execute(
            "UPDATE questions SET answer = ?, updated_at = ? WHERE id = ?",
            (new_answer, "2026-05-06 12:00:00", row["id"])
        )
        print(f"  ID={row['id']}: '{old_answer}' -> '{new_answer}'")
        fixed_count += 1

    # 2. 修复多选题答案（如果存储格式有问题）
    print("正在检查多选题答案...")
    cursor = conn.execute("""
        SELECT id, answer FROM questions
        WHERE question_type LIKE '%多选%'
    """)
    for row in cursor.fetchall():
        answer = row["answer"] or ""
        # 如果答案包含|||分隔符，检查文字部分是否完整
        if "|||" in answer:
            parts = answer.split("|||")
            letters = parts[0] if len(parts) > 0 else ""
            texts = parts[1] if len(parts) > 1 else ""
            text_list = texts.split(",") if texts else []

            # 检查字母数量和文字数量是否一致
            expected_count = len([c for c in letters.upper() if c in "ABCDEF"])
            actual_count = len([t for t in text_list if t.strip()])

            if expected_count != actual_count and expected_count > 0:
                print(f"  ID={row['id']}: 答案格式异常 '{answer}' (字母{expected_count}个vs文字{actual_count}个)")
                # 保留原样，不自动修复

    conn.commit()
    conn.close()

    print()
    print(f"修复完成，共修复 {fixed_count} 道题目")
    print("提示：建议使用诊断功能重新检查修复后的数据")


def export_problem_questions():
    """导出有问题的题目到文件"""
    print()
    print("=" * 60)
    print("导出问题题目")
    print("=" * 60)

    db_path = get_db_path()
    if not db_path.exists():
        print("数据库不存在")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # 导出所有题目到CSV
    cursor = conn.execute("""
        SELECT id, question_type, question_text, answer, analysis, updated_at
        FROM questions
        ORDER BY id
    """)

    output_path = Path(__file__).parent / "data" / "questions_export.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("ID,题目类型,题目文本,答案,解析,更新时间\n")
        for row in cursor.fetchall():
            question_text = (row["question_text"] or "").replace("\n", " ").replace(",", "，")
            answer = (row["answer"] or "").replace(",", "，")
            analysis = (row["analysis"] or "").replace("\n", " ").replace(",", "，")
            f.write(f"{row['id']},{row['question_type']},{question_text},{answer},{analysis},{row['updated_at']}\n")

    print(f"已导出到: {output_path}")
    conn.close()


if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  中石化答题助手 - 错题诊断与修复工具")
    print("=" * 60)
    print()
    print("选项:")
    print("  1. 诊断数据库（只读，不修改数据）")
    print("  2. 修复数据库（谨慎修改）")
    print("  3. 导出所有题目到CSV")
    print()

    choice = input("请选择 (1/2/3): ").strip()

    if choice == "1":
        diagnose_database()
    elif choice == "2":
        fix_database()
    elif choice == "3":
        export_problem_questions()
    else:
        print("无效选择")
