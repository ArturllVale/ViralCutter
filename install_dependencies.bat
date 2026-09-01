@echo off
setlocal
cd /d "%~dp0"

echo ==========================================
echo Instalando/Atualizando uv (Gerenciador de pacotes Python)...
echo ==========================================
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

:: Adiciona locais padrao do uv ao PATH da sessao atual
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

echo.
echo ==========================================
echo Criando ambiente virtual (.venv)...
echo ==========================================
uv venv .venv

echo.
echo ==========================================
echo CONFIGURACAO DE PLACA DE VIDEO
echo ==========================================
echo Qual e a sua Placa de Video?
echo [1] NVIDIA (Instala com aceleracao CUDA - Mais rapido)
echo [2] AMD / Nenhuma (Ou se nao souber - Instala versao normal)
set /p gpu_choice="Escolha (1/2): "

if "%gpu_choice%"=="1" (
    echo.
    echo Instalando PyTorch e ONNX para NVIDIA...
    uv pip install --python .venv torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cu124
    uv pip install --python .venv onnxruntime-gpu==1.20.1
) else (
    echo.
    echo Instalando PyTorch e ONNX para AMD/CPU...
    uv pip install --python .venv torch==2.5.1 torchvision==0.20.1 torchaudio==2.5.1 --index-url https://download.pytorch.org/whl/cpu
    uv pip install --python .venv onnxruntime==1.20.1
)

echo.
echo ==========================================
echo Instalando dependencias essenciais do requirements.txt...
echo (IAs em Nuvem / Sem Modelos Locais)
echo ==========================================
uv pip install --python .venv -r requirements.txt

echo.
echo ==========================================
echo Concluido! O ambiente .venv foi configurado com sucesso.
echo ==========================================
pause
