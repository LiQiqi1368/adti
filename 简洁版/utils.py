import re
import sqlite3
import unicodedata
from datetime import datetime
from pathlib import Path
from difflib import SequenceMatcher


LETTER_ORDER = "ABCDEF"
ANSWER_SEPARATOR = "|||"  # 答案字母与选项文字的分隔符


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", str(text)).strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。！？；：、,.!?;:\-—_（）()\[\]{}<>《》\"'“”‘’]", "", text)
    return text


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_unique_key(question_text: str, options: list[str]) -> str:
    normalized_options = [normalize_text(x) for x in (options or [])[:6]]
    normalized_options += [""] * (6 - len(normalized_options))
    return "|".join([normalize_text(question_text)] + normalized_options)


def normalize_answer(answer_text: str) -> str:
    raw = unicodedata.normalize("NFKC", str(answer_text or "")).strip()
    if not raw:
        return ""

    compact = re.sub(r"\s+", "", raw)
    if compact in ["对", "正确"]:
        return "正确"
    if compact in ["错", "错误"]:
        return "错误"

    letters = re.findall(r"[A-F]", compact.upper())
    if letters:
        unique_letters = []
        for ch in LETTER_ORDER:
            if ch in letters and ch not in unique_letters:
                unique_letters.append(ch)
        return "".join(unique_letters)

    return raw


def answer_to_display(answer: str) -> str:
    normalized = normalize_answer(answer)
    if not normalized:
        return ""
    if normalized in ["正确", "错误"]:
        return normalized
    if re.fullmatch(r"[A-F]+", normalized, flags=re.I):
        return ",".join(list(normalized.upper())) if len(normalized) > 1 else normalized.upper()
    return normalized


def answer_to_display_verbose(answer: str) -> str:
    """
    显示完整答案格式：如果有文字则显示"字母 (文字)"，否则只显示字母
    示例: "A|||正确" → "A (正确)"
          "AB|||对,错" → "A,B (对,错)"
          "正确" → "正确"
          "A" → "A"
    """
    letters, texts = parse_answer(answer)
    if not letters:
        return ""
    if letters in ["正确", "错误"]:
        return letters
    # 显示字母部分
    display = ",".join(list(letters.upper())) if len(letters) > 1 else letters.upper()
    # 如果有文字，附加上去
    if texts:
        texts_str = ",".join(texts)
        display = f"{display} ({texts_str})"
    return display


def format_answer(letters: str, option_texts: list[str]) -> str:
    """
    格式化答案为复合格式：字母|||文字1,文字2
    示例: "A|||正确"  或  "AB|||选项A文字,选项B文字"
    判断题直接返回"正确"/"错误"
    """
    normalized = normalize_answer(letters)
    if not normalized:
        return ""
    # 判断题：直接返回
    if normalized in ["正确", "错误"]:
        return normalized
    # 多选题/单选题：构造复合格式
    texts = ",".join(option_texts) if option_texts else ""
    if texts:
        return f"{normalized}{ANSWER_SEPARATOR}{texts}"
    return normalized


def parse_answer(answer: str) -> tuple[str, list[str]]:
    """
    解析复合答案格式，返回 (字母部分, 选项文字列表)
    示例:
        "A|||正确"  → ("A", ["正确"])
        "AB|||选项1,选项2"  → ("AB", ["选项1", "选项2"])
        "正确"  → ("正确", ["正确"])
        "A" (旧格式)  → ("A", [])
    """
    if not answer:
        return "", []
    if answer in ["正确", "错误"]:
        return answer, [answer]
    if ANSWER_SEPARATOR in answer:
        parts = answer.split(ANSWER_SEPARATOR, 1)
        letters = parts[0]
        texts = [t.strip() for t in parts[1].split(",") if t.strip()] if len(parts) > 1 else []
        return letters, texts
    # 兼容旧格式（纯字母，如 "A" 或 "AB"）
    if re.fullmatch(r"[A-F]+", answer, flags=re.I):
        return answer.upper(), []
    return answer, [answer]


def fuzzy_score(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
