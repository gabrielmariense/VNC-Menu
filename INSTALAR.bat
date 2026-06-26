@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo ==========================================
echo  INSTALADOR - VNC-Menu
echo ==========================================
echo.

set "PY_CMD="

echo [1/4] Verificando Python...

py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    goto PY_FOUND
)

python --version >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=python"
    goto PY_FOUND
)

echo Python nao encontrado.
echo Tentando instalar Python pelo winget...
echo.

winget --version >nul 2>&1
if not %errorlevel%==0 (
    echo ERRO: winget nao encontrado.
    echo Instale o Python manualmente e execute este arquivo novamente:
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements

echo.
echo Revalidando Python...

py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=py -3"
    goto PY_FOUND
)

python --version >nul 2>&1
if %errorlevel%==0 (
    set "PY_CMD=python"
    goto PY_FOUND
)

echo.
echo ERRO: Python foi instalado, mas ainda nao foi encontrado neste terminal.
echo Feche esta janela, abra novamente o INSTALAR.bat e tente de novo.
echo.
pause
exit /b 1

:PY_FOUND
echo Python encontrado usando: %PY_CMD%
%PY_CMD% --version
echo.

echo [2/4] Atualizando pip...
%PY_CMD% -m ensurepip --upgrade >nul 2>&1
%PY_CMD% -m pip install --upgrade pip
if not %errorlevel%==0 (
    echo.
    echo ERRO: falha ao atualizar o pip.
    pause
    exit /b 1
)

echo.
echo [3/4] Instalando requirements.txt...
if not exist "requirements.txt" (
    echo ERRO: requirements.txt nao encontrado na pasta atual.
    echo Pasta atual: %CD%
    pause
    exit /b 1
)

%PY_CMD% -m pip install -r requirements.txt
if not %errorlevel%==0 (
    echo.
    echo ERRO: falha ao instalar dependencias.
    pause
    exit /b 1
)

echo.
echo [4/4] Validando instalacao...
%PY_CMD% -c "import pywinauto; import PyInstaller; import win32api; import comtypes; print('Dependencias OK')"
if not %errorlevel%==0 (
    echo.
    echo ERRO: alguma dependencia nao foi importada corretamente.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Instalacao finalizada com sucesso.
echo ==========================================
echo.
pause
exit /b 0
