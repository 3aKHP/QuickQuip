@echo off
chcp 65001 >nul
title QuickQuip

:: Resolve script directory
cd /d "%~dp0"

:: ── First-run: copy config examples ──────────────────────────────────────
if not exist "config\llm.toml" (
    echo [首次运行] 复制 config\llm.toml.example -^> config\llm.toml
    copy "config\llm.toml.example" "config\llm.toml" >nul
)
if not exist "config\chat_rules.toml" (
    echo [首次运行] 复制 config\chat_rules.toml.example -^> config\chat_rules.toml
    copy "config\chat_rules.toml.example" "config\chat_rules.toml" >nul
)
if not exist "config\generation.toml" (
    echo [首次运行] 复制 config\generation.toml.example -^> config\generation.toml
    copy "config\generation.toml.example" "config\generation.toml" >nul
)
:: Optional: copy llm_about templates for group identity & vocab features
if not exist "llm_about\vocab.yaml" (
    if exist "llm_about\vocab.yaml.example" (
        echo [首次运行] 复制 llm_about\vocab.yaml.example -^> llm_about\vocab.yaml
        copy "llm_about\vocab.yaml.example" "llm_about\vocab.yaml" >nul
    )
)
if not exist "llm_about\identities.yaml" (
    if exist "llm_about\identities.yaml.example" (
        echo [首次运行] 复制 llm_about\identities.yaml.example -^> llm_about\identities.yaml
        copy "llm_about\identities.yaml.example" "llm_about\identities.yaml" >nul
    )
)

:: ── Resolve Python ───────────────────────────────────────────────────────
set "_PYTHON="
if exist ".\python\pythonw.exe" (
    :: Embedded Python from lazy package
    set "_PYTHON=.\python\python.exe"
    set "_PYTHONW=.\python\pythonw.exe"
) else (
    :: Fallback to system Python
    set "_PYTHON=python"
    set "_PYTHONW=pythonw"
)

:: ── Start admin panel (hidden window) ────────────────────────────────────
echo 正在启动管理后台...
start "QuickQuip Admin" /MIN "%_PYTHONW%" web_api.py

:: Wait for admin to bind port
echo 等待管理后台就绪...
:wait_admin
"%_PYTHON%" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5104/ops/api/auth/me', timeout=1)" >nul 2>&1
if errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait_admin
)

:: ── Open browser ─────────────────────────────────────────────────────────
start http://127.0.0.1:5104/ops

:: ── Start bot ────────────────────────────────────────────────────────────
echo 正在启动 QQ Bot...
"%_PYTHON%" bot.py

pause
