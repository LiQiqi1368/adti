"""
机器码绑定授权模块 v3.0 — 加密授权码模式
生成加密授权字符串，用户粘贴到软件中即可激活
"""
import base64
import hashlib
import hmac
import json
import os
import platform
import subprocess
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Optional


LICENSE_VERSION = "3.0"

# ===== 开发者私钥（仅在此处和授权工具中一致即可） =====
# 修改此密钥后，之前生成的所有授权码将失效
_SECRET_KEY = os.environ.get("EXAMAUTO_SECRET_KEY", "change-me-before-release").encode("utf-8")


def get_machine_fingerprint() -> str:
    """
    获取机器指纹（硬件信息组合）
    跨平台支持 Windows/Linux/Mac
    """
    fingerprint_parts = []

    # 1. 获取CPU信息
    cpu_info = _get_cpu_info()
    if cpu_info:
        fingerprint_parts.append(f"CPU:{cpu_info}")

    # 2. 获取主板序列号/系统UUID
    system_uuid = _get_system_uuid()
    if system_uuid:
        fingerprint_parts.append(f"UUID:{system_uuid}")

    # 3. 获取硬盘序列号
    disk_serial = _get_disk_serial()
    if disk_serial:
        fingerprint_parts.append(f"DISK:{disk_serial}")

    # 4. 获取MAC地址（取第一个物理网卡）
    mac = _get_mac_address()
    if mac:
        fingerprint_parts.append(f"MAC:{mac}")

    # 5. 平台信息作为辅助
    fingerprint_parts.append(f"OS:{platform.system()}:{platform.machine()}")

    # 组合并生成哈希
    raw_fingerprint = "|".join(fingerprint_parts)
    return hashlib.sha256(raw_fingerprint.encode("utf-8")).hexdigest()[:32]


def _get_cpu_info() -> Optional[str]:
    """获取CPU信息"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "cpu", "get", "ProcessorId", "/format:csv"],
                capture_output=True,
                text=True,
                timeout=5
            )
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if "ProcessorId" in line:
                    parts = line.split(",")
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()
        elif platform.system() == "Linux":
            result = subprocess.run(
                ["cat", "/proc/cpuinfo"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split("\n"):
                if line.startswith("serial") or line.startswith("cpu serial"):
                    return line.split(":")[1].strip()
    except Exception:
        pass

    # 降级方案：使用CPU型号
    try:
        return platform.processor() or ""
    except Exception:
        pass

    return ""


def _get_system_uuid() -> Optional[str]:
    """获取系统UUID"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "path", "win32_computersystemproduct", "get", "UUID", "/format:csv"],
                capture_output=True,
                text=True,
                timeout=5
            )
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if "UUID" in line:
                    parts = line.split(",")
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()
        elif platform.system() == "Linux":
            result = subprocess.run(
                ["cat", "/sys/class/dmi/id/product_uuid"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip()
    except Exception:
        pass

    return ""


def _get_disk_serial() -> Optional[str]:
    """获取硬盘序列号"""
    try:
        if platform.system() == "Windows":
            result = subprocess.run(
                ["wmic", "diskdrive", "get", "serialnumber", "/format:csv"],
                capture_output=True,
                text=True,
                timeout=5
            )
            lines = result.stdout.strip().split("\n")
            for line in lines:
                if "SerialNumber" in line:
                    parts = line.split(",")
                    if len(parts) > 1 and parts[1].strip():
                        return parts[1].strip()
    except Exception:
        pass

    return ""


def _get_mac_address() -> Optional[str]:
    """获取MAC地址（第一个物理网卡）"""
    try:
        mac = uuid.getnode()
        mac_str = ':'.join(f'{(mac >> i) & 0xff:02x}' for i in range(40, -1, -8))
        if mac_str != "00:00:00:00:00:00":
            return mac_str
    except Exception:
        pass

    return ""


def generate_machine_code() -> str:
    """生成机器码（展示给用户）"""
    fingerprint = get_machine_fingerprint()
    # 格式化为 XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX-XXXX
    return "-".join([fingerprint[i:i+4] for i in range(0, 32, 4)]).upper()


def _normalize_machine_code(code: str) -> str:
    """标准化机器码（去除分隔符，转小写）"""
    return code.replace("-", "").replace(" ", "").lower()


def _encrypt_data(data: str) -> str:
    """
    HMAC-SHA256 签名 + Base64 编码
    数据格式: machine_code|expires_at
    签名: HMAC-SHA256(_SECRET_KEY, data)
    输出: base64(data + ":" + signature)
    """
    signature = hmac.new(_SECRET_KEY, data.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    combined = f"{data}:{signature}"
    return base64.urlsafe_b64encode(combined.encode("utf-8")).decode("ascii")


def _decrypt_data(encoded: str) -> tuple[Optional[str], str]:
    """
    解码并验证授权码
    返回: (数据部分, 错误信息)
    成功时 error 为空字符串
    """
    try:
        decoded_bytes = base64.urlsafe_b64decode(encoded.encode("ascii"))
        decoded = decoded_bytes.decode("utf-8")
    except Exception:
        return None, "授权码格式错误（不是有效的 Base64）"

    # 分割数据和签名
    if ":" not in decoded:
        return None, "授权码格式错误（缺少分隔符）"

    data, signature = decoded.rsplit(":", 1)

    # 验证签名
    expected_sig = hmac.new(_SECRET_KEY, data.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    if not hmac.compare_digest(signature, expected_sig):
        return None, "授权码无效（签名不匹配，可能被篡改）"

    return data, ""


def generate_license_code(machine_code: str, expires_at: str = "") -> str:
    """
    生成加密授权码（开发者使用）
    :param machine_code: 用户的机器码
    :param expires_at: 过期时间 "2026-12-31 18:00" 或 ""（永不过期）
    :return: 加密授权码字符串
    """
    normalized_code = _normalize_machine_code(machine_code)
    data = f"{normalized_code}|{expires_at}" if expires_at else normalized_code
    return _encrypt_data(data)


def verify_license(license_code: str = "") -> tuple[bool, str]:
    """
    验证授权码
    支持两种输入：
      1. license_code 参数直接传入授权码字符串
      2. 从 data/license.key 文件读取（兼容旧格式）
    返回: (是否授权, 消息)
    """
    machine_code = generate_machine_code()
    normalized_machine = _normalize_machine_code(machine_code)

    # 方式1：直接传入授权码
    if license_code:
        data, err = _decrypt_data(license_code)
        if err:
            return False, err

        # 解析数据：machine_code|expires_at 或 machine_code
        parts = data.split("|", 1)
        code_in_license = parts[0]
        expires_at = parts[1] if len(parts) > 1 else ""

        if code_in_license != normalized_machine:
            return False, f"授权码与本机不匹配。\n当前机器码: {machine_code}"

        if not expires_at:
            return True, "授权验证通过（永久有效）"

        return _check_expiry(expires_at)

    # 方式2：从文件读取（兼容旧格式）
    license_dir = Path(__file__).resolve().parent / "data"
    license_file = license_dir / "license.key"
    if license_file.exists():
        try:
            with open(license_file, "r", encoding="utf-8") as f:
                license_data = json.load(f)
            authorized_machine = license_data.get("machine_code", "")
            if not authorized_machine:
                return False, "授权文件格式错误"
            if _normalize_machine_code(authorized_machine) != normalized_machine:
                return False, f"授权不匹配。当前机器码: {machine_code}"
            expires_at = license_data.get("expires_at", "")
            if expires_at:
                return _check_expiry(expires_at)
            return True, "授权验证通过（旧版文件格式）"
        except Exception:
            pass

    return False, f"未授权。您的机器码: {machine_code}\n请将机器码发给开发者获取授权码。"


def _check_expiry(expires_at: str) -> tuple[bool, str]:
    """检查过期时间，返回 (是否有效, 消息)"""
    try:
        if " " in expires_at:
            expire_dt = datetime.strptime(expires_at, "%Y-%m-%d %H:%M")
            now = datetime.now()
            if now > expire_dt:
                return False, f"授权已过期（{expires_at}），请联系开发者续期。"
            remaining = expire_dt - now
            days = remaining.days
            hours = remaining.seconds // 3600
            if days > 0:
                msg = f"授权验证通过，有效期至 {expires_at}（剩余 {days} 天 {hours} 小时）"
            else:
                msg = f"授权验证通过，有效期至 {expires_at}（剩余 {hours} 小时）"
        else:
            expire_date = datetime.strptime(expires_at, "%Y-%m-%d").date()
            today = date.today()
            if today > expire_date:
                return False, f"授权已过期（{expires_at}），请联系开发者续期。"
            days_left = (expire_date - today).days
            msg = f"授权验证通过，有效期至 {expires_at}（剩余 {days_left} 天）"
        return True, msg
    except ValueError:
        return False, f"授权日期格式错误: {expires_at}"


def create_license_file(machine_code: str, output_dir: Optional[Path] = None,
                        expires_at: Optional[str] = None) -> Path:
    """
    创建授权文件（兼容模式，推荐改用 generate_license_code 生成授权码）
    """
    if output_dir is None:
        output_dir = Path(__file__).resolve().parent / "data"
    output_dir.mkdir(parents=True, exist_ok=True)
    license_file = output_dir / "license.key"
    license_data = {
        "machine_code": machine_code.upper(),
        "issued_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "version": LICENSE_VERSION
    }
    if expires_at:
        license_data["expires_at"] = expires_at
    with open(license_file, "w", encoding="utf-8") as f:
        json.dump(license_data, f, ensure_ascii=False, indent=2)
    return license_file
