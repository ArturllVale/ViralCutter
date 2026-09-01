@echo off
setlocal
title ViralCutter CLI

cd /d "%~dp0"

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo AVISO: Ambiente virtual .venv nao encontrado.
    echo Execute install_dependencies.bat primeiro se encontrar problemas.
    echo Tentando executar com o Python do sistema...
)

python main_improved.py
echo.
pause