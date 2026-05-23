from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from utils import build_unique_key, fuzzy_score, normalize_text, now_str


class QuestionDB:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_text TEXT NOT NULL,
                question_text_normalized TEXT NOT NULL,
                option_a TEXT DEFAULT '',
                option_b TEXT DEFAULT '',
                option_c TEXT DEFAULT '',
                option_d TEXT DEFAULT '',
                option_e TEXT DEFAULT '',
                option_f TEXT DEFAULT '',
                question_type TEXT DEFAULT '单选',
                answer TEXT NOT NULL,
                analysis TEXT DEFAULT '',
                source TEXT DEFAULT '',
                unique_key TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_questions_unique_key ON questions(unique_key)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_questions_question_text_normalized ON questions(question_text_normalized)")
        self.conn.commit()

    def find_question(self, question_text: str, options: list[str], threshold: float = 0.82) -> dict[str, Any] | None:
        unique_key = build_unique_key(question_text, options)
        row = self.conn.execute("SELECT * FROM questions WHERE unique_key = ? LIMIT 1", (unique_key,)).fetchone()
        if row:
            return dict(row)

        exact = self.conn.execute(
            "SELECT * FROM questions WHERE question_text_normalized = ? ORDER BY updated_at DESC LIMIT 1",
            (normalize_text(question_text),),
        ).fetchone()
        if exact:
            return dict(exact)

        best_row = None
        best_score = 0.0
        # 用 normalized 后的用户选项做二次验证
        user_opts_norm = [normalize_text(o) for o in (options or []) if o]

        for row in self.conn.execute("SELECT * FROM questions ORDER BY id ASC").fetchall():
            # 计算文本相似度
            text_score = fuzzy_score(question_text, row["question_text"])

            # 计算选项匹配度
            db_opts = self._get_question_options(row["id"])
            opt_match_score = self._options_match_score(user_opts_norm, db_opts)

            # 综合分数：文本相似度为主(80%)，选项匹配度为辅(20%)
            combined_score = text_score * 0.8 + opt_match_score * 0.2

            if combined_score > best_score:
                # 如果分数接近，额外检查选项是否更匹配
                if best_row and abs(combined_score - best_score) < 0.05:
                    # 现任者选项匹配度
                    curr_db_opts = self._get_question_options(best_row["id"])
                    curr_opt_score = self._options_match_score(user_opts_norm, curr_db_opts)
                    # 如果现任者选项匹配度更好，保留现任者
                    if curr_opt_score > opt_match_score:
                        continue

                best_score = combined_score
                best_row = row

        if best_row and best_score >= float(threshold):
            result = dict(best_row)
            result["_match_score"] = best_score
            return result
        return None

    def _options_match_score(self, user_opts: list[str], db_opts: list[str]) -> float:
        """计算用户选项与数据库选项的匹配分数 (0.0-1.0)"""
        if not user_opts:
            return 0.5  # 没有用户选项，返回中等分数
        if not db_opts:
            return 0.0
        matched = 0
        for uo in user_opts:
            if not uo:
                continue
            for do in db_opts:
                if not do:
                    continue
                if fuzzy_score(uo, do) > 0.6:
                    matched += 1
                    break
        return matched / max(len(user_opts), 1)

    def verify_and_fix_answer(self, answer: str, question_type: str) -> tuple[str, bool]:
        """
        验证答案格式是否与题目类型一致，如果不一致则尝试修复
        返回: (修复后的答案, 是否已修改)
        """
        if not answer:
            return answer, False

        # 判断题
        if "判断" in (question_type or ""):
            if answer in ["正确", "错误"]:
                return answer, False
            # 尝试转换
            if answer.strip() in ["对", "√", "T", "true", "True"]:
                return "正确", True
            if answer.strip() in ["错", "×", "F", "false", "False"]:
                return "错误", True
            return answer, False

        # 单选题 - 应该是单个字母
        if "单选" in (question_type or ""):
            # 提取字母部分（如果是复合格式）
            letters_part = answer
            if "|||" in answer:
                letters_part = answer.split("|||")[0]
            letters = [c for c in letters_part.upper() if c in "ABCDEF"]
            if len(letters) == 1:
                return answer, False
            # 如果有多个字母只取第一个（可能是录错了）
            if len(letters) > 1:
                first_letter = letters[0]
                if "|||" in answer:
                    parts = answer.split("|||")
                    texts = parts[1] if len(parts) > 1 else ""
                    return f"{first_letter}|||{texts}", True
                return first_letter, True
            return answer, False

        # 多选题 - 应该是多个字母组合
        if "多选" in (question_type or ""):
            letters_part = answer
            if "|||" in answer:
                letters_part = answer.split("|||")[0]
            letters = [c for c in letters_part.upper() if c in "ABCDEF"]
            if len(letters) >= 2:
                return answer, False
            # 单字母多选题答案，可能录错了，需要重新提取
            if len(letters) == 1:
                return answer, False  # 不自动修复，需要重新从解析提取
            return answer, False

        return answer, False

    def _get_question_options(self, qid: int) -> list[str]:
        """获取题目的选项列表"""
        row = self.conn.execute(
            "SELECT option_a, option_b, option_c, option_d, option_e, option_f FROM questions WHERE id = ?",
            (qid,),
        ).fetchone()
        if not row:
            return []
        return [normalize_text(x) for x in row if x]

    def _options_match(self, user_opts: list[str], db_opts: list[str]) -> bool:
        """检查用户选项是否与数据库选项匹配（至少部分匹配）"""
        if not user_opts or not db_opts:
            return True  # 没有选项时不阻拦
        matched = 0
        for uo in user_opts:
            if not uo:
                continue
            for do in db_opts:
                if not do:
                    continue
                if fuzzy_score(uo, do) > 0.6:
                    matched += 1
                    break
        return matched >= max(1, len(user_opts) // 2)

    def insert_question_if_not_exists(self, question_type: str, question_text: str, options: list[str], answer: str, analysis: str, source: str) -> tuple[bool, int]:
        unique_key = build_unique_key(question_text, options)
        existing = self.conn.execute("SELECT id FROM questions WHERE unique_key = ? LIMIT 1", (unique_key,)).fetchone()
        if existing:
            return False, int(existing["id"])

        opts = list(options or [])[:6] + [""] * (6 - len(list(options or [])[:6]))
        now = now_str()
        cursor = self.conn.execute(
            """
            INSERT INTO questions (
                question_text, question_text_normalized,
                option_a, option_b, option_c, option_d, option_e, option_f,
                question_type, answer, analysis, source, unique_key, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                question_text,
                normalize_text(question_text),
                opts[0], opts[1], opts[2], opts[3], opts[4], opts[5],
                question_type,
                answer,
                analysis,
                source,
                unique_key,
                now,
                now,
            ),
        )
        self.conn.commit()
        return True, int(cursor.lastrowid)

    def update_question_answer(self, record_id: int, new_answer: str, new_analysis: str | None = None) -> bool:
        now = now_str()
        if new_analysis is None:
            cursor = self.conn.execute(
                "UPDATE questions SET answer = ?, updated_at = ? WHERE id = ?",
                (new_answer, now, int(record_id)),
            )
        else:
            cursor = self.conn.execute(
                "UPDATE questions SET answer = ?, analysis = ?, updated_at = ? WHERE id = ?",
                (new_answer, new_analysis, now, int(record_id)),
            )
        self.conn.commit()
        return cursor.rowcount > 0

    def debug_find_question_record(self, question_text: str, limit: int = 10) -> list[dict[str, Any]]:
        normalized = normalize_text(question_text)
        rows = self.conn.execute(
            """
            SELECT * FROM questions
            WHERE question_text_normalized = ?
               OR question_text LIKE ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (normalized, f"%{question_text.strip()}%", int(limit)),
        ).fetchall()

        results: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["options"] = [
                item.get("option_a", "") or "",
                item.get("option_b", "") or "",
                item.get("option_c", "") or "",
                item.get("option_d", "") or "",
                item.get("option_e", "") or "",
                item.get("option_f", "") or "",
            ]
            results.append(item)
        return results

    def debug_delete_question_record(self, question_text: str) -> tuple[int, list[dict[str, Any]]]:
        rows = self.debug_find_question_record(question_text, limit=50)
        if not rows:
            return 0, []

        ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        self.conn.execute(f"DELETE FROM questions WHERE id IN ({placeholders})", ids)
        self.conn.commit()
        return len(ids), rows

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def clear_all_questions(self) -> int:
        """清空所有题目，返回删除的记录数"""
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM questions")
            count = cursor.fetchone()[0]

            self.conn.execute("DELETE FROM questions")
            # 重置自增计数器，让ID从1开始
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name='questions'")
            self.conn.commit()
            self.log(f"已清空题库，共删除 {count} 道题目，ID已重置")
            return count
        except Exception as e:
            self.log(f"清空题库失败: {e}")
            return 0

    def get_all_questions(self) -> list[dict[str, Any]]:
        """获取所有题目"""
        try:
            rows = self.conn.execute(
                "SELECT * FROM questions ORDER BY id ASC"
            ).fetchall()

            results = []
            for row in rows:
                item = dict(row)
                item["options"] = [
                    item.get("option_a", "") or "",
                    item.get("option_b", "") or "",
                    item.get("option_c", "") or "",
                    item.get("option_d", "") or "",
                    item.get("option_e", "") or "",
                    item.get("option_f", "") or "",
                ]
                results.append(item)
            return results
        except Exception as e:
            self.log(f"获取所有题目失败: {e}")
            return []

    def log(self, message: str) -> None:
        """简单的日志输出（可被子类或外部覆盖）"""
        print(f"[DB] {message}")
