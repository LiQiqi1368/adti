"""
测试修复功能的正确性
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from utils import normalize_text, fuzzy_score, LETTER_ORDER
from db import QuestionDB
import tempfile
import os


def test_answer_verification():
    """测试答案验证功能"""
    print("=" * 60)
    print("测试 1: 答案格式验证")
    print("=" * 60)

    # 创建临时数据库
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        db = QuestionDB(db_path)

        test_cases = [
            # (答案, 题目类型, 期望修复后答案, 是否应修复)
            ("对", "判断题", "正确", True),
            ("错", "判断题", "错误", True),
            ("正确", "判断题", "正确", False),
            ("A", "单选题", "A", False),
            ("AB", "单选题", "A", True),  # 多选字母对单选应修复
            ("ACD", "多选题", "ACD", False),
            ("A", "多选题", "A", False),  # 单字母对多选不自动修复
        ]

        all_passed = True
        for answer, qtype, expected, should_fix in test_cases:
            fixed, was_fixed = db.verify_and_fix_answer(answer, qtype)
            passed = (fixed == expected and was_fixed == should_fix)
            status = "✓" if passed else "✗"
            print(f"{status} 答案='{answer}' 类型='{qtype}' -> '{fixed}' (期望: '{expected}') 修复={was_fixed}")
            if not passed:
                all_passed = False

        print()
        if all_passed:
            print("✓ 所有答案验证测试通过")
        else:
            print("✗ 部分测试失败")

    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(db_path)
        except:
            pass


def test_options_match_score():
    """测试选项匹配分数计算"""
    print()
    print("=" * 60)
    print("测试 2: 选项匹配分数计算")
    print("=" * 60)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        db = QuestionDB(db_path)

        # 测试选项匹配分数
        user_opts = ["选项A", "选项B", "选项C"]
        db_opts_match = ["选项A", "选项B", "选项C"]  # 完全匹配
        db_opts_partial = ["选项A", "选项X", "选项C"]  # 部分匹配
        db_opts_no_match = ["选项X", "选项Y", "选项Z"]  # 不匹配

        score1 = db._options_match_score(user_opts, db_opts_match)
        score2 = db._options_match_score(user_opts, db_opts_partial)
        score3 = db._options_match_score(user_opts, db_opts_no_match)

        print(f"完全匹配分数: {score1:.2f} (期望: 1.00)")
        print(f"部分匹配分数: {score2:.2f} (期望: ~0.67)")
        print(f"不匹配分数: {score3:.2f} (期望: 0.00)")

        # 验证
        passed = (score1 == 1.0 and score2 > 0.5 and score3 == 0.0)
        status = "✓" if passed else "✗"
        print(f"{status} 选项匹配分数测试")

    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(db_path)
        except:
            pass


def test_find_question_improvement():
    """测试改进后的 find_question"""
    print()
    print("=" * 60)
    print("测试 3: 改进的 find_question 匹配逻辑")
    print("=" * 60)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        db = QuestionDB(db_path)

        # 插入测试数据
        db.insert_question_if_not_exists(
            question_type="单选题",
            question_text="什么是问责的主要方式",
            options=["A. 通报", "B. 诫勉", "C. 组织调整", "D. 以上都是"],
            answer="D",
            analysis="",
            source="test"
        )

        db.insert_question_if_not_exists(
            question_type="单选题",
            question_text="什么是问责的直接方式",
            options=["A. 通报", "B. 诫勉", "C. 组织调整", "D. 以上都是"],
            answer="A",
            analysis="",
            source="test"
        )

        # 测试查找
        result1 = db.find_question(
            "什么是问责的主要方式",
            ["A. 通报", "B. 诫勉", "C. 组织调整", "D. 以上都是"],
            threshold=0.82
        )

        result2 = db.find_question(
            "什么是问责的直接方式",
            ["A. 通报", "B. 诫勉", "C. 组织调整", "D. 以上都是"],
            threshold=0.82
        )

        print(f"查找'主要方式': {'找到' if result1 else '未找到'}")
        if result1:
            print(f"  答案: {result1.get('answer')}")
            print(f"  匹配分数: {result1.get('_match_score', 0):.2f}")

        print(f"查找'直接方式': {'找到' if result2 else '未找到'}")
        if result2:
            print(f"  答案: {result2.get('answer')}")
            print(f"  匹配分数: {result2.get('_match_score', 0):.2f}")

        # 验证找到的答案是正确的
        passed = True
        if result1 and result1.get('answer') != 'D':
            print("✗ '主要方式' 应该匹配答案 D")
            passed = False
        if result2 and result2.get('answer') != 'A':
            print("✗ '直接方式' 应该匹配答案 A")
            passed = False

        status = "✓" if passed else "✗"
        print(f"{status} find_question 改进测试")

    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(db_path)
        except:
            pass


def test_similar_questions():
    """测试相似题目的区分"""
    print()
    print("=" * 60)
    print("测试 4: 相似题目区分")
    print("=" * 60)

    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name

    try:
        db = QuestionDB(db_path)

        # 插入两道非常相似的题目
        db.insert_question_if_not_exists(
            question_type="单选题",
            question_text="根据《中国共产党问责条例》，对党组织的问责方式包括检查、通报、改组",
            options=["A. 正确", "B. 错误"],
            answer="A",
            analysis="",
            source="test"
        )

        db.insert_question_if_not_exists(
            question_type="单选题",
            question_text="根据《中国共产党问责条例》，对党组织的问责方式包括检查、通报、解散",
            options=["A. 正确", "B. 错误"],
            answer="B",
            analysis="",
            source="test"
        )

        # 查找第一题
        result1 = db.find_question(
            "根据《中国共产党问责条例》，对党组织的问责方式包括检查、通报、改组",
            ["A. 正确", "B. 错误"],
            threshold=0.82
        )

        # 查找第二题
        result2 = db.find_question(
            "根据《中国共产党问责条例》，对党组织的问责方式包括检查、通报、解散",
            ["A. 正确", "B. 错误"],
            threshold=0.82
        )

        print(f"查找'改组'版本: {'找到' if result1 else '未找到'}")
        if result1:
            print(f"  答案: {result1.get('answer')} (期望: A)")

        print(f"查找'解散'版本: {'找到' if result2 else '未找到'}")
        if result2:
            print(f"  答案: {result2.get('answer')} (期望: B)")

        # 验证
        passed = True
        if result1 and result1.get('answer') != 'A':
            print("✗ '改组'版本应该匹配答案 A")
            passed = False
        if result2 and result2.get('answer') != 'B':
            print("✗ '解散'版本应该匹配答案 B")
            passed = False

        status = "✓" if passed else "✗"
        print(f"{status} 相似题目区分测试")

    finally:
        try:
            db.close()
        except:
            pass
        try:
            os.unlink(db_path)
        except:
            pass


if __name__ == "__main__":
    print()
    print("=" * 60)
    print("  中石化答题助手 - 修复功能测试")
    print("=" * 60)
    print()

    test_answer_verification()
    test_options_match_score()
    test_find_question_improvement()
    test_similar_questions()

    print()
    print("=" * 60)
    print("测试完成")
    print("=" * 60)
