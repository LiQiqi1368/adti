from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from config import WAIT_AFTER_NEXT_MS, LOGIN_USERNAME, LOGIN_PASSWORD
from utils import normalize_answer, format_answer, parse_answer


LETTER_ORDER = "ABCDEF"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class DomService:
    def __init__(self, log, target_url: str, username: str = "", password: str = ""):
        self.log = log
        self.target_url = (target_url or "").strip()
        self.username = (username or "").strip()
        self.password = (password or "").strip()
        self.thread_id = threading.get_ident()
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._page_stable_key = 0  # 用于页面稳定性检测

    def wait_for_page_stable(self, timeout: int = 8000):
        """
        等待页面稳定（老旧电脑专用，确保页面渲染完成后再操作）
        检测方式：网络空闲 + body 可见 + 连续两次 DOM 一致
        """
        page = self.ensure_page()
        try:
            page.wait_for_load_state("networkidle", timeout=timeout)
        except Exception:
            self.log("页面网络未完全空闲，继续等待...")
        try:
            page.locator("body").first.wait_for(state="visible", timeout=timeout)
        except Exception:
            self.log("页面 body 可见性检测超时")
        page.wait_for_timeout(1000)
        self.log("页面已稳定")

    def _assert_thread(self) -> None:
        if threading.get_ident() != self.thread_id:
            raise RuntimeError("Playwright 对象不能跨线程使用")

    def ensure_page(self):
        self._assert_thread()
        if self.page is not None:
            return self.page
        if not self.target_url:
            raise ValueError("请先配置目标网址")
        self.playwright = sync_playwright().start()
        # 打开浏览器并设置移动端视口
        self.log("正在启动浏览器...（老旧电脑可能较慢，请稍候）")
        # 检测打包后的浏览器路径（PyInstaller 打包后 _internal 目录）
        import sys
        browser_path = None
        
        # 方法1: 通过 _MEIPASS（PyInstaller 打包后的临时/运行目录）
        if hasattr(sys, '_MEIPASS'):
            candidate = Path(sys._MEIPASS) / "playwright_browsers" / "chromium-1208" / "chrome-win64" / "chrome.exe"
            if candidate.exists():
                browser_path = candidate
                self.log(f"通过 _MEIPASS 找到浏览器: {browser_path}")
        
        # 方法2: 通过 exe 所在目录的 _internal 子目录（COLLECT 模式）
        if browser_path is None:
            try:
                exe_dir = Path(sys.executable).parent
                candidate = exe_dir / "_internal" / "playwright_browsers" / "chromium-1208" / "chrome-win64" / "chrome.exe"
                if candidate.exists():
                    browser_path = candidate
                    self.log(f"通过 exe 目录找到浏览器: {browser_path}")
            except Exception:
                pass
        
        # 方法3: 通过当前工作目录的 _internal 子目录
        if browser_path is None:
            candidate = Path.cwd() / "_internal" / "playwright_browsers" / "chromium-1208" / "chrome-win64" / "chrome.exe"
            if candidate.exists():
                browser_path = candidate
                self.log(f"通过工作目录找到浏览器: {browser_path}")
        
        # 启动浏览器
        if browser_path:
            self.browser = self.playwright.chromium.launch(
                headless=False,
                executable_path=str(browser_path)
            )
        else:
            self.log("未找到打包的浏览器，尝试使用系统默认浏览器...")
            self.browser = self.playwright.chromium.launch(headless=False)

        # 尝试加载保存的登录状态，同时设置移动端视口
        storage_state_path = self._get_storage_state_path()
        if storage_state_path and storage_state_path.exists():
            try:
                self.context = self.browser.new_context(
                    storage_state=str(storage_state_path),
                    viewport={"width": 390, "height": 844}
                )
                self.log("已加载保存的登录状态（移动端视口）")
            except Exception as e:
                self.log(f"加载登录状态失败: {e}，将重新登录")
                self.context = self.browser.new_context(viewport={"width": 390, "height": 844})
        else:
            self.context = self.browser.new_context(viewport={"width": 390, "height": 844})

        self.page = self.context.new_page()
        self.page.goto(self.target_url, wait_until="networkidle", timeout=30000)
        self.log(f"已打开网页: {self.target_url}")

        # 尝试切换到移动端设备工具栏（Ctrl+Shift+M）
        self.page.wait_for_timeout(1500)
        try:
            self.page.keyboard.press("Control+Shift+M")
            self.log("已切换至移动端设备模式")
        except Exception:
            self.log("切换设备模式未生效（不影响正常使用）")
        
        # 等待页面完全加载
        self.page.wait_for_timeout(5000)

        # 尝试自动登录：优先用传入的账号密码，其次用 config 中的
        username = self.username or LOGIN_USERNAME
        password = self.password or LOGIN_PASSWORD
        if username and password:
            self._auto_login(username, password)
        else:
            self.log("请先在配置中填写账号密码，或手动登录")

        return self.page

    def _get_storage_state_path(self) -> Path | None:
        """获取登录状态保存路径"""
        try:
            from pathlib import Path
            data_dir = Path(__file__).resolve().parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir / "login_state.json"
        except Exception:
            return None

    def _auto_login(self, username: str, password: str) -> bool:
        """使用实际页面选择器自动登录"""
        try:
            page = self.page
            self.log("开始自动登录...")

            # 等待页面加载完成
            page.wait_for_timeout(5000)

            # 填写账号 - 用户提供的实际选择器
            try:
                username_field = page.locator('input[type="text"][placeholder="请输入账号"]').first
                username_field.wait_for(state="visible", timeout=5000)
                username_field.fill(username)
                self.log(f"已填写账号: {username[:3]}***")
            except Exception as e:
                self.log(f"未找到账号输入框: {e}")
                return False

            # 填写密码 - 用户提供的实际选择器
            try:
                password_field = page.locator('input[type="password"][placeholder="请输入密码"]').first
                password_field.wait_for(state="visible", timeout=3000)
                password_field.fill(password)
                self.log("已填写密码")
            except Exception as e:
                self.log(f"未找到密码输入框: {e}")
                return False

            # 点击登录按钮 - 用户提供的实际选择器
            try:
                login_btn = page.locator(".login-btn-box button").first
                login_btn.wait_for(state="visible", timeout=3000)
                login_btn.click()
                self.log("已点击登录按钮，等待跳转...")
                page.wait_for_timeout(5000)
                self._save_login_state()
                return True
            except Exception as e:
                self.log(f"未找到登录按钮: {e}")
                return False
        except Exception as e:
            self.log(f"自动登录异常: {e}")
            return False

    def _save_login_state(self):
        """保存登录状态"""
        try:
            storage_state_path = self._get_storage_state_path()
            if storage_state_path:
                self.context.storage_state(path=str(storage_state_path))
                self.log(f"登录状态已保存到: {storage_state_path}")
        except Exception as e:
            self.log(f"保存登录状态失败: {e}")

    def extract_question_data(self) -> dict[str, Any]:
        page = self.ensure_page()
        question_type = self._get_question_type(page)
        question_text = self._get_question_text(page)
        options = self._get_options(page)
        if not question_text:
            raise RuntimeError("未能提取到题目")
        return {
            "question_type": question_type,
            "question_text": question_text,
            "options": options,
        }

    def _first_visible_text(self, page, selectors: list[str]) -> str:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                count = min(loc.count(), 5)
                for i in range(count):
                    text = _clean_text(loc.nth(i).inner_text())
                    if text:
                        self.log(f"命中题目选择器: {selector}")
                        return text
            except Exception:
                continue
        return ""

    def _get_question_type(self, page) -> str:
        selector_groups = [
            [".topic_item_head .left span", ".exam-head span", ".question-type", ".type"],
            ["body"],
        ]
        for selectors in selector_groups:
            for selector in selectors:
                try:
                    loc = page.locator(selector)
                    count = min(loc.count(), 8)
                    for i in range(count):
                        text = _clean_text(loc.nth(i).inner_text())
                        if any(x in text for x in ["判断题", "单选题", "多选题"]):
                            return next(x for x in ["判断题", "单选题", "多选题"] if x in text)
                except Exception:
                    continue
        return ""

    def _get_question_text(self, page) -> str:
        selectors = [
            ".exam-sc-stem .stem-item",
            ".exam-sc-stem",
            ".stem-item",
            ".question-content",
            ".question-title",
            ".topic-content",
            ".topic-title",
        ]
        text = self._first_visible_text(page, selectors)
        if text:
            return text
        return _clean_text(page.locator("body").inner_text())[:300]

    def _get_options(self, page) -> list[str]:
        selector_groups = [
            ".exam-sc-quelists li",
            ".exam-sc-quelists .option",
            ".question-options li",
            ".options li",
            ".option-list li",
        ]
        for selector in selector_groups:
            values = []
            try:
                items = page.locator(selector)
                count = min(items.count(), 6)
                for i in range(count):
                    text = _clean_text(items.nth(i).inner_text())
                    if not text:
                        continue
                    # 不再强制添加字母前缀，保留原始文字
                    values.append(text)
            except Exception:
                values = []
            if values:
                self.log(f"命中选项选择器: {selector}")
                return values
        return []

    def get_option_text_by_answer(self, answer_letters: str, options: list[str]) -> list[str]:
        """
        根据答案字母（如 'A' 或 'BC'）返回对应的选项文字
        用于精准答题：找到选项文字后点击
        """
        result = []
        letter_map = {"A": 0, "B": 1, "C": 2, "D": 3, "E": 4, "F": 5}

        for letter in answer_letters.upper():
            if letter in letter_map:
                idx = letter_map[letter]
                if idx < len(options):
                    # 提取选项文字（去掉开头的字母标识、分隔符和多余空格）
                    text = re.sub(r"^[A-F]\s*[.、．:：]\s*", "", options[idx]).strip()
                    result.append(text)

        return result

    def click_option_by_text(self, option_text: str, options: list[str]) -> bool:
        """
        根据选项文字点击对应的选项
        支持复合格式答案：字母|||文字1,文字2（优先按文字点击）
        支持精确匹配和模糊匹配
        """
        from utils import parse_answer

        self.log(f"click_option_by_text: 输入='{option_text}', 选项数={len(options)}")

        # 解析复合格式：先判断是不是"字母|||文字"格式
        answer_letters, answer_texts = parse_answer(option_text)
        self.log(f"解析结果: 字母='{answer_letters}', 文字={answer_texts}")
        
        # 如果有选项文字，优先按文字点击（多选题就点多个文字）
        if answer_texts:
            self.log(f"按选项文字点击: {answer_texts} (字母: {answer_letters})")
            success = True
            for i, text in enumerate(answer_texts):
                if not self._click_single_option_text(text, options):
                    # 文字匹配失败，尝试用字母索引（单选题用第一个字母，多选题用对应位置的字母）
                    if answer_letters:
                        if len(answer_letters) == 1:
                            # 单选题，用唯一的字母
                            letter_idx = "ABCDEF".index(answer_letters[0])
                        elif i < len(answer_letters):
                            # 多选题，用对应位置的字母
                            letter_idx = "ABCDEF".index(answer_letters[i])
                        else:
                            continue
                        self.log(f"文字匹配失败，降级到字母索引: {letter_idx} (字母: {answer_letters})")
                        if not self._click_option_by_index(letter_idx):
                            success = False
                    else:
                        success = False
            return success
        
        # 没有文字（旧格式纯字母），用原有逻辑
        if answer_letters and re.fullmatch(r"[A-F]+", answer_letters, flags=re.I):
            self.log(f"旧格式答案，按字母索引点击: {answer_letters}")
            success = True
            for ch in answer_letters.upper():
                idx = "ABCDEF".index(ch)
                if not self._click_option_by_index(idx):
                    success = False
            return success
        
        # 原有的单文字匹配逻辑（兼容）
        return self._click_single_option_text(option_text, options)

    def _click_single_option_text(self, option_text: str, options: list[str]) -> bool:
        """按单个文字匹配并点击选项"""
        page = self.ensure_page()
        answer_clean = option_text.strip()

        # 去掉答案文字中的字母前缀、分隔符和多余空格（如 "B . 新型能源体系" -> "新型能源体系"）
        answer_clean = re.sub(r"^[A-F]\s*[.、．:：]\s*", "", answer_clean).strip()

        self.log(f"尝试匹配选项文字: '{answer_clean}' (原始: '{option_text}')")
        self.log(f"可用选项: {options}")

        # 精确匹配：去掉选项的字母前缀、分隔符和多余空格后比较
        for i, opt in enumerate(options):
            clean_opt = re.sub(r"^[A-F]\s*[.、．:：]\s*", "", opt).strip()
            if clean_opt == answer_clean:
                self.log(f"精确匹配成功: '{answer_clean}' -> 选项{i} '{opt}'")
                return self._click_option_by_index(i)

        # 反向精确匹配
        for i, opt in enumerate(options):
            clean_opt = re.sub(r"^[A-F]\s*[.、．:：]\s*", "", opt).strip()
            if answer_clean and (answer_clean in clean_opt or clean_opt in answer_clean):
                self.log(f"包含匹配选项: '{answer_clean}' -> 选项{i} '{opt}'")
                return self._click_option_by_index(i)

        # 模糊匹配（相似度>0.75）
        from difflib import SequenceMatcher
        best_idx = -1
        best_ratio = 0.0
        for i, opt in enumerate(options):
            clean_opt = re.sub(r"^[A-F]\s*[.、．:：]\s*", "", opt).strip()
            ratio = SequenceMatcher(None, clean_opt, answer_clean).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_idx = i

        if best_ratio > 0.75 and best_idx >= 0:
            self.log(f"模糊匹配选项: '{answer_clean}' -> '{options[best_idx]}' (相似度: {best_ratio:.2f})")
            return self._click_option_by_index(best_idx)

        self.log(f"✗ 未找到匹配的选项: '{answer_clean}'，可用选项: {[re.sub(r'^[A-F]\s*[.、．:：]\s*', '', opt).strip() for opt in options]}")
        return False

    def _click_option_by_index(self, index: int) -> bool:
        """根据索引点击选项"""
        page = self.ensure_page()
        selector_groups = [
            ".exam-sc-quelists li",
            ".exam-sc-quelists .option",
            ".question-options li",
            ".options li",
            ".option-list li",
        ]

        for selector in selector_groups:
            try:
                items = page.locator(selector)
                if index < items.count():
                    item = items.nth(index)
                    if item.is_visible():
                        item.click()
                        page.wait_for_timeout(300)
                        self.log(f"已点击选项 {index}")
                        return True
            except Exception:
                continue

        return False

    def click_answer_by_text(self, answer_letters: str, options: list[str]) -> bool:
        """
        根据答案字母找到对应选项文字，然后点击
        这是精准答题的核心方法
        """
        option_texts = self.get_option_text_by_answer(answer_letters, options)
        if not option_texts:
            self.log(f"无法找到答案对应的选项文字: {answer_letters}")
            return False

        success = True
        for text in option_texts:
            if not self.click_option_by_text(text, options):
                success = False

        return success

    def expand_answer_explanation(self) -> bool:
        page = self.ensure_page()
        if self._is_explanation_visible(page):
            self.log("解析区已展开")
            return True
        title_selectors = [
            ".ques-answer-title",
            "text=答案解析",
            "text=查看解析",
            "text=参考解析",
            ".answer-analysis-title",
        ]
        for selector in title_selectors:
            try:
                title = page.locator(selector).first
                for mode in [0, 1, 2]:
                    try:
                        title.wait_for(state="visible", timeout=1000)
                        try:
                            title.scroll_into_view_if_needed(timeout=500)
                        except Exception:
                            pass
                        if mode == 0:
                            title.click(timeout=900)
                        elif mode == 1:
                            title.click(force=True, timeout=900)
                        else:
                            handle = title.element_handle()
                            if handle is not None:
                                page.evaluate("(el)=>el.click()", handle)
                        page.wait_for_timeout(200)
                        if self._is_explanation_visible(page):
                            self.log(f"答案解析展开成功: {selector}")
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
        self.log("答案解析展开失败")
        return False

    def _is_explanation_visible(self, page) -> bool:
        visible_selectors = [
            ".ques-answer ul",
            ".ques-answer .ques-answer-p",
            ".answer-analysis",
            ".analysis-content",
        ]
        for selector in visible_selectors:
            try:
                loc = page.locator(selector)
                if loc.count() > 0 and loc.first.is_visible():
                    return True
            except Exception:
                continue
        try:
            loc = page.locator("body")
            text = _clean_text(loc.inner_text())
            return any(x in text for x in ["正确答案", "参考答案", "参考解析"])
        except Exception:
            return False

    def extract_correct_answer_from_explanation(self, question_type: str, options: list[str],
                                                  parent_locator=None,
                                                  skip_option_text: bool = False) -> tuple[str, str]:
        """
        从答案解析区域提取正确答案

        Args:
            question_type: 题目类型
            options: 选项列表
            parent_locator: 父级元素定位器
            skip_option_text: 是否跳过获取选项文字（在考试回顾页面使用，因为选项可能不准确）
        """
        page = self.ensure_page()
        texts = []
        selectors = [
            ".ques-answer .ques-answer-p",
            ".answer-analysis p",
            ".analysis-content p",
            ".analysis-content",
            ".ques-answer",
        ]

        # 如果传入了父级元素，在父级范围内查找（避免混入其他错题的内容）
        base = parent_locator if parent_locator is not None else page
        for selector in selectors:
            try:
                loc = base.locator(selector) if parent_locator is not None else page.locator(selector)
                count = min(loc.count(), 12)
                current = []
                for i in range(count):
                    text = _clean_text(loc.nth(i).inner_text())
                    if text:
                        current.append(text)
                if current:
                    texts = current
                    self.log(f"命中解析选择器: {selector}")
                    break
            except Exception:
                continue

        joined = "\n".join(texts)
        answer_letters = self._parse_answer_text(joined, question_type)
        analysis = ""
        for text in texts:
            if "参考解析" in text:
                analysis = re.split(r"[：:]", text, maxsplit=1)[-1].strip()
                break

        # 获取选项文字并构造复合格式答案
        option_texts = []
        if not skip_option_text and answer_letters and options:
            option_texts = self.get_option_text_by_answer(answer_letters, options)
            if option_texts:
                self.log(f"答案选项文字: {option_texts}")

        # 构造复合格式：字母|||文字1,文字2
        compound_answer = format_answer(answer_letters, option_texts)
        if compound_answer and compound_answer != answer_letters:
            self.log(f"复合答案格式: {compound_answer}")

        return compound_answer, analysis

    def has_unanswered_question(self) -> bool:
        """
        检测页面上是否还有未答的题目
        在点击"我要交卷"前调用，防止漏题
        """
        page = self.ensure_page()
        try:
            # 方式1: 检测"下一题"按钮依然存在 → 说明还有题没答
            next_selectors = [
                ".bot .next_btn",
                "text=下一题",
                "li.next_btn",
                "button:has-text('下一题')",
            ]
            for sel in next_selectors:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=500):
                    self.log("检测到'下一题'按钮，还有题目未答")
                    return True

            # 方式2: 检测常见"未答"提示
            unans_texts = page.locator("text=未答").first
            if unans_texts.is_visible(timeout=500):
                self.log("检测到'未答'提示，还有题目未答")
                return True

            return False
        except Exception:
            return False

    def click_answer_card_tab(self) -> bool:
        """点击底部导航栏的'答题卡'按钮"""
        page = self.ensure_page()
        selectors = [
            'li:has(p:text("答题卡"))',
            'text=答题卡',
            'li:has-text("答题卡")',
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    self.log("已点击'答题卡'")
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        self.log("未找到'答题卡'按钮")
        return False

    def get_unanswered_numbers_from_card(self) -> list[int]:
        """
        从答题卡中获取所有未做题目的编号
        返回: 未做题号列表 [1, 3, 5, ...]
        """
        page = self.ensure_page()
        unanswered = []
        try:
            # 答题卡中未答的题: <li class=""><p class="num">1</p>...
            # 已答的题: <li class="active"><p class="num">2</p>...
            items = page.locator('.details li')
            count = items.count()
            for i in range(count):
                item = items.nth(i)
                cls = item.get_attribute("class") or ""
                if "active" not in cls:
                    num_text = item.locator(".num").inner_text()
                    if num_text.strip().isdigit():
                        unanswered.append(int(num_text.strip()))
            self.log(f"答题卡中未答题: {unanswered}")
        except Exception as e:
            self.log(f"获取答题卡未答题失败: {e}")
        return unanswered

    def goto_question_by_number(self, num: int) -> bool:
        """点击答题卡中指定题号，跳转到该题"""
        page = self.ensure_page()
        try:
            # 答题卡页面找到对应题号并点击
            items = page.locator('.details li')
            count = items.count()
            for i in range(count):
                num_text = items.nth(i).locator(".num").inner_text().strip()
                if num_text == str(num):
                    items.nth(i).click()
                    self.log(f"已跳转到第 {num} 题")
                    page.wait_for_timeout(2000)
                    return True
        except Exception as e:
            self.log(f"跳转到第 {num} 题失败: {e}")
        return False

    def close_answer_card(self) -> bool:
        """关闭答题卡（点击外部或关闭按钮）"""
        page = self.ensure_page()
        try:
            # 点击答题卡遮罩层
            overlay = page.locator('.van-overlay').first
            if overlay.is_visible(timeout=500):
                overlay.click()
                self.log("已关闭答题卡")
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        try:
            # 尝试点击答题卡头部关闭按钮
            close_btn = page.locator('.center .head h4').first
            if close_btn.is_visible(timeout=500):
                page.locator('.van-overlay').first.click(timeout=500)
                self.log("已关闭答题卡(2)")
                page.wait_for_timeout(1000)
                return True
        except Exception:
            pass
        return False

    def click_submit_from_card(self) -> bool:
        """在答题卡底部点击'我要交卷'"""
        page = self.ensure_page()
        selectors = [
            '.bot li:text("我要交卷")',
            '.bot li:text("交卷")',
            'li:p(text="我要交卷")',
            'li:text("交卷")',
        ]
        for sel in selectors:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=3000):
                    btn_text = btn.inner_text().strip()
                    btn.click()
                    self.log(f"已点击答题卡底部'{btn_text}'")
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                continue
        self.log("未找到答题卡底部'交卷'按钮")
        return False

    def click_next_question(self) -> str:
        """
        点击'下一题'或'我要交卷'
        返回: "next"=点击了下一题, "submit"=点击了我要交卷, ""=失败
        """
        page = self.ensure_page()

        # 重试机制：等待按钮出现（循环轮次后可能加载较慢）
        max_retry = 3
        for attempt in range(max_retry):
            # 先尝试'下一题'
            next_selectors = [
                ".bot .next_btn",
                "text=下一题",
                "li.next_btn",
                "button:has-text('下一题')",
                "a:has-text('下一题')",
            ]
            for selector in next_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.scroll_into_view_if_needed(timeout=500)
                        btn.click(timeout=900)
                        page.wait_for_timeout(max(int(WAIT_AFTER_NEXT_MS), 200))
                        self.log(f"已点击'下一题': {selector}")
                        return "next"
                except Exception:
                    continue

            # 再尝试'我要交卷'
            submit_selectors = [
                "text=我要交卷",
                "span:has-text('我要交卷')",
                ".next:has-text('我要交卷')",
                "text=交卷",
                "button:has-text('我要交卷')",
            ]
            for selector in submit_selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.scroll_into_view_if_needed(timeout=500)
                        btn.click(timeout=900)
                        page.wait_for_timeout(2000)
                        self.log("已点击'我要交卷'")
                        return "submit"
                except Exception:
                    continue

            # 没找到，等一会儿再试
            if attempt < max_retry - 1:
                self.log(f"未找到按钮，等待重试 ({attempt+1}/{max_retry})...")
                page.wait_for_timeout(2000)

        self.log("未找到'下一题'或'我要交卷'按钮")
        return ""

    def _parse_answer_text(self, text: str, question_type: str = "") -> str:
        raw = _clean_text(text)
        if not raw:
            return ""

        # 判断题特殊处理：直接查找"正确"或"错误"关键字
        if "判断" in (question_type or ""):
            # 优先匹配"正确答案：正确/错误"格式
            judge_patterns = [
                r"正确答案\s*[：:]\s*(正确|错误)",
                r"参考答案\s*[：:]\s*(正确|错误)",
                r"答案\s*[：:]\s*(正确|错误)",
            ]
            for pattern in judge_patterns:
                match = re.search(pattern, raw, flags=re.I)
                if match:
                    answer = match.group(1)
                    self.log(f"判断题答案匹配: {answer!r}")
                    return answer

            # 如果没有匹配到标准格式，查找文本开头的"正确"或"错误"
            # 通常判断题的答案在文本最前面
            first_part = raw.split()[0] if raw else ""
            if first_part in ["正确", "错误"]:
                self.log(f"判断题答案(开头): {first_part!r}")
                return first_part

            # 尝试匹配"对"或"错"（旧格式）
            if "对" in first_part and "错" not in first_part:
                self.log("判断题答案: 正确 (从'对'转换)")
                return "正确"
            if "错" in first_part:
                self.log("判断题答案: 错误 (从'错'转换)")
                return "错误"

        # 选择题处理
        # 调试：打印完整解析文本（用于排查问题）
        if raw:
            self.log(f"解析文本前200字: {raw[:200]!r}")

        patterns = [
            # 第一优先级：正确答案（最可靠）
            (r"正确答案\s*[：:]\s*([A-F][A-F,、]*)", "正确答案"),
            (r"正确答案\s*[：:]\s*([^\n；;。]+)", "正确答案(宽泛)"),
            # 第二优先级：参考答案
            (r"参考答案\s*[：:]\s*([A-F][A-F,、]*)", "参考答案"),
            (r"参考答案\s*[：:]\s*([^\n；;。]+)", "参考答案(宽泛)"),
            # 第三优先级：我的答案（可能错，最后考虑）
            (r"我的答案\s*[：:]\s*([A-F][A-F,、]*)", "我的答案"),
            (r"我的答案\s*[：:]\s*([^\n；;。]+)", "我的答案(宽泛)"),
            # 最低优先级：只有"答案"
            (r"答案\s*[：:]\s*([A-F][A-F,、]*)", "答案"),
            (r"答案\s*[：:]\s*([^\n；;。]+)", "答案(宽泛)"),
        ]
        for pattern, pattern_name in patterns:
            match = re.search(pattern, raw, flags=re.I)
            if match:
                raw_answer = _clean_text(match.group(1))
                normalized = normalize_answer(raw_answer)
                self.log(f"匹配模式: {pattern_name}, 原始片段: {raw_answer!r}")
                self.log(f"标准化后的答案: {normalized!r}")
                return normalized

        normalized = normalize_answer(raw)
        if normalized:
            self.log(f"原始解析片段: {raw!r}")
            self.log(f"标准化后的答案: {normalized!r}")
        return normalized

    def click_enter_button(self) -> bool:
        """
        点击'自主练测'卡片的'进入'按钮（登录后的首页）
        HTML结构:
        <li class="card type_3">
          <div class="detail"><div><p>自主练测</p></div></div>
          <div class="btn">进入</div>
        </li>
        """
        page = self.ensure_page()
        # 精准定位"自主练测"卡片内的"进入"按钮
        selectors = [
            'li:has(p:text("自主练测")) div.btn:text("进入")',
            'li:has(div:has(p:text("自主练测"))) .btn',
            '.card:has(p:text("自主练测")) .btn',
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=5000):
                    btn.click()
                    self.log("已点击'自主练测'的'进入'按钮")
                    # 等待题库页面加载完成（等待 .van-tab 出现）
                    try:
                        page.locator('.van-tab').first.wait_for(state="visible", timeout=10000)
                        self.log("题库页面已加载")
                    except Exception:
                        self.log("等待题库页面超时，继续执行")
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                continue
        self.log("未找到'自主练测'的'进入'按钮")
        return False

    def select_question_bank(self, index: int = 0) -> bool:
        """
        选择题库tab（1-5）
        tab列表:
        1: 1钻（修）井/基本素养和形势任务Ⅱ
        2: 1钻（修）井/专业知识
        3: 1钻（修）井/HSE通用知识Ⅱ
        4: 1钻（修）井/HSE法律法规Ⅱ
        5: 0石油工程基础/基本素养和形势任务Ⅱ
        HTML:
        <div class="van-tabs__wrap van-tabs__wrap--scrollable">
          <div role="tablist" class="van-tabs__nav ...">
            <div role="tab" class="van-tab"><span class="van-tab__text">1钻（修）井/基本素养和形势任务Ⅱ</span></div>
            ...
          </div>
        </div>
        """
        page = self.ensure_page()
        tab_names = {
            1: "1钻（修）井/基本素养和形势任务Ⅱ",
            2: "1钻（修）井/专业知识",
            3: "1钻（修）井/HSE通用知识Ⅱ",
            4: "1钻（修）井/HSE法律法规Ⅱ",
            5: "0石油工程基础/基本素养和形势任务Ⅱ",
        }

        if index not in tab_names:
            self.log(f"题库索引无效: {index}，应在1-5之间")
            return False

        target_name = tab_names[index]
        self.log(f"准备选择题库: {target_name}")

        try:
            # 等待tab容器加载
            page.locator('.van-tabs__wrap').first.wait_for(state="visible", timeout=8000)
            page.wait_for_timeout(1000)

            # 方式1: 通过文字精准匹配tab（最可靠）
            tab = page.locator(f'.van-tab:has(.van-tab__text:text-is("{target_name}"))')
            if tab.count() > 0 and tab.first.is_visible(timeout=3000):
                tab.first.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(300)
                tab.first.click(force=True)
                self.log(f"已选择题库: {target_name} (方式1)")
                page.wait_for_timeout(2000)
                return True

            # 方式2: 模糊文字匹配
            tab = page.locator(f'.van-tab:text("{target_name}")')
            if tab.count() > 0 and tab.first.is_visible(timeout=3000):
                tab.first.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(300)
                tab.first.click(force=True)
                self.log(f"已选择题库: {target_name} (方式2)")
                page.wait_for_timeout(2000)
                return True

            # 方式3: 通过索引定位（兜底）
            self.log(f"文字匹配失败，尝试索引定位 index={index}")
            tabs = page.locator('.van-tabs__wrap .van-tab')
            if tabs.count() >= index:
                tab = tabs.nth(index - 1)
                tab.wait_for(state="visible", timeout=5000)
                tab.scroll_into_view_if_needed(timeout=2000)
                page.wait_for_timeout(300)
                tab.click(force=True)
                self.log(f"已选择题库 tab {index} (方式3)")
                page.wait_for_timeout(2000)
                return True

            self.log(f"所有方式均无法选择题库: {target_name}")
            return False

        except Exception as e:
            self.log(f"选择题库失败: {e}")
            return False

    def click_continue_exam(self) -> bool:
        """
        点击'继续考试'或'重新考试'按钮
        HTML: <div data-v-e479f478="" class="btn">继续考试</div>
              或 第二轮的 <div ... class="btn">重新考试</div>
        """
        page = self.ensure_page()
        # 先等待页面加载
        page.wait_for_timeout(2000)
        
        selectors = [
            'div.btn:has-text("继续考试")',
            'div.btn:has-text("重新考试")',
            'div.btn:has-text("开始模拟")',
            'text=继续考试',
            'text=重新考试',
            'text=开始模拟',
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=8000):
                    btn_text = btn.inner_text().strip()
                    btn.click()
                    self.log(f"已点击'{btn_text}'")
                    page.wait_for_timeout(2000)
                    
                    # 立即检查是否显示"暂无试卷"（常见于点击"开始模拟"后）
                    for _ in range(3):  # 重试几次
                        try:
                            no_paper = page.locator("text=暂无试卷").first
                            if no_paper.is_visible(timeout=1000):
                                self.log("检测到'暂无试卷'，切换题库刷新...")
                                tabs = page.locator('.van-tabs__wrap .van-tab')
                                if tabs.count() >= 2:
                                    tabs.nth(1).click()
                                    page.wait_for_timeout(2000)
                                    tabs.nth(0).click()
                                    page.wait_for_timeout(3000)
                                    # 重新点击考试按钮
                                    for sel2 in selectors:
                                        try:
                                            b2 = page.locator(sel2).first
                                            if b2.is_visible(timeout=5000):
                                                b2.click()
                                                self.log(f"刷新后已点击'{b2.inner_text().strip()}'")
                                                page.wait_for_timeout(2000)
                                                break
                                        except Exception:
                                            continue
                                break
                        except Exception:
                            pass
                        page.wait_for_timeout(1000)
                    
                    # 等待考试准备页加载（等待"开始考试"或"重新考试"按钮出现）
                    try:
                        page.locator('div.btn:has-text("开始考试"), div.btn:has-text("重新考试")').first.wait_for(state="visible", timeout=8000)
                        self.log("考试准备页已加载")
                    except Exception:
                        self.log("等待考试准备页超时，继续执行")
                    page.wait_for_timeout(2000)
                    return True
            except Exception:
                continue
        
        # 如果找不到按钮，尝试切换题库再切回（刷新按钮状态）
        self.log("未找到考试按钮，尝试切换题库刷新...")
        try:
            tabs = page.locator('.van-tabs__wrap .van-tab')
            tab_count = tabs.count()
            if tab_count >= 2:
                # 切换到第2个题库
                tabs.nth(1).click()
                page.wait_for_timeout(2000)
                # 切回第1个题库
                tabs.nth(0).click()
                page.wait_for_timeout(3000)
                # 重新查找按钮
                for selector in selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=5000):
                            btn_text = btn.inner_text().strip()
                            btn.click()
                            self.log(f"切换题库后已点击'{btn_text}'")
                            page.wait_for_timeout(2000)
                            # 同样检查"暂无试卷"
                            for _ in range(3):
                                try:
                                    np = page.locator("text=暂无试卷").first
                                    if np.is_visible(timeout=1000):
                                        self.log("切换题库后仍检测到'暂无试卷'，再切一次...")
                                        tabs.nth(1).click()
                                        page.wait_for_timeout(2000)
                                        tabs.nth(0).click()
                                        page.wait_for_timeout(3000)
                                        for s3 in selectors:
                                            try:
                                                b3 = page.locator(s3).first
                                                if b3.is_visible(timeout=5000):
                                                    b3.click()
                                                    self.log(f"二次刷新后已点击'{b3.inner_text().strip()}'")
                                                    break
                                            except Exception:
                                                continue
                                        break
                                except Exception:
                                    pass
                                page.wait_for_timeout(1000)
                            page.wait_for_timeout(3000)
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        
        self.log("未找到'继续考试'或'重新考试'按钮（可能无需操作，直接开始）")
        return False

    def click_start_exam(self) -> bool:
        """
        点击考试按钮（支持多次点击：进入综合模拟测试 → 继续考试 → 开始考试）
        第一次: '继续考试' / '开始考试' / '重新考试'
        第二次: 在'综合模拟测试'页面点击'开始考试'开始答题
        """
        page = self.ensure_page()
        
        # ===== 第一次点击：进入综合模拟测试页面 =====
        # 综合模拟测试页面也可能显示"继续考试"，需要点击后再按"开始考试"
        selectors_1st = [
            'div.bot div.btn:has-text("继续考试")',
            'div.bot div.btn:has-text("开始考试")',
            'div.bot div.btn:has-text("开始模拟")',
            'div.bot div.btn:has-text("重新考试")',
            'div.btn:has-text("继续考试")',
            'div.btn:has-text("开始考试")',
            'div.btn:has-text("开始模拟")',
            'div.btn:has-text("重新考试")',
            'text=继续考试',
            'text=开始考试',
            'text=开始模拟',
            'text=重新考试',
        ]
        
        clicked_1st = False
        for selector in selectors_1st:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=5000):
                    btn_text = btn.inner_text()
                    btn.click()
                    self.log(f"已点击'{btn_text}'按钮")
                    clicked_1st = True
                    break
            except Exception:
                continue
        
        if not clicked_1st:
            # 切换题库再切回，刷新按钮状态
            self.log("未找到考试按钮，尝试切换题库刷新...")
            try:
                tabs = page.locator('.van-tabs__wrap .van-tab')
                if tabs.count() >= 2:
                    tabs.nth(1).click()
                    page.wait_for_timeout(2000)
                    tabs.nth(0).click()
                    page.wait_for_timeout(3000)
                    for selector in selectors_1st:
                        try:
                            btn = page.locator(selector).first
                            if btn.is_visible(timeout=5000):
                                btn_text = btn.inner_text()
                                btn.click()
                                self.log(f"切换题库后已点击'{btn_text}'")
                                clicked_1st = True
                                break
                        except Exception:
                            continue
            except Exception:
                pass
        
        if not clicked_1st:
            self.log("未找到'开始考试'或'重新考试'按钮（可能已在答题中）")
            return False
        
        # 等待综合模拟测试页面加载
        page.wait_for_timeout(3000)
        
        # ===== 第二次点击：在综合模拟测试页面点击'开始考试' =====
        self.log("等待综合模拟测试页面加载...")
        page.wait_for_timeout(2000)
        
        selectors_2nd = [
            'div.btn:has-text("开始考试")',
            'text=开始考试',
        ]
        
        for selector in selectors_2nd:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=8000):
                    btn.click()
                    self.log("已点击'综合模拟测试'页面的'开始考试'按钮")
                    break
            except Exception:
                continue
        
        # 等待题目页面加载
        self.log("等待题目页面加载...")
        max_wait = 15
        for _ in range(max_wait):
            if self.is_exam_page():
                self.log("题目页面已加载")
                page.wait_for_timeout(2000)
                return True
            page.wait_for_timeout(1000)
        
        self.log("等待题目页面超时，继续执行")
        page.wait_for_timeout(2000)
        return True

    def click_exam_review(self) -> bool:
        """
        点击'回顾本次答题过程'按钮（答题完成后，分数≤98.5时触发）
        HTML: <li data-v-7c3feb8c="" class="review"> 回顾本次答题过程 </li>
        """
        page = self.ensure_page()
        selectors = [
            'li.review:text("回顾本次答题过程")',
            'li:has-text("回顾本次答题过程")',
            'text=回顾本次答题过程',
            'li.review',
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=5000):
                    btn.click()
                    self.log("已点击'回顾本次答题过程'按钮")
                    page.wait_for_timeout(3000)
                    return True
            except Exception:
                continue
        self.log("未找到'回顾本次答题过程'按钮")
        return False

    def click_retry_button(self) -> bool:
        """
        点击'再考一次'按钮（优先找结果页的"再考一次"，找不到则尝试"重新考试"）
        HTML: <li data-v-7c3feb8c="" class="active">再考一次</li>
        """
        page = self.ensure_page()
        # 优先找结果页的"再考一次"
        selectors = [
            '.exam_result .bot li.active:has-text("再考一次")',
            'li.active:has-text("再考一次")',
            'text=再考一次',
        ]
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    self.log("已点击'再考一次'按钮")
                    page.wait_for_timeout(3000)
                    return True
            except Exception:
                continue
        
        # 找不到"再考一次"，说明可能在自主练测页面，尝试重入考试按钮
        self.log("未找到'再考一次'，尝试重新进入考试...")
        fallback_selectors = [
            'div.btn:has-text("重新考试")',
            'div.btn:has-text("开始考试")',
            'div.btn:has-text("开始模拟")',
            'div.btn:has-text("继续考试")',
            'text=重新考试',
            'text=开始考试',
            'text=开始模拟',
            'text=继续考试',
        ]
        for selector in fallback_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=3000):
                    btn.click()
                    self.log(f"已点击'{btn.inner_text().strip()}'按钮")
                    page.wait_for_timeout(3000)
                    return True
            except Exception:
                continue
        
        # 切换题库再切回，刷新按钮状态
        self.log("尝试切换题库刷新按钮状态...")
        try:
            tabs = page.locator('.van-tabs__wrap .van-tab')
            if tabs.count() >= 2:
                tabs.nth(1).click()
                page.wait_for_timeout(2000)
                tabs.nth(0).click()
                page.wait_for_timeout(3000)
                for selector in fallback_selectors:
                    try:
                        btn = page.locator(selector).first
                        if btn.is_visible(timeout=3000):
                            btn.click()
                            self.log(f"切换题库后已点击'{btn.inner_text().strip()}'")
                            page.wait_for_timeout(3000)
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        
        self.log("未找到'再考一次'或'重新考试'按钮")
        return False

    def is_result_page(self) -> bool:
        """判断当前是否在考试结果页面"""
        page = self.ensure_page()
        try:
            # 结果页特征1: .exam_result 存在
            exam_result = page.locator('.exam_result')
            if exam_result.count() > 0 and exam_result.first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        try:
            # 结果页特征2: .score 存在（分数区域）
            score_div = page.locator('.score')
            if score_div.count() > 0 and score_div.first.is_visible(timeout=1000):
                return True
        except Exception:
            pass
        try:
            # 结果页特征3: 文本包含"当前得分"和"再考一次"/"回顾本次答题过程"
            text = _clean_text(page.locator("body").inner_text())
            if "当前得分" in text and ("再考一次" in text or "退出考试" in text or "回顾本次答题过程" in text):
                return True
        except Exception:
            pass
        return False

    def is_exam_page(self) -> bool:
        """判断当前是否在答题页面"""
        page = self.ensure_page()
        try:
            # 答题页特征: 有题目标题和选项列表
            # 扩展选择器列表，增加更多可能的匹配项
            for selector in [
                ".exam-sc-stem", 
                ".topic_item_head", 
                ".question-content",
                ".question-text",
                ".stem",
                ".question",
                "text=下一题",  # 如果有"下一题"按钮，说明在答题页
                "text=我要交卷",  # 如果有"我要交卷"按钮，说明在答题页
                ".van-radio",  # 单选题选项
                ".van-checkbox",  # 多选题选项
            ]:
                try:
                    loc = page.locator(selector)
                    if loc.count() > 0 and loc.first.is_visible(timeout=1000):
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        
        # 备用方案：检查页面文本是否包含题目特征
        try:
            body_text = page.locator("body").inner_text()
            # 如果页面包含常见答题页面文字，也认为在答题页
            keywords = ["下一题", "我要交卷", "单选题", "多选题", "判断题"]
            if any(keyword in body_text for keyword in keywords):
                return True
        except Exception:
            pass
        
        return False

    def click_submit(self) -> bool:
        """点击提交按钮"""
        page = self.ensure_page()
        submit_selectors = [
            "text=提交",
            "text=确定",
            ".submit-btn",
            ".btn-submit",
            "button[type='submit']",
            ".confirm-btn",
        ]

        for selector in submit_selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    btn.click()
                    page.wait_for_timeout(1000)
                    self.log("已点击提交按钮")
                    return True
            except Exception:
                continue

        self.log("未找到提交按钮")
        return False

    def click_submit_exam(self) -> bool:
        """
        点击'交卷'按钮（答题完毕后的确认对话框）
        返回值: True=已交卷, False=取消(用户继续答题)
                "unanswered"=检测到未答题，已点击继续作答
        """
        page = self.ensure_page()

        # 检查弹窗内容
        try:
            dialog = page.locator('.van-dialog__content')
            if dialog.is_visible(timeout=1000):
                dialog_text = dialog.inner_text()
                # 检测"您还有XX道题目未作答，是否交卷？"
                if "未作答" in dialog_text or "未做" in dialog_text or "未答" in dialog_text:
                    self.log(f"弹窗提示有未做题: {dialog_text.strip()[:60]}")
                    # 点击"继续作答"
                    continue_sel = [
                        'div.van-dialog__content div.btn div.left:has-text("继续作答")',
                        'div.van-dialog__content div.left:text("继续作答")',
                        'text=继续作答',
                        'div.van-dialog__content div.btn div.left',
                    ]
                    for sel in continue_sel:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                self.log("已点击'继续作答'")
                                page.wait_for_timeout(1000)
                                return "unanswered"
                        except Exception:
                            continue
                    # 找不到继续作答，尝试取消
                    cancel_sel = [
                        'div.van-dialog__content div.btn div.left:has-text("取消")',
                        'text=取消',
                    ]
                    for sel in cancel_sel:
                        try:
                            btn = page.locator(sel).first
                            if btn.is_visible(timeout=1000):
                                btn.click()
                                self.log("已点击'取消'")
                                page.wait_for_timeout(1000)
                                return False
                        except Exception:
                            continue
        except Exception:
            pass

        # 重试机制：多次尝试点击交卷按钮
        max_retries = 3
        for attempt in range(max_retries):
            selectors = [
                'div.van-dialog__content div.btn div.right:has-text("交卷")',
                'div.van-dialog__content span:text("交卷")',
                'text=交卷',
                'button:has-text("交卷")',
                '.van-dialog__footer button:last-child',
            ]
            for selector in selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.is_visible(timeout=3000):
                        btn.scroll_into_view_if_needed(timeout=500)
                        btn.click(timeout=1000)
                        self.log(f"已点击'交卷'按钮 (尝试 {attempt+1}/{max_retries})")
                        page.wait_for_timeout(2000)
                        # 检查是否还在弹窗页面，如果不在了说明成功
                        try:
                            dialog = page.locator('.van-dialog__content')
                            if not dialog.is_visible(timeout=1000):
                                self.log("交卷弹窗已关闭，确认交卷成功")
                                return True
                        except:
                            return True
                except Exception:
                    continue

            # 如果没成功，等待一下再试
            if attempt < max_retries - 1:
                self.log(f"交卷按钮点击未成功，等待重试 ({attempt+1}/{max_retries})...")
                page.wait_for_timeout(1500)

        self.log("未找到'交卷'按钮或点击失败")
        return False

    def get_exam_score(self) -> float:
        """
        获取考试分数
        从结果页面提取分数，返回浮点数（如 98.5）
        
        HTML格式1: <div class="score"><h2>98.5</h2><h3>当前得分</h3></div>
        HTML格式2: "得分：98.5" 或 "当前得分：98.5"
        """
        page = self.ensure_page()
        try:
            import re
            
            # 方式1: 从.score的h2中提取分数（数字在"当前得分"之前）
            try:
                score_h2 = page.locator('.score h2').first
                if score_h2.is_visible(timeout=1000):
                    score_text = score_h2.inner_text().strip()
                    match = re.search(r"(\d+\.?\d*)", score_text)
                    if match:
                        score = float(match.group(1))
                        self.log(f"检测到考试分数: {score}")
                        return score
            except Exception:
                pass
            
            # 方式2: 从body文本中匹配"得分：98.5"格式（"得分"在数字之前）
            body_text = page.locator("body").inner_text()
            match = re.search(r"得分[：:]\s*(\d+\.?\d*)", body_text)
            if match:
                score = float(match.group(1))
                self.log(f"检测到考试分数: {score}")
                return score
                
            # 方式3: 从body文本中匹配"数字 当前得分"格式（数字在"当前得分"之前）
            match = re.search(r"(\d+\.?\d*)\s*[分]?\s*当前得分", body_text)
            if match:
                score = float(match.group(1))
                self.log(f"检测到考试分数: {score}")
                return score
                
        except Exception as e:
            self.log(f"获取考试分数失败: {e}")
        return 0.0

    def get_wrong_questions_from_review(self, db, log, threshold: float = 0.82) -> int:
        """
        从'考试回顾'页面获取错题，提取正确答案和解析，存入数据库
        返回: 成功更新的题目数量

        错题HTML结构:
        <div data-v-2e1a611f="" class="exam-sc-stem qa-1">
            <span data-v-2e1a611f="" class="que-status is-error"> 错误 </span>
            ...
        </div>
        或（只看错题模式）:
        <div data-v-2ela6llf class="exam-sc-box2">
            <span data-v-2ela6llf class="que-status is-error">错误</span>
            <span data-v-33430a00="">答案解析 <i class="van-icon van-icon-arrow-down"></i></span>
        </div>
        """
        page = self.ensure_page()
        updated_count = 0

        try:
            # 先尝试点击"只看错题"按钮（如果存在）
            try:
                filter_btn = page.locator('text=只看错题').first
                if filter_btn.is_visible(timeout=2000):
                    filter_btn.click()
                    log("已点击'只看错题'")
                    page.wait_for_timeout(2000)
            except Exception:
                pass

            # 找到所有包含错误状态的题目（支持多种选择器）
            wrong_items = None
            selectors = [
                '.exam-sc-stem:has(.que-status.is-error)',
                '.exam-sc-box2:has(.que-status.is-error)',
                '.exam-sc-stem.qa-1:has(.is-error)',
                'div:has(.que-status.is-error)',
            ]
            for selector in selectors:
                try:
                    items = page.locator(selector)
                    count = items.count()
                    if count > 0:
                        wrong_items = items
                        log(f"使用选择器找到错题: {selector}")
                        break
                except Exception:
                    continue

            if wrong_items is None:
                log("未找到错题元素")
                return 0

            wrong_count = wrong_items.count()
            log(f"在考试回顾中找到 {wrong_count} 道错题")

            for i in range(wrong_count):
                try:
                    # 点击错题，展开详情
                    wrong_item = wrong_items.nth(i)
                    wrong_item.click()
                    page.wait_for_timeout(1500)

                    # 尝试点击"答案解析"按钮（只看错题模式需要）
                    try:
                        answer_analysis_btn = wrong_item.locator('text=答案解析').first
                        if answer_analysis_btn.is_visible(timeout=2000):
                            answer_analysis_btn.click()
                            log(f"错题 {i+1}: 已点击'答案解析'")
                            page.wait_for_timeout(1500)
                    except Exception:
                        pass

                    # 提取题目数据
                    data = self.extract_question_data()
                    question_text = data["question_text"]
                    question_type = data["question_type"]
                    options = data["options"]

                    log(f"错题 {i+1}/{wrong_count}: {question_text[:50]}...")

                    # 展开答案解析（如果上面没点到）
                    if self.expand_answer_explanation():
                        # 提取正确答案和解析
                        # 注意：在考试回顾页面，options 可能不准确，所以 skip_option_text=True
                        answer, analysis = self.extract_correct_answer_from_explanation(
                            question_type, options, skip_option_text=True
                        )

                        if answer:
                            # 验证答案格式是否与题目类型匹配
                            fixed_answer, was_fixed = db.verify_and_fix_answer(answer, question_type)
                            if was_fixed:
                                log(f"答案格式已修复: {answer} -> {fixed_answer}")
                                answer = fixed_answer

                            # 检查答案是否有效
                            if not answer:
                                log(f"错题 {i+1} 答案无效，跳过")
                                continue

                            # 存入数据库
                            matched = db.find_question(question_text, options, threshold=threshold)
                            if matched:
                                # 验证匹配到的题目是否真的匹配（相似度检查）
                                match_score = matched.get("_match_score", 0.0)
                                if match_score >= 0.90:
                                    # 高置信度匹配，直接更新
                                    db.update_question_answer(int(matched["id"]), answer, analysis or "")
                                    log(f"已更新错题答案(高置信度): {answer}")
                                    updated_count += 1
                                elif match_score >= threshold:
                                    # 中等置信度，检查题目内容是否真的相似
                                    from utils import normalize_text, fuzzy_score
                                    old_text_norm = normalize_text(matched.get("question_text", "") or "")
                                    new_text_norm = normalize_text(question_text)
                                    text_similarity = fuzzy_score(old_text_norm, new_text_norm)
                                    if text_similarity >= 0.90:
                                        db.update_question_answer(int(matched["id"]), answer, analysis or "")
                                        log(f"已更新错题答案(文本验证): {answer} (相似度={text_similarity:.2f})")
                                        updated_count += 1
                                    else:
                                        # 文本相似度不够，可能是不同题目，插入新记录
                                        log(f"匹配题目相似度不足({text_similarity:.2f})，插入新记录")
                                        db.insert_question_if_not_exists(
                                            question_type=question_type or "单选题",
                                            question_text=question_text,
                                            options=options,
                                            answer=answer,
                                            analysis=analysis,
                                            source="考试回顾补录(新)"
                                        )
                                        updated_count += 1
                                else:
                                    # 匹配分数太低，插入新记录
                                    log(f"匹配分数太低({match_score:.2f})，插入新记录")
                                    db.insert_question_if_not_exists(
                                        question_type=question_type or "单选题",
                                        question_text=question_text,
                                        options=options,
                                        answer=answer,
                                        analysis=analysis,
                                        source="考试回顾补录(新)"
                                    )
                                    updated_count += 1
                            else:
                                # 如果数据库中没有，插入新记录
                                db.insert_question_if_not_exists(
                                    question_type=question_type or "单选题",
                                    question_text=question_text,
                                    options=options,
                                    answer=answer,
                                    analysis=analysis,
                                    source="考试回顾补录"
                                )
                                log(f"已插入错题: {answer}")
                                updated_count += 1
                        else:
                            log(f"错题 {i+1} 未提取到答案")
                    else:
                        log(f"错题 {i+1} 展开解析失败")

                    # 返回考试回顾列表
                    page.wait_for_timeout(500)

                except Exception as e:
                    log(f"处理错题 {i+1} 失败: {e}")
                    continue

            log(f"考试回顾处理完成，共更新 {updated_count} 道错题")
            return updated_count

        except Exception as e:
            log(f"获取错题失败: {e}")
            return 0

    def close(self) -> None:
        self._assert_thread()
        # 逐项清理，单项失败不影响后续
        if self.context is not None:
            try:
                self.context.close()
            except Exception as e:
                self.log(f"context 关闭异常: {e}")
            self.context = None
        if self.browser is not None:
            try:
                self.browser.close()
            except Exception as e:
                self.log(f"browser 关闭异常: {e}")
            self.browser = None
        if self.playwright is not None:
            try:
                self.playwright.stop()
            except Exception as e:
                self.log(f"playwright 停止异常: {e}")
            self.playwright = None
        self.page = None
