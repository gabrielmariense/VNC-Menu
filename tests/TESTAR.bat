@echo off
setlocal EnableExtensions

rem Este arquivo vive dentro de tests\, mas o unittest precisa rodar a partir
rem da RAIZ do projeto (a pasta que CONTEM tests\). Subir um nivel resolve
rem isso, independente de onde o duplo clique aconteceu.
cd /d "%~dp0.."

echo ==========================================
echo  TESTES - VNC-Menu
echo ==========================================
echo.

if not exist "tests\test_vncmenu.py" (
    echo ERRO: nao encontrei tests\test_vncmenu.py
    echo.
    echo Este arquivo precisa estar dentro da pasta tests\, que por sua vez
    echo fica na raiz do projeto, ao lado de VNC-Menu.pyw.
    echo.
    echo Pasta atual: %CD%
    echo.
    pause
    exit /b 1
)

set "PY_CMD="

py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto PY_FOUND
)

python --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=python"
    goto PY_FOUND
)

echo ERRO: Python nao encontrado.
echo Execute o INSTALAR.bat primeiro.
echo.
pause
exit /b 1

:PY_FOUND
echo Usando: %PY_CMD%
%PY_CMD% --version
echo.
echo Os testes rodam em uma pasta temporaria propria.
echo Nada em Documents\VNC-Menu ou em data\ e alterado.
echo.

%PY_CMD% -m unittest discover -s tests -v
set "RESULT=%errorlevel%"

echo.
if "%RESULT%"=="0" (
    echo ==========================================
    echo  TODOS OS TESTES PASSARAM.
    echo ==========================================
    echo  Esperado: 117 testes, 1 skip.
) else (
    echo ==========================================
    echo  ALGUM TESTE FALHOU. Veja a saida acima.
    echo ==========================================
)

echo.
pause
exit /b %RESULT%
