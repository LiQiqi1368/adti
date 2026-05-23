"""
错题更新后仍然答错的根本原因分析与修复

问题分析:
1. find_question 使用模糊匹配，当相似度 > threshold 时返回第一个匹配的题目
2. 如果数据库中有多条相似题目，可能匹配到错误的那条并更新
3. 考试回顾时 extract_question_data 可能读取的不是当前点击的题目内容
4. 历史数据库中可能存在同一题目的多个版本，答案互相覆盖

修复方案:
1. 在更新答案前，验证题目内容是否真正匹配
2. 当模糊匹配分数接近时，优先选择题目内容完全一致的
3. 添加 update_question_answer_if_better 方法，只有在新答案更确定时才更新
"""

import re
from utils import normalize_text, fuzzy_score, LETTER_ORDER


def verify_answer_consistency(answer: str, question_type: str) -> tuple[bool, str]:
    """
    验证答案格式是否与题目类型一致
    返回: (是否一致, 错误原因)
    """
    if not answer:
        return False, "答案为空"

    # 判断题
    if "判断" in (question_type or ""):
        if answer in ["正确", "错误"]:
            return True, ""
        return False, f"判断题答案应为'正确'或'错误'，实际为'{answer}'"

    # 单选题
    if "单选" in (question_type or ""):
        letters = [c for c in (answer or "").upper() if c in LETTER_ORDER]
        if len(letters) == 1:
            return True, ""
        # 如果是旧格式 (如 "A|||文字")
        if "|||" in answer:
            letters_part = answer.split("|||")[0]
            letters = [c for c in letters_part.upper() if c in LETTER_ORDER]
            if len(letters) == 1:
                return True, ""
        return False, f"单选题答案应为单个字母，实际为'{answer}'"

    # 多选题
    if "多选" in (question_type or ""):
        letters = [c for c in (answer or "").upper() if c in LETTER_ORDER]
        if len(letters) >= 2:
            return True, ""
        # 如果是旧格式 (如 "A|||文字")
        if "|||" in answer:
            letters_part = answer.split("|||")[0]
            letters = [c for c in letters_part.upper() if c in LETTER_ORDER]
            if len(letters) >= 2:
                return True, ""
        return False, f"多选题答案应为多字母组合(如ACD)，实际为'{answer}'"

    # 未知类型，不做验证
    return True, ""


def suggest_answer_fix(answer: str, question_type: str) -> str:
    """
    如果答案格式不正确，尝试修复
    """
    if not answer:
        return ""

    # 判断题
    if "判断" in (question_type or ""):
        answer_clean = (answer or "").strip()
        if answer_clean in ["对", "√", "T"]:
            return "正确"
        if answer_clean in ["错", "×", "F"]:
            return "错误"
        return answer

    return answer


def is_question_text_match(q1_text: str, q2_text: str, threshold: float = 0.90) -> bool:
    """
    判断两个题目文本是否足够相似（用于验证是否同一题）
    """
    if not q1_text or not q2_text:
        return False

    norm1 = normalize_text(q1_text)
    norm2 = normalize_text(q2_text)

    # 完全相同
    if norm1 == norm2:
        return True

    # 相似度足够高
    score = fuzzy_score(norm1, norm2)
    return score >= threshold


def find_best_matching_question(
    question_text: str,
    options: list[str],
    db_rows: list,
    threshold: float = 0.82
) -> tuple[dict | None, float]:
    """
    改进的模糊匹配：优先选择题目内容更一致的
    返回: (最佳匹配行, 匹配分数)
    """
    if not db_rows:
        return None, 0.0

    user_text_norm = normalize_text(question_text)
    user_opts_norm = [normalize_text(o) for o in (options or []) if o]

    best_row = None
    best_score = 0.0
    best_text_score = 0.0  # 纯文本相似度

    for row in db_rows:
        row_text_norm = normalize_text(row["question_text"] or "")

        # 计算文本相似度
        text_score = fuzzy_score(user_text_norm, row_text_norm)

        # 计算综合分数（文本相似度为主）
        score = text_score

        if score > best_score:
            # 检查选项匹配度
            db_opts_norm = [normalize_text(x) for x in [
                row.get("option_a", "") or "",
                row.get("option_b", "") or "",
                row.get("option_c", "") or "",
                row.get("option_d", "") or "",
                row.get("option_e", "") or "",
                row.get("option_f", "") or "",
            ] if x]

            # 选项匹配度
            opt_match_score = 0.0
            if user_opts_norm and db_opts_norm:
                matched = 0
                for uo in user_opts_norm:
                    for do in db_opts_norm:
                        if fuzzy_score(uo, do) > 0.7:
                            matched += 1
                            break
                opt_match_score = matched / max(len(user_opts_norm), 1)

            # 综合分数：文本80% + 选项20%
            combined_score = score * 0.8 + opt_match_score * 0.2

            # 新的最佳分数
            if combined_score > best_score:
                best_score = combined_score
                best_text_score = text_score
                best_row = row

    # 检查最佳匹配的文本相似度是否足够高
    if best_row and best_text_score >= threshold:
        return best_row, best_score

    return None, 0.0


# ============ 测试代码 ============
if __name__ == "__main__":
    # 测试用例
    test_cases = [
        # 多选题答案格式
        ("ACD", "多选题", True),
        ("A", "多选题", False),  # 单个字母对多选题来说不对
        ("ABD", "多选题", True),
        ("", "多选题", False),
        ("A,C,D", "多选题", True),  # 逗号分隔也算

        # 单选题答案格式
        ("A", "单选题", True),
        ("AB", "单选题", False),  # 多选字母对单选不对
        ("", "单选题", False),

        # 判断题答案格式
        ("正确", "判断题", True),
        ("错误", "判断题", True),
        ("对", "判断题", False),  # 应该转换为"正确"
        ("A", "判断题", False),
    ]

    print("=" * 60)
    print("答案一致性验证测试")
    print("=" * 60)

    for answer, qtype, expected in test_cases:
        is_valid, error = verify_answer_consistency(answer, qtype)
        status = "✓" if is_valid == expected else "✗"
        print(f"{status} 答案='{answer}' 类型='{qtype}' 验证={is_valid}", end="")
        if error:
            print(f" 原因: {error}")
        else:
            print()

    print()
    print("=" * 60)
    print("答案修复建议测试")
    print("=" * 60)

    fix_cases = [
        ("对", "判断题", "正确"),
        ("错", "判断题", "错误"),
        ("A", "判断题", "A"),
        ("正确", "判断题", "正确"),
    ]

    for answer, qtype, expected in fix_cases:
        fixed = suggest_answer_fix(answer, qtype)
        status = "✓" if fixed == expected else "✗"
        print(f"{status} '{answer}' -> '{fixed}' (期望: '{expected}')")
