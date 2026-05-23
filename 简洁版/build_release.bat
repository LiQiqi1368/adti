@echo off
chcp 65001 >nul

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

set "DIST_DIR=%PROJECT_DIR%\dist\答题助手"
set "SPEC_FILE=%PROJECT_DIR%\build_release.spec"
set "LICENSE_SPEC=%PROJECT_DIR%\build_license_tool.spec"
set "SOURCE_DB=%PROJECT_DIR%\data\question_bank.db"
set "TARGET_DB_DIR=%DIST_DIR%\data"
set "TARGET_BROWSERS_DIR=%DIST_DIR%\playwright_browsers"
set "MS_PLAYWRIGHT=%USERPROFILE%\AppData\Local\ms-playwright"

echo ========================================
echo 打包 Windows 发布版
echo 项目目录: %PROJECT_DIR%
echo ========================================

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 python
    pause
    exit /b 1
)

if not exist "%SPEC_FILE%" (
    echo [错误] 未找到 spec 文件: %SPEC_FILE%
    pause
    exit /b 1
)

echo [1/5] 检查 PyInstaller...
python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo 正在安装 PyInstaller...
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [错误] 安装失败
        pause
        exit /b 1
    )
)

echo [2/5] 打包主程序...
python -m PyInstaller --noconfirm --clean "%SPEC_FILE%"
if errorlevel 1 (
    echo [错误] 主程序打包失败
    pause
    exit /b 1
)

echo [3/5] 打包授权工具...
python -m PyInstaller --noconfirm --clean "%LICENSE_SPEC%"
if errorlevel 1 (
    echo [警告] 授权工具打包失败，主程序不受影响
)

if not exist "%DIST_DIR%" (
    echo [错误] 输出目录不存在
    pause
    exit /b 1
)

echo [4/5] 复制数据库文件...
if not exist "%TARGET_DB_DIR%" mkdir "%TARGET_DB_DIR%"
if exist "%SOURCE_DB%" (
    copy /Y "%SOURCE_DB%" "%TARGET_DB_DIR%\question_bank.db" >nul
) else (
    echo 未找到数据库文件，首次运行自动创建。
)

echo [5/5] 复制 Playwright 浏览器资源...
if not exist "%TARGET_BROWSERS_DIR%" mkdir "%TARGET_BROWSERS_DIR%"
if exist "%MS_PLAYWRIGHT%" (
    echo 复制浏览器资源...
    xcopy "%MS_PLAYWRIGHT%\*" "%TARGET_BROWSERS_DIR%\" /E /I /Y >nul
    if errorlevel 1 (
        echo [警告] 浏览器资源复制不完整，请手动检查
    ) else (
        echo 浏览器资源复制完成
    )
) else (
    echo [警告] 未找到本机 Playwright 浏览器
    echo 请先执行: python -m playwright install chromium
    echo 然后重新运行此脚本
)

echo.
echo ===== 打包完成 =====
echo 发布目录: %DIST_DIR%
echo 授权工具: %PROJECT_DIR%\dist\授权码生成工具
echo.
echo 将"答题助手"文件夹压缩后发给用户
echo.
pause
