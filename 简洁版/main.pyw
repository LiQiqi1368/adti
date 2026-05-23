from __future__ import annotations

import os
import sys

# 修复 Playwright 在某些 asyncio 环境下的兼容性问题（"Sync API inside asyncio loop"）
os.environ.setdefault("PLAYWRIGHT_SYNC_IO_ASYNC_STACK", "0")

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

from license import verify_license, generate_machine_code

from config import (
    APP_AUTHOR,
    APP_TITLE,
    APP_WEBSITE,
    ANSWER_INTERVAL_MS,
    AUTO_CLICK_RETRY_COUNT,
    AUTO_RUN_QUESTION_BANK_AFTER_CYCLE,
    CLEAR_OLD_QUESTIONS_BEFORE_RECORD,
    DATA_DIR_NAME,
    DB_FILENAME,
    DEFAULT_CYCLE_COUNT,
    DEFAULT_QUESTION_BANK,
    LICENSE_ENABLED,
    LOGIN_PASSWORD,
    LOGIN_USERNAME,
    LOG_MAX_LINES,
    MATCH_THRESHOLD,
    POLL_INTERVAL_MS,
    TARGET_URL,
    USE_OPTION_TEXT_MATCH,
)
from db import QuestionDB
from dom_service import DomService
from workflow import run_assist_once, run_auto_answer_cycle, run_exam_review_manual, run_question_bank_check, run_record_once


def get_base_dir() -> Path:
    """获取 config.py 所在目录"""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # 打包后 config.py 在 _internal/ 中
        if (exe_dir / "_internal" / "config.py").exists():
            return exe_dir / "_internal"
        return exe_dir
    return Path(__file__).resolve().parent


def get_data_dir() -> Path:
    """获取用户数据存储目录（始终在 exe 同级，不在 _internal 中）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    return Path(__file__).resolve().parent / "data"


def resolve_playwright_browsers_dir(base_dir: Path) -> Path:
    bundled_dir = base_dir / "playwright_browsers"
    if bundled_dir.exists():
        return bundled_dir

    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if local_appdata:
        local_cache = Path(local_appdata) / "ms-playwright"
        if local_cache.exists():
            return local_cache

    return bundled_dir


BASE_DIR = get_base_dir()
PLAYWRIGHT_BROWSERS_DIR = resolve_playwright_browsers_dir(BASE_DIR)
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_DIR)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.project_dir = BASE_DIR
        self.data_dir = get_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / DB_FILENAME

        self.task_queue: queue.Queue = queue.Queue()
        self.result_queue: queue.Queue = queue.Queue()

        self.workflow_running = False
        self.is_running = False
        self.is_paused = False
        self.worker_busy = False
        self.current_mode = "record"
        self.current_question = ""
        self.current_answer = ""
        self.last_status = "就绪"
        self.worker_thread = None

        # 停止事件，用于停止循环答题
        self.stop_event = threading.Event()

        self.mode_var = tk.StringVar(value="record")
        self.url_var = tk.StringVar(value=TARGET_URL)
        self.answer_var = tk.StringVar(value="")
        self.enable_supplement_on_miss_var = tk.BooleanVar(value=True)

        # 新增：登录配置变量
        self.username_var = tk.StringVar(value=LOGIN_USERNAME)
        self.password_var = tk.StringVar(value=LOGIN_PASSWORD)

        # 新增：循环次数配置
        self.cycle_count_var = tk.IntVar(value=DEFAULT_CYCLE_COUNT)
        self.answer_delay_var = tk.StringVar(value=str(ANSWER_INTERVAL_MS))

        # 新增：题库选择配置
        self.question_bank_var = tk.IntVar(value=DEFAULT_QUESTION_BANK)
        self.question_banks = {
            1: "1钻（修）井/基本素养和形势任务Ⅱ",
            2: "1钻（修）井/专业知识",
            3: "1钻（修）井/HSE通用知识Ⅱ",
            4: "1钻（修）井/HSE法律法规Ⅱ",
            5: "0石油工程基础/基本素养和形势任务Ⅱ",
        }

        # 授权状态
        self.license_var = tk.StringVar(value="正在验证授权...")
        self.license_valid = False
        # 授权码
        self.license_code_var = tk.StringVar(value="")

        self.log_lines: list[str] = []

        self.build_ui()
        # 将主窗口移出屏幕，弹出授权弹窗
        self.root.geometry("+9999+9999")
        self.show_license_dialog()  # 弹出授权窗口
        # 授权通过，将主窗口居中显示
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        cx = max(0, (sw - 1300) // 2)
        cy = max(0, (sh - 860) // 2)
        self.root.geometry(f"1300x860+{cx}+{cy}")
        self.append_log(f"[DEBUG] 当前数据库路径: {self.db_path}")
        self.start_worker_thread()
        self.poll_result_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self):
        self.root.title(APP_TITLE)
        self.root.geometry("1300x860")
        self.root.minsize(1200, 800)
        self.root.configure(bg="#f5f6fa")

        # ===== 样式系统 =====
        style = ttk.Style()
        style.theme_use("clam")

        # 调色板（极简专业风）
        C = {
            "primary": "#4f6ef7",
            "primary_dark": "#3b5de7",
            "danger": "#ef4444",
            "bg": "#f5f6fa",
            "card": "#ffffff",
            "text": "#1e293b",
            "text_sec": "#64748b",
            "border": "#e2e8f0",
            "header_bg": "#1e293b",
            "gray_btn": "#e8ecf1",
            "gray_btn_text": "#334155",
        }

        # ===== 按钮样式（极简：仅蓝色 + 红色 + 灰色） =====
        BTN_PAD = (16, 6)

        # 蓝色主按钮（全自动答题等核心操作）
        style.configure("Primary.TButton", background=C["primary"], foreground="white",
                        borderwidth=0, focusthickness=0, font=("微软雅黑", 9), padding=BTN_PAD)
        style.map("Primary.TButton", background=[("active", C["primary_dark"])])

        # 红色危险按钮（仅停止用）
        style.configure("Danger.TButton", background=C["danger"], foreground="white",
                        borderwidth=0, focusthickness=0, font=("微软雅黑", 9), padding=BTN_PAD)
        style.map("Danger.TButton", background=[("active", "#dc2626")])

        # 灰色次要按钮（所有其他操作，统一风格）
        style.configure("Default.TButton", background=C["gray_btn"], foreground=C["gray_btn_text"],
                        borderwidth=0, focusthickness=0, font=("微软雅黑", 9), padding=BTN_PAD)
        style.map("Default.TButton", background=[("active", "#d1d5db")])

        # 白色边框按钮（置入卡片内的次要操作）
        style.configure("Outline.TButton", background=C["card"], foreground=C["text"],
                        borderwidth=1, focusthickness=0, font=("微软雅黑", 9), padding=BTN_PAD,
                        relief="solid")
        style.map("Outline.TButton", background=[("active", "#f1f5f9")])

        # 下拉框样式
        style.configure("TCombobox", font=("微软雅黑", 9), padding=4)
        style.configure("ComboboxPopdownFrame", relief="solid", borderwidth=1)

        # 单选框样式
        style.configure("TRadiobutton", font=("微软雅黑", 9), padding=2,
                        background=C["card"], foreground=C["text"])
        style.map("TRadiobutton",
                  background=[("active", C["card"]), ("selected", C["card"])])

        # 复选框样式
        style.configure("TCheckbutton", font=("微软雅黑", 9), padding=2,
                        background=C["card"], foreground=C["text"])
        style.map("TCheckbutton",
                  background=[("active", C["card"]), ("selected", C["card"])])

        # Spinbox 样式
        style.configure("TSpinbox", font=("微软雅黑", 9), padding=2)

        # Entry 样式
        style.configure("TEntry", font=("微软雅黑", 9), padding=2)

        # LabelFrame 卡片样式
        style.configure("Card.TLabelframe", background=C["card"], relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=C["card"],
                        foreground=C["primary"], font=("微软雅黑", 10, "bold"), padding=(0, 4))

        # ===== 顶部标题栏（简洁白底） =====
        header = tk.Frame(self.root, bg=C["card"], height=48, highlightthickness=0)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(header, text=f"全自动答题系统", font=("微软雅黑", 13, "bold"),
                 fg=C["text"], bg=C["card"]).pack(side="left", padx=(20, 0))
        tk.Label(header, text=f"by {APP_AUTHOR}  {APP_WEBSITE}  |  定制版", font=("微软雅黑", 8),
                 fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(6, 0), pady=10)

        self.status_var = tk.StringVar(value="状态：就绪")
        self.status_label = tk.Label(header, textvariable=self.status_var,
                                     font=("微软雅黑", 9, "bold"),
                                     fg=C["primary"], bg=C["card"])
        self.status_label.pack(side="right", padx=(0, 20), pady=10)

        # ===== 主内容容器 =====
        main = tk.Frame(self.root, bg=C["bg"])
        main.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        # 左侧面板（配置）
        left_panel = tk.Frame(main, bg=C["bg"])
        left_panel.pack(side="left", fill="y", padx=(0, 10))

        # 右侧面板（答题区 + 日志）
        right_panel = tk.Frame(main, bg=C["bg"])
        right_panel.pack(side="left", fill="both", expand=True)

        # ================================================================
        # 左侧面板
        # ================================================================

        # -- 快捷操作 --
        action_card = ttk.LabelFrame(left_panel, text="快捷操作", style="Card.TLabelframe", padding=10)
        action_card.pack(fill="x", pady=(0, 8))

        btn_row1 = tk.Frame(action_card, bg=C["card"])
        btn_row1.pack(fill="x", pady=(0, 4))
        ttk.Button(btn_row1, text="▶ 全自动答题", style="Primary.TButton",
                   command=self.on_auto_answer).pack(side="left", padx=2)
        ttk.Button(btn_row1, text="继续答题", style="Default.TButton",
                   command=self.on_continue_answer).pack(side="left", padx=2)

        btn_row2 = tk.Frame(action_card, bg=C["card"])
        btn_row2.pack(fill="x")
        ttk.Button(btn_row2, text="⏹ 停止", style="Danger.TButton",
                   command=self.on_stop).pack(side="left", padx=2)
        ttk.Button(btn_row2, text="考试回顾", style="Default.TButton",
                   command=self.on_exam_review).pack(side="left", padx=2)
        ttk.Button(btn_row2, text="跑题库", style="Default.TButton",
                   command=self.on_run_question_bank).pack(side="left", padx=2)
        ttk.Button(btn_row2, text="清空题库", style="Default.TButton",
                   command=self.on_clear_db).pack(side="left", padx=2)

        # -- 登录配置 --
        login_card = ttk.LabelFrame(left_panel, text="登录配置", style="Card.TLabelframe", padding=10)
        login_card.pack(fill="x", pady=(0, 8))

        row1 = tk.Frame(login_card, bg=C["card"])
        row1.pack(fill="x", pady=(0, 6))
        tk.Label(row1, text="账号", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        ttk.Entry(row1, textvariable=self.username_var, width=16).pack(side="left", padx=(0, 10))
        tk.Label(row1, text="密码", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        ttk.Entry(row1, textvariable=self.password_var, width=16, show="*").pack(side="left", padx=(0, 6))
        ttk.Button(row1, text="保存", style="Default.TButton", command=self.save_login_config).pack(side="left")

        # -- 循环配置 --
        cycle_card = ttk.LabelFrame(left_panel, text="循环配置", style="Card.TLabelframe", padding=10)
        cycle_card.pack(fill="x", pady=(0, 8))

        row2 = tk.Frame(cycle_card, bg=C["card"])
        row2.pack(fill="x")
        tk.Label(row2, text="轮数 (0=无限)", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        ttk.Spinbox(row2, textvariable=self.cycle_count_var, from_=0, to=999, width=6).pack(side="left", padx=(0, 12))
        tk.Label(row2, text="题库", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        self.bank_combo = ttk.Combobox(row2, values=list(self.question_banks.values()), state="readonly", width=30)
        self.bank_combo.current(DEFAULT_QUESTION_BANK - 1)
        self.bank_combo.pack(side="left")

        delay_row = tk.Frame(cycle_card, bg=C["card"])
        delay_row.pack(fill="x", pady=(6, 0))
        tk.Label(delay_row, text="答题间隔", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        ttk.Spinbox(delay_row, textvariable=self.answer_delay_var, from_=500, to=10000, increment=100, width=6).pack(side="left", padx=(0, 4))
        self.delay_sec_label = tk.Label(delay_row, font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"])
        self.delay_sec_label.pack(side="left")

        # 实时更新秒数显示
        def _update_delay_label(*_):
            try:
                ms = int(self.answer_delay_var.get())
            except (ValueError, TypeError):
                ms = ANSWER_INTERVAL_MS
            self.delay_sec_label.config(text=f"({ms/1000:.1f}秒)")
        self.answer_delay_var.trace_add("write", _update_delay_label)
        _update_delay_label()  # 初始化
        tk.Label(delay_row, text="毫秒", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left")

        # -- 辅助模式 --
        assist_card = ttk.LabelFrame(left_panel, text="辅助模式", style="Card.TLabelframe", padding=10)
        assist_card.pack(fill="x", pady=(0, 8))

        mode_row = tk.Frame(assist_card, bg=C["card"])
        mode_row.pack(fill="x", pady=(0, 6))
        tk.Label(mode_row, text="模式:", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left")
        ttk.Radiobutton(mode_row, text="录题", variable=self.mode_var, value="record").pack(side="left", padx=6)
        ttk.Radiobutton(mode_row, text="辅助答题", variable=self.mode_var, value="assist").pack(side="left", padx=6)
        ttk.Checkbutton(mode_row, text="未命中自动补库", variable=self.enable_supplement_on_miss_var).pack(side="left", padx=(10, 0))

        url_row = tk.Frame(assist_card, bg=C["card"])
        url_row.pack(fill="x")
        tk.Label(url_row, text="网址", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left", padx=(0, 4))
        ttk.Entry(url_row, textvariable=self.url_var, width=22).pack(side="left", padx=(0, 4))
        ttk.Button(url_row, text="打开", style="Default.TButton", command=self.open_web_page).pack(side="left", padx=2)
        ttk.Button(url_row, text="开始", style="Primary.TButton", command=self.on_start).pack(side="left", padx=2)
        ttk.Button(url_row, text="暂停", style="Default.TButton", command=self.on_pause).pack(side="left", padx=2)
        ttk.Button(url_row, text="停止", style="Danger.TButton", command=self.on_stop).pack(side="left", padx=2)

        # ================================================================
        # 右侧面板
        # ================================================================

        # -- 当前答案 --
        answer_card = ttk.LabelFrame(right_panel, text="当前答案", style="Card.TLabelframe", padding=10)
        answer_card.pack(fill="x", pady=(0, 8))

        ans_row = tk.Frame(answer_card, bg=C["card"])
        ans_row.pack(fill="x")
        tk.Label(ans_row, text="答案：", font=("微软雅黑", 9), fg=C["text_sec"], bg=C["card"]).pack(side="left")
        self.answer_entry = ttk.Entry(ans_row, textvariable=self.answer_var, width=40)
        self.answer_entry.pack(side="left", fill="x", expand=True)

        # -- 当前题目 --
        question_card = ttk.LabelFrame(right_panel, text="当前题目", style="Card.TLabelframe", padding=10)
        question_card.pack(fill="x", pady=(0, 8))

        self.question_text = ScrolledText(question_card, height=8, wrap="word",
                                          font=("微软雅黑", 9), relief="flat", borderwidth=1,
                                          highlightthickness=1, highlightcolor=C["border"],
                                          highlightbackground=C["border"])
        self.question_text.pack(fill="x")

        # -- 日志 --
        log_card = ttk.LabelFrame(right_panel, text="日志输出", style="Card.TLabelframe", padding=10)
        log_card.pack(fill="both", expand=True)

        self.log_text = ScrolledText(log_card, height=14, wrap="word",
                                     font=("微软雅黑", 9), relief="flat", borderwidth=1,
                                     highlightthickness=1, highlightcolor=C["border"],
                                     highlightbackground=C["border"])
        self.log_text.pack(fill="both", expand=True)

        # ===== 底部状态栏（浅灰） =====
        footer = tk.Frame(self.root, bg=C["bg"], height=28)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        machine_code = generate_machine_code()
        tk.Label(footer, text=f"机器码: {machine_code[:20]}...",
                 font=("Consolas", 8), fg=C["text_sec"], bg=C["bg"]).pack(side="left", padx=12)

        # 免责声明
        tk.Label(footer, text="⚠ 本工具仅供学习交流，定制版使用产生的一切问题与原作者无关",
                 font=("微软雅黑", 8), fg="#94a3b8", bg=C["bg"]).pack(side="left", padx=(30, 0))

        self.license_status = tk.Label(footer, text="", font=("微软雅黑", 8),
                                       fg=C["text_sec"], bg=C["bg"])
        self.license_status.pack(side="right", padx=12)

    def show_license_dialog(self):
        """显示授权激活对话框（验证通过后返回，否则持续显示）"""
        if not LICENSE_ENABLED:
            self.license_valid = True
            return

        # 尝试自动加载已保存的授权码
        code_file = self.data_dir / "license.code"
        saved_code = ""
        if code_file.exists():
            try:
                saved_code = code_file.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        # 已保存的授权码有效，直接通过
        if saved_code:
            try:
                authorized, msg = verify_license(saved_code)
                if authorized:
                    self.license_valid = True
                    self.license_code_var.set(saved_code)
                    self.append_log(f"授权验证通过: {msg}")
                    return
            except Exception:
                pass

        # ===== 显示授权对话框 =====
        machine_code = generate_machine_code()

        dialog = tk.Toplevel(self.root)
        dialog.title("软件授权激活")
        dialog.geometry("500x430")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg="#ffffff")

        # 居中显示
        dialog.update_idletasks()
        dw, dh = 500, 430
        sw = dialog.winfo_screenwidth()
        sh = dialog.winfo_screenheight()
        cx = max(0, (sw - dw) // 2)
        cy = max(0, (sh - dh) // 2)
        dialog.geometry(f"{dw}x{dh}+{cx}+{cy}")

        # 关闭弹窗 = 退出整个软件
        def close_app():
            dialog.destroy()
            self.root.destroy()
        dialog.protocol("WM_DELETE_WINDOW", close_app)

        # 标题区
        title_frame = tk.Frame(dialog, bg="#1677ff", height=95)
        title_frame.pack(fill="x")
        title_frame.pack_propagate(False)

        tk.Label(title_frame, text="全自动答题系统", font=("微软雅黑", 18, "bold"),
                 fg="white", bg="#1677ff").pack(pady=(8, 0))
        tk.Label(title_frame, text="请激活授权后使用", font=("微软雅黑", 10),
                 fg="#d9e8ff", bg="#1677ff").pack()
        tk.Label(title_frame, text=f"© 2026 {APP_AUTHOR}  {APP_WEBSITE}  |  定制版",
                 font=("微软雅黑", 8), fg="#a5b4fc", bg="#1677ff").pack(pady=(3, 0))

        # 内容区
        content = tk.Frame(dialog, bg="#ffffff", padx=30, pady=20)
        content.pack(fill="both", expand=True)

        # 机器码
        tk.Label(content, text="您的机器码（复制后发给开发者获取授权码）：",
                 font=("微软雅黑", 9), fg="#333333", bg="#ffffff",
                 anchor="w").pack(fill="x", pady=(0, 4))

        code_frame = tk.Frame(content, bg="#ffffff")
        code_frame.pack(fill="x", pady=(0, 12))

        code_entry = tk.Entry(code_frame, font=("Consolas", 11), justify="center",
                              width=40, relief="solid", borderwidth=1)
        code_entry.insert(0, machine_code)
        code_entry.config(state="readonly")
        code_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        def copy_code():
            self.root.clipboard_clear()
            self.root.clipboard_append(machine_code)
            # 临时反馈
            copy_btn.config(text="✅ 已复制")
            dialog.after(1500, lambda: copy_btn.config(text="📋 复制"))

        copy_btn = tk.Button(code_frame, text="📋 复制", command=copy_code,
                             font=("微软雅黑", 9), bg="#f0f2f5", relief="flat",
                             padx=10, cursor="hand2")
        copy_btn.pack(side="left")

        # 分隔线
        sep = tk.Frame(content, bg="#e8e8e8", height=1)
        sep.pack(fill="x", pady=(0, 12))

        # 授权码输入
        tk.Label(content, text="粘贴开发者给你的授权码：",
                 font=("微软雅黑", 9), fg="#333333", bg="#ffffff",
                 anchor="w").pack(fill="x", pady=(0, 4))

        input_frame = tk.Frame(content, bg="#ffffff")
        input_frame.pack(fill="x", pady=(0, 12))

        code_input_var = tk.StringVar()
        code_input = tk.Entry(input_frame, textvariable=code_input_var,
                              font=("Consolas", 10), relief="solid", borderwidth=1)
        code_input.pack(side="left", fill="x", expand=True, padx=(0, 6))
        code_input.focus()

        # ===== 免责声明 =====
        disclaimer_frame = tk.Frame(content, bg="#fff7ed", highlightbackground="#fed7aa",
                                    highlightthickness=1, padx=10, pady=6)
        disclaimer_frame.pack(fill="x", pady=(0, 8))
        tk.Label(disclaimer_frame,
                 text="⚠ 使用须知",
                 font=("微软雅黑", 8, "bold"), fg="#9a3412", bg="#fff7ed",
                 anchor="w").pack(fill="x")
        tk.Label(disclaimer_frame,
                 text="1. 本软件仅供学习交流，严禁用于考试作弊\n2. 使用者需自行承担一切使用后果\n3. 点击激活即表示同意以上条款",
                 font=("微软雅黑", 8), fg="#92400e", bg="#fff7ed",
                 anchor="w", justify="left").pack(fill="x")

        # 状态消息
        status_label = tk.Label(content, text="", font=("微软雅黑", 9),
                                bg="#ffffff", fg="#ff4d4f")
        status_label.pack(fill="x", pady=(0, 8))

        def do_activate():
            code = code_input_var.get().strip()
            if not code:
                status_label.config(text="⚠️ 请先输入授权码")
                return

            try:
                authorized, msg = verify_license(code)
                if authorized:
                    self.license_valid = True
                    self.license_code_var.set(code)
                    # 保存授权码
                    try:
                        code_file.write_text(code, encoding="utf-8")
                    except Exception:
                        pass
                    self.append_log(f"授权码激活成功: {msg}")
                    try:
                        self.license_status.config(text=f"✅ 已授权")
                    except Exception:
                        pass
                    dialog.destroy()
                else:
                    status_label.config(text=f"❌ {msg}", fg="#ff4d4f")
            except Exception as e:
                status_label.config(text=f"❌ 验证异常: {e}", fg="#ff4d4f")

        # 激活按钮
        activate_btn = tk.Button(content, text="激活授权码",
                                 font=("微软雅黑", 11, "bold"),
                                 bg="#1677ff", fg="white", relief="flat",
                                 height=1, cursor="hand2", command=do_activate)
        activate_btn.pack(fill="x", pady=(0, 8))

        # 回车键激活
        code_input.bind("<Return>", lambda e: do_activate())

        # 未授权状态提示
        if saved_code:
            status_label.config(text="⚠️ 已保存的授权码无效或已过期，请重新输入", fg="#faad14")

        # 等待对话框关闭
        dialog.wait_window()

        # 如果对话框关闭但未授权，直接退出
        if not self.license_valid:
            sys.exit(0)

    def on_activate_license(self):
        """激活授权码（备用，dialog 已含此功能）"""
        pass

    def save_login_config(self):
        """保存登录配置到config.py"""
        try:
            username = self.username_var.get().strip()
            password = self.password_var.get().strip()

            # 读取config.py
            config_path = get_base_dir() / "config.py"
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 替换配置值（转义反斜杠，避免路径问题）
            import re
            username_esc = username.replace("\\", "\\\\")
            password_esc = password.replace("\\", "\\\\")
            target_url = self.url_var.get().strip()
            content = re.sub(
                r'LOGIN_USERNAME = ".*"',
                f'LOGIN_USERNAME = "{username_esc}"',
                content
            )
            content = re.sub(
                r'LOGIN_PASSWORD = ".*"',
                f'LOGIN_PASSWORD = "{password_esc}"',
                content
            )
            content = re.sub(
                r'TARGET_URL = ".*"',
                f'TARGET_URL = "{target_url}"',
                content
            )

            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)

            self.append_log(f"配置已保存（账号: {username[:3]}***，网址: {target_url[:30]}...）")
        except Exception as e:
            self.append_log(f"保存配置失败: {e}")

    def show_machine_code(self):
        """显示机器码（可复制）"""
        try:
            machine_code = generate_machine_code()
            win = tk.Toplevel(self.root)
            win.title("机器码")
            win.geometry("460x150")
            win.resizable(False, False)
            win.transient(self.root)
            win.grab_set()

            tk.Label(win, text="您的机器码（复制后发给开发者获取授权码）:", font=("", 10, "bold")).pack(pady=(15, 5))

            text_var = tk.StringVar(value=machine_code)
            entry = tk.Entry(win, textvariable=text_var, font=("Consolas", 11), justify="center", state="readonly", width=40)
            entry.pack(pady=5)
            entry.select_range(0, "end")

            btn_frame = tk.Frame(win)
            btn_frame.pack(pady=(5, 10))
            tk.Button(btn_frame, text="复制机器码", width=15, command=lambda: self._copy_to_clipboard(win, machine_code)).pack(side="left", padx=10)
            tk.Button(btn_frame, text="关闭", width=10, command=win.destroy).pack(side="left", padx=10)

            win.wait_window()
        except Exception as e:
            messagebox.showerror("错误", f"获取机器码失败: {e}")

    def _copy_to_clipboard(self, window, text: str):
        """复制文本到剪贴板"""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        messagebox.showinfo("已复制", "机器码已复制到剪贴板")

    def on_auto_answer(self):
        """全自动答题"""
        if not self.license_valid:
            messagebox.showerror("授权失败", "请先获取授权后再使用此功能")
            return

        # 验证必填项
        target_url = self.url_var.get().strip()

        errors = []
        if not target_url:
            errors.append("目标网址未填写")

        if errors:
            messagebox.showerror("配置不完整", "请先完成以下配置：\n\n" + "\n".join(f"• {e}" for e in errors))
            return

        cycle_count = self.cycle_count_var.get()
        # 从下拉框获取题库索引
        bank_index = self.bank_combo.current() + 1  # 0-based -> 1-based
        if bank_index < 1:
            bank_index = DEFAULT_QUESTION_BANK

        self.reset_runtime_state()
        self.reset_gui_state()
        self.workflow_running = True
        self.is_running = True
        self.last_status = "全自动答题中"
        self.set_status(f"状态：全自动答题中（轮数: {'无限' if cycle_count == 0 else cycle_count}，题库: {self.question_banks.get(bank_index, '?')}）")
        self.append_log(f"开始全自动答题，轮数: {'无限' if cycle_count == 0 else cycle_count}，题库: {self.question_banks.get(bank_index, '?')}")

        # 清除停止事件
        self.stop_event.clear()

        # 将任务放入队列
        self.task_queue.put({
            "type": "auto_answer",
            "mode": self.mode_var.get().strip() or "assist",
            "target_url": target_url,
            "cycle_count": cycle_count,
            "question_bank": bank_index,
            "enable_supplement_on_miss": self.enable_supplement_on_miss_var.get(),
            "username": self.username_var.get().strip(),
            "password": self.password_var.get().strip(),
            "answer_delay": int(self.answer_delay_var.get() or ANSWER_INTERVAL_MS),
        })

    def on_continue_answer(self):
        """继续答题（复用当前配置重新开始一轮）"""
        self.append_log("继续答题...")
        self.on_auto_answer()

    def on_clear_db(self):
        """清空题库"""
        if not self.license_valid:
            messagebox.showerror("授权失败", "请先获取授权后再使用此功能")
            return

        result = messagebox.askyesno("确认", "确定要清空所有题库数据吗？此操作不可恢复！")
        if not result:
            return

        try:
            db = QuestionDB(self.db_path)
            count = db.clear_all_questions()
            db.close()
            self.append_log(f"已清空题库，共删除 {count} 道题目")
            messagebox.showinfo("成功", f"已清空题库，共删除 {count} 道题目")
        except Exception as e:
            self.append_log(f"清空题库失败: {e}")
            messagebox.showerror("错误", f"清空题库失败: {e}")

    def on_run_question_bank(self):
        """跑题库"""
        if not self.license_valid:
            messagebox.showerror("授权失败", "请先获取授权后再使用此功能")
            return

        self.append_log("开始跑题库...")
        self.task_queue.put({
            "type": "run_question_bank",
            "target_url": self.url_var.get().strip(),
        })

    def on_exam_review(self):
        """手动触发考试回顾"""
        if not self.license_valid:
            messagebox.showerror("授权失败", "请先获取授权后再使用此功能")
            return
        self.append_log("开始手动考试回顾...")
        self.task_queue.put({
            "type": "exam_review",
            "target_url": self.url_var.get().strip(),
        })

    def reset_runtime_state(self):
        self.workflow_running = False
        self.is_running = False
        self.is_paused = False
        self.worker_busy = False
        self.current_question = ""
        self.current_answer = ""
        self.last_status = "就绪"

    def reset_gui_state(self):
        self.question_text.delete("1.0", "end")
        self.answer_var.set("")
        self.set_status("状态：就绪")

    def start_worker_thread(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return
        self.worker_thread = threading.Thread(target=self.worker_loop, daemon=True)
        self.worker_thread.start()

    def worker_log(self, message: str):
        self.result_queue.put({"type": "log", "message": str(message)})

    def worker_loop(self):
        db = QuestionDB(self.db_path)
        dom_service = None
        current_url = ""
        while True:
            task = self.task_queue.get()
            task_type = task.get("type")
            if task_type == "shutdown":
                break
            if task_type == "stop":
                self.result_queue.put({"type": "worker_idle"})
                continue

            mode = task.get("mode", "record")
            target_url = (task.get("target_url") or "").strip()
            enable_supplement_on_miss = bool(task.get("enable_supplement_on_miss", True))
            cycle_count = int(task.get("cycle_count", 1))
            question_bank = int(task.get("question_bank", 1))
            username = task.get("username", "")
            password = task.get("password", "")
            answer_delay = int(task.get("answer_delay", ANSWER_INTERVAL_MS))

            if task_type not in ["run_once", "open_page", "auto_answer", "run_question_bank", "exam_review"]:
                continue

            self.result_queue.put({"type": "worker_busy"})
            try:
                if dom_service is None or current_url != target_url:
                    if dom_service is not None:
                        try:
                            dom_service.close()
                        except Exception:
                            pass
                    dom_service = DomService(log=self.worker_log, target_url=target_url, username=username, password=password)
                    current_url = target_url

                if task_type == "open_page":
                    dom_service.ensure_page()
                    self.result_queue.put({"type": "page_opened", "target_url": target_url})
                elif task_type == "auto_answer":
                    # 全自动答题
                    result = run_auto_answer_cycle(
                        dom_service,
                        db,
                        self.worker_log,
                        cycle_count=cycle_count,
                        threshold=MATCH_THRESHOLD,
                        question_bank=question_bank,
                        stop_event=self.stop_event,
                        answer_delay=answer_delay,
                    )
                    self.result_queue.put({"type": "run_result", "result": result})

                    # 答题完成后，如果设置了自动跑题库，则执行
                    if AUTO_RUN_QUESTION_BANK_AFTER_CYCLE:
                        self.worker_log("开始自动跑题库...")
                        run_question_bank_check(dom_service, db, self.worker_log)
                elif task_type == "run_question_bank":
                    result = run_question_bank_check(dom_service, db, self.worker_log)
                    self.result_queue.put({"type": "run_result", "result": result})
                elif task_type == "exam_review":
                    # 手动考试回顾
                    if dom_service is None:
                        dom_service = DomService(log=self.worker_log, target_url=target_url)
                        current_url = target_url
                    dom_service.ensure_page()
                    result = run_exam_review_manual(dom_service, db, self.worker_log, threshold=MATCH_THRESHOLD)
                    self.result_queue.put({"type": "run_result", "result": result})
                elif mode == "record":
                    result = run_record_once(dom_service, db, self.worker_log, threshold=MATCH_THRESHOLD)
                    self.result_queue.put({"type": "run_result", "result": result})
                else:
                    result = run_assist_once(
                        dom_service,
                        db,
                        self.worker_log,
                        threshold=MATCH_THRESHOLD,
                        enable_supplement_on_miss=enable_supplement_on_miss,
                    )
                    self.result_queue.put({"type": "run_result", "result": result})
            except Exception as exc:
                # 记录完整错误到日志
                try:
                    import traceback
                    err_log = get_data_dir() / "error.log"
                    err_log.parent.mkdir(parents=True, exist_ok=True)
                    err_log.write_text(
                        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                        encoding="utf-8"
                    )
                except Exception:
                    pass
                self.result_queue.put({"type": "run_result", "result": {"ok": False, "mode": mode, "status": f"执行异常: {exc}", "question": "", "answer": "", "options": []}})
            finally:
                self.result_queue.put({"type": "worker_idle"})
        try:
            if dom_service is not None:
                dom_service.close()
        finally:
            db.close()

    def start_workflow(self):
        self.on_start()

    def stop_workflow(self):
        self.on_stop()

    def on_start(self):
        if not self.license_valid:
            messagebox.showerror("授权失败", "请先获取授权后再使用此功能")
            return

        self.reset_runtime_state()
        self.reset_gui_state()
        self.workflow_running = True
        self.is_running = True
        self.is_paused = False
        self.current_mode = self.mode_var.get().strip() or "record"
        self.last_status = "运行中"
        self.set_status(f"状态：运行中（{self.current_mode}）")
        self.append_log("开始执行")
        self.run_dom_loop()

    def on_stop(self):
        self.workflow_running = False
        self.is_running = False
        self.is_paused = False
        self.worker_busy = False
        # 设置停止事件，通知循环答题停止
        self.stop_event.set()
        self.task_queue.put({"type": "stop"})
        self.reset_gui_state()
        self.last_status = "已停止"
        self.set_status("状态：已停止")
        self.append_log("已停止")

    def on_pause(self):
        if not self.is_running:
            return
        self.is_paused = True
        self.last_status = "已暂停"
        self.set_status("状态：已暂停")
        self.append_log("已暂停")

    def on_resume(self):
        if not self.is_running:
            return
        self.is_paused = False
        self.last_status = "运行中"
        self.set_status(f"状态：运行中（{self.current_mode}）")
        self.append_log("已恢复")

    def open_web_page(self):
        target_url = self.url_var.get().strip()
        if not target_url:
            self.set_status("状态：请先输入目标网址")
            self.append_log("请先输入目标网址")
            return
        self.set_status("状态：正在打开网页...")
        self.task_queue.put({"type": "open_page", "target_url": target_url})

    def schedule_next_task(self, force: bool = False):
        if not self.workflow_running or not self.is_running:
            return
        if self.is_paused:
            return
        if self.worker_busy and not force:
            return
        target_url = self.url_var.get().strip()
        if not target_url:
            self.set_status("状态：请先输入目标网址")
            self.append_log("请先输入目标网址")
            self.workflow_running = False
            self.is_running = False
            return
        self.task_queue.put({
            "type": "run_once",
            "mode": self.current_mode,
            "target_url": target_url,
            "enable_supplement_on_miss": self.enable_supplement_on_miss_var.get(),
        })

    def run_once_thread(self):
        threading.Thread(target=self.schedule_next_task, kwargs={"force": True}, daemon=True).start()

    def run_dom_loop(self):
        if not self.is_running:
            return
        if not self.is_paused and not self.worker_busy:
            self.run_once_thread()
        self.root.after(POLL_INTERVAL_MS, self.run_dom_loop)

    def poll_result_queue(self):
        while True:
            try:
                message = self.result_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_worker_message(message)
        self.root.after(POLL_INTERVAL_MS, self.poll_result_queue)

    def handle_worker_message(self, message: dict):
        msg_type = message.get("type")
        if msg_type == "log":
            self.append_log(message.get("message", ""))
            return
        if msg_type == "worker_busy":
            self.worker_busy = True
            if self.is_running and not self.is_paused:
                self.set_status("状态：处理中...")
            return
        if msg_type == "worker_idle":
            self.worker_busy = False
            if self.is_running and self.is_paused:
                self.set_status("状态：已暂停")
            return
        if msg_type == "page_opened":
            self.set_status("状态：网页已打开，正在自动登录...")
            self.append_log(f"网页已打开: {message.get('target_url', '')}")
            return
        if msg_type == "run_result":
            result = message.get("result") or {}
            question = result.get("question", "")
            answer = result.get("answer", "")
            status = result.get("status", "")
            self.current_question = question
            self.current_answer = answer
            self.last_status = status
            self.question_text.delete("1.0", "end")
            self.question_text.insert("1.0", question)
            self.answer_var.set(answer)
            if self.is_running and not self.is_paused:
                self.set_status(f"状态：{status}")
            return

    def set_status(self, text: str):
        """更新顶部状态文字并自动切换颜色"""
        self.status_var.set(text)
        try:
            if "就绪" in text or "完成" in text or "已停止" in text or "空闲" in text:
                self.status_label.config(fg="#64748b")
            elif "运行" in text or "答题" in text or "处理" in text or "打开" in text:
                self.status_label.config(fg="#4f6ef7")
            elif "暂停" in text:
                self.status_label.config(fg="#f59e0b")
            elif "停止" in text or "错误" in text:
                self.status_label.config(fg="#ef4444")
            else:
                self.status_label.config(fg="#1e293b")
        except Exception:
            pass

    def append_log(self, text: str):
        text = str(text or "").strip()
        if not text:
            return
        if self.log_lines and self.log_lines[-1] == text:
            return
        self.log_lines.append(text)
        if len(self.log_lines) > LOG_MAX_LINES:
            self.log_lines = self.log_lines[-LOG_MAX_LINES:]
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(self.log_lines))
        self.log_text.see("end")

    def on_close(self):
        self.workflow_running = False
        self.is_running = False
        self.is_paused = False
        self.stop_event.set()  # 通知工作线程停止
        try:
            self.task_queue.put({"type": "shutdown"})
        except Exception:
            pass
        # 等待工作线程退出（最多 5 秒），确保浏览器正确关闭
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=5.0)
        self.root.destroy()


def _global_exception_handler(exc_type, exc_value, exc_traceback):
    """全局异常捕获：不弹 Python 报错弹窗，改成友好提示框并记录日志"""
    # SystemExit（正常退出）不处理
    if exc_type is SystemExit:
        return True
    import traceback
    error_msg = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
    # 尝试保存错误日志
    try:
        log_path = get_data_dir() / "error.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(error_msg, encoding="utf-8")
    except Exception:
        pass
    # 弹出友好提示
    try:
        import tkinter.messagebox
        tkinter.messagebox.showerror(
            "程序异常",
            "软件遇到意外错误，已记录到 data/error.log\n"
            "请将错误日志发送给开发者排查。"
        )
    except Exception:
        pass
    # 阻止默认的 sys.excepthook 行为（显示控制台报错）
    return True


if __name__ == "__main__":
    # 设置全局异常处理器（捕获 tkinter 事件循环中的异常）
    import sys
    sys.excepthook = lambda t, v, tb: _global_exception_handler(t, v, tb)
    # 设置 tkinter 异常回调
    import tkinter as tk
    try:
        root = tk.Tk()
        root.report_callback_exception = lambda e, v, tb: _global_exception_handler(type(e), v, tb)
        App(root)
        root.mainloop()
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        try:
            log_path = Path(__file__).resolve().parent / "data" / "error.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(error_msg, encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror(
                "启动异常",
                f"软件启动失败，已记录到 data/error.log\n请联系开发者。"
            )
        except Exception:
            pass
