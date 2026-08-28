@echo off
chcp 65001 >nul
setlocal
title QuickQuip

cd /d "%~dp0"

if not exist "data" mkdir "data"

set "_ENV_CREATED=0"
call :copy_env_if_missing ".env.example" ".env"
call :copy_if_missing "config\llm.toml.example" "config\llm.toml"
call :copy_if_missing "config\chat_rules.toml.example" "config\chat_rules.toml"
call :copy_if_missing "config\generation.toml.example" "config\generation.toml"
call :copy_if_missing "config\games.toml.example" "config\games.toml"
call :copy_if_missing "config\awakening.toml.example" "config\awakening.toml"
call :copy_if_missing "config\sensitive_words.toml.example" "config\sensitive_words.toml"
call :copy_if_missing "config\niuniu_text.toml.example" "config\niuniu_text.toml"
call :copy_if_missing "config\niuniu_text_safe.toml.example" "config\niuniu_text_safe.toml"
if not exist "config\personas" (
    if exist "config\personas.example" (
        echo [First run] Copy config\personas.example -^> config\personas
        xcopy "config\personas.example" "config\personas\" /E /I /Q /Y >nul
    ) else (
        echo [WARNING] Missing config\personas.example, skipping personas copy
    )
)
call :copy_if_missing "llm_about\vocab.yaml.example" "llm_about\vocab.yaml"
call :copy_if_missing "llm_about\identities.yaml.example" "llm_about\identities.yaml"

if "%_ENV_CREATED%"=="1" (
    echo.
    echo First-run files were created.
    echo Edit .env, then run start.bat again.
    pause
    exit /b
)

set "_PYTHON="
if exist ".\python\pythonw.exe" (
    set "_PYTHON=.\python\python.exe"
    set "_PYTHONW=.\python\pythonw.exe"
    set "PLAYWRIGHT_BROWSERS_PATH=0"
) else (
    set "_PYTHON=python"
    set "_PYTHONW=pythonw"
)

echo Starting Web Admin...
start "QuickQuip Admin" /MIN "%_PYTHONW%" web_api.py

echo Opening Web Admin...
start "QuickQuip Admin Window" "%_PYTHONW%" webview_launcher.py

echo Starting QQ Bot...
"%_PYTHON%" bot.py

pause
exit /b

:copy_if_missing
if not exist "%~2" (
    if exist "%~1" (
        echo [First run] Copy %~1 -^> %~2
        copy "%~1" "%~2" >nul
    ) else (
        echo [WARNING] Missing template %~1, skipping %~2
    )
)
exit /b

:copy_env_if_missing
if not exist "%~2" (
    if exist "%~1" (
        echo [First run] Copy %~1 -^> %~2
        copy "%~1" "%~2" >nul
        set "_ENV_CREATED=1"
    ) else (
        echo [WARNING] Missing template %~1, skipping %~2
    )
)
exit /b
