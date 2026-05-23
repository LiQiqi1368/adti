"""
授权码生成工具 v3.0（独立运行，无需打开主软件）
功能：输入用户机器码 + 选择过期时间 → 生成加密授权码
用户将授权码粘贴到软件的"授权激活"框即可激活
"""
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox

# 将上级目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from license import generate_machine_code, generate_license_code

BG_COLOR = "#f5f5f5"


def get_base_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def build_ui():
    root = tk.Tk()
    root.title("授权码生成工具 v3.0")
    root.geometry("620x420")
    root.configure(bg=BG_COLOR)

    # ===== 标题 =====
    tk.Label(
        root,
        text="输入用户的机器码，设置授权期限，生成加密授权码",
        bg=BG_COLOR,
        font=("", 10)
    ).pack(pady=(15, 10))

    # ===== 机器码输入 =====
    input_frame = ttk.Frame(root)
    input_frame.pack(fill="x", padx=30)

    ttk.Label(input_frame, text="用户机器码：").pack(anchor="w", pady=(0, 4))
    code_var = tk.StringVar()
    entry = ttk.Entry(input_frame, textvariable=code_var, font=("Consolas", 11), width=55)
    entry.pack(fill="x", pady=(0, 10))
    entry.focus()

    # ===== 过期时间选择 =====
    date_frame = ttk.Frame(root)
    date_frame.pack(fill="x", padx=30, pady=(0, 10))

    ttk.Label(date_frame, text="授权过期时间：").pack(anchor="w", pady=(0, 4))

    presets_frame = ttk.Frame(date_frame)
    presets_frame.pack(fill="x")

    now = datetime.now()
    expiry_var = tk.StringVar(value=(now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M"))

    def set_expiry(days: int):
        if days == 0:
            expiry_var.set("")
            expiry_label.config(text="永久有效")
        else:
            d = now + timedelta(days=days)
            expiry_var.set(d.strftime("%Y-%m-%d %H:%M"))
            expiry_label.config(text=d.strftime("%Y-%m-%d %H:%M"))

    presets = [("7天", 7), ("30天", 30), ("90天", 90),
               ("半年", 180), ("一年", 365), ("永久", 0)]
    for label, days in presets:
        ttk.Button(presets_frame, text=label, width=8,
                   command=lambda d=days: set_expiry(d)).pack(side="left", padx=2)

    # 时间显示
    time_frame = ttk.Frame(date_frame)
    time_frame.pack(fill="x", pady=(8, 0))
    ttk.Label(time_frame, text="当前时间：").pack(side="left")
    ttk.Label(time_frame, text=now.strftime("%Y-%m-%d %H:%M"),
              font=("", 9, "bold")).pack(side="left", padx=(0, 15))
    ttk.Label(time_frame, text="过期时间：").pack(side="left")
    expiry_label = tk.Label(time_frame,
                            text=(now + timedelta(days=30)).strftime("%Y-%m-%d %H:%M"),
                            font=("", 9, "bold"), fg="red", bg=BG_COLOR)
    expiry_label.pack(side="left", padx=(0, 5))
    ttk.Button(time_frame, text="手动输入", command=lambda: _manual_time()).pack(side="left")

    def _manual_time():
        win = tk.Toplevel(root)
        win.title("手动输入时间")
        win.geometry("340x130")
        win.transient(root)
        win.grab_set()
        tk.Label(win, text="格式: YYYY-MM-DD HH:MM\n空=永久  例: 2026-12-31 18:00",
                 justify="left").pack(pady=(8, 5))
        var = tk.StringVar(value=expiry_var.get() or "")
        e = ttk.Entry(win, textvariable=var, font=("Consolas", 11), width=25)
        e.pack(pady=5)
        e.select_range(0, "end")
        e.focus()

        def confirm():
            val = var.get().strip()
            if val:
                for fmt in ["%Y-%m-%d %H:%M", "%Y-%m-%d"]:
                    try:
                        datetime.strptime(val, fmt)
                        expiry_var.set(val)
                        expiry_label.config(text=val)
                        win.destroy()
                        return
                    except ValueError:
                        continue
                messagebox.showerror("格式错误", "请使用格式: YYYY-MM-DD HH:MM")
            else:
                expiry_var.set("")
                expiry_label.config(text="永久有效")
                win.destroy()

        ttk.Button(win, text="确认", command=confirm).pack(pady=5)

    def do_generate():
        code = code_var.get().strip().upper()
        if not code or len(code) < 10:
            messagebox.showerror("错误", "请输入有效的机器码！")
            return

        try:
            expires = expiry_var.get().strip()
            license_code = generate_license_code(code, expires if expires else "")
            result_var.set(license_code)
            result_entry.select_range(0, "end")
            expire_text = f"过期: {expires}" if expires else "永久有效"
            log_text = f"机器码: {code}\n{expire_text}\n授权码已生成，请复制发给用户"
            log_label.config(text=log_text)
            messagebox.showinfo("成功", "授权码已生成！\n点击'复制'按钮发给用户。")
        except Exception as e:
            messagebox.showerror("错误", f"生成失败：{e}")

    # ===== 生成按钮 =====
    ttk.Button(root, text="生成授权码", command=do_generate).pack(pady=(0, 10))

    # ===== 结果区域 =====
    result_frame = ttk.LabelFrame(root, text="生成的授权码（复制后发给用户）", padding=8)
    result_frame.pack(fill="x", padx=30, pady=(0, 10))

    result_var = tk.StringVar()
    result_entry = ttk.Entry(result_frame, textvariable=result_var,
                             font=("Consolas", 10), width=60)
    result_entry.pack(fill="x", pady=(0, 6))

    btn_frame = ttk.Frame(result_frame)
    btn_frame.pack(fill="x")

    def copy_result():
        code = result_var.get().strip()
        if not code:
            return
        root.clipboard_clear()
        root.clipboard_append(code)
        messagebox.showinfo("已复制", "授权码已复制到剪贴板，可以发给用户了")

    ttk.Button(btn_frame, text="📋 复制授权码", command=copy_result).pack(side="left", padx=2)
    ttk.Button(btn_frame, text="清空", command=lambda: result_var.set("")).pack(side="left", padx=2)

    # ===== 日志信息 =====
    log_label = tk.Label(root, text="", font=("", 8), fg="gray",
                         bg=BG_COLOR, justify="left")
    log_label.pack(pady=(0, 5))

    # ===== 底部：本机信息 =====
    sep = ttk.Separator(root, orient="horizontal")
    sep.pack(fill="x", padx=20, pady=(0, 8))

    bottom_frame = ttk.Frame(root)
    bottom_frame.pack(fill="x", padx=20)

    ttk.Label(bottom_frame, text="本机机器码（开发者参考）：",
              font=("", 9)).pack(anchor="w")
    dev_code = generate_machine_code()
    tk.Label(bottom_frame, text=dev_code, font=("Consolas", 9),
             fg="blue", bg=BG_COLOR).pack(anchor="w", pady=(0, 3))

    def copy_dev_code():
        root.clipboard_clear()
        root.clipboard_append(dev_code)
        messagebox.showinfo("已复制", "本机机器码已复制")

    ttk.Button(bottom_frame, text="复制本机机器码", command=copy_dev_code).pack(anchor="w")

    root.mainloop()


if __name__ == "__main__":
    build_ui()
