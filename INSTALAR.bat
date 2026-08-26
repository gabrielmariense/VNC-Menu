@echo off
setlocal EnableExtensions

cd /d "%~dp0"

echo ==========================================
echo  INSTALADOR - VNC-Menu
echo ==========================================
echo.

rem ---------------------------------------------------------------------
rem  [1/5] Conferir a pasta ANTES de instalar qualquer coisa.
rem  Nao faz sentido instalar Python para depois descobrir que o .bat esta
rem  no lugar errado.
rem ---------------------------------------------------------------------
echo [1/5] Verificando a pasta do projeto...

if not exist "requirements.txt" goto WRONG_FOLDER
if not exist "VNC-Menu.pyw" goto WRONG_FOLDER
echo       OK: %CD%
echo.

rem ---------------------------------------------------------------------
rem  [2/5] Python
rem ---------------------------------------------------------------------
echo [2/5] Verificando Python...

call :FIND_PYTHON
if defined PY_CMD goto PY_FOUND

echo       Python nao encontrado. Tentando instalar pelo winget...
echo.

winget --version >nul 2>&1
if errorlevel 1 (
    echo ERRO: winget nao encontrado nesta maquina.
    echo Instale o Python manualmente e rode este arquivo de novo:
    echo https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements

echo.
echo       Recarregando as variaveis de ambiente...

rem  AQUI estava o problema de "rodar duas vezes": o winget grava o novo PATH
rem  no registro, mas esta janela do cmd carrega uma COPIA do ambiente feita
rem  quando ela abriu. Por isso o py/python continuava "nao encontrado" ate
rem  fechar e abrir de novo. Reler o PATH do registro resolve sem reabrir.
call :REFRESH_PATH
call :FIND_PYTHON
if defined PY_CMD goto PY_FOUND

rem  Se mesmo assim nao apareceu, procura direto nos caminhos onde o
rem  instalador do Python costuma colocar os arquivos.
echo       Procurando o Python nas pastas padrao...
call :FIND_PYTHON_ON_DISK
if defined PY_CMD goto PY_FOUND

echo.
echo ERRO: o Python foi instalado, mas nao consegui localiza-lo.
echo Feche esta janela, abra o INSTALAR.bat novamente e ele deve encontrar.
echo Se continuar falhando, reinicie o computador e tente mais uma vez.
echo.
pause
exit /b 1

:PY_FOUND
echo       Usando: %PY_CMD%
%PY_CMD% --version
echo.

rem ---------------------------------------------------------------------
rem  [3/5] pip
rem ---------------------------------------------------------------------
echo [3/5] Preparando o pip...
%PY_CMD% -m ensurepip --upgrade >nul 2>&1
%PY_CMD% -m pip install --upgrade pip >nul 2>&1
if errorlevel 1 (
    rem  Nao e fatal: um pip mais antigo instala as dependencias do mesmo
    rem  jeito. So avisa e segue.
    echo       AVISO: nao consegui atualizar o pip. Seguindo assim mesmo.
) else (
    echo       OK
)
echo.

rem ---------------------------------------------------------------------
rem  [4/5] Dependencias
rem ---------------------------------------------------------------------
echo [4/5] Instalando as dependencias...
%PY_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto RETRY_USER
goto DEPS_OK

:RETRY_USER
echo.
echo       Falhou. Tentando instalar apenas para este usuario...
echo.
%PY_CMD% -m pip install --user -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERRO: nao foi possivel instalar as dependencias.
    echo Verifique a conexao com a internet e, se a rede exigir proxy,
    echo configure-o antes de tentar de novo.
    echo.
    pause
    exit /b 1
)

:DEPS_OK
echo.

rem ---------------------------------------------------------------------
rem  [5/5] Validacao
rem ---------------------------------------------------------------------
echo [5/5] Validando...
%PY_CMD% -c "import customtkinter, pywinauto, win32api, comtypes; print('      Dependencias OK')"
if errorlevel 1 (
    echo.
    echo ERRO: alguma dependencia nao foi importada corretamente.
    echo Rode o INSTALAR.bat novamente; se persistir, envie a mensagem acima.
    echo.
    pause
    exit /b 1
)

echo.
echo ==========================================
echo  Instalacao finalizada com sucesso.
echo ==========================================
echo.
echo Para abrir o programa, de duplo clique em VNC-Menu.pyw
echo.
pause
exit /b 0


:WRONG_FOLDER
echo.
echo ERRO: este arquivo precisa estar na raiz do projeto, ao lado de
echo VNC-Menu.pyw e requirements.txt.
echo.
echo Pasta atual: %CD%
echo.
pause
exit /b 1


rem =====================================================================
rem  Sub-rotinas
rem =====================================================================

:FIND_PYTHON
rem  Define PY_CMD se o Python estiver acessivel pelo PATH atual.
set "PY_CMD="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "PY_CMD=py -3"
    goto :eof
)
python --version >nul 2>&1
if errorlevel 1 goto :eof
rem  O "python.exe" da Microsoft Store e um atalho que abre a loja: responde
rem  ao --version mas nao executa nada. Este teste separa um do outro.
python -c "import sys; sys.exit(0)" >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"
goto :eof


:REFRESH_PATH
rem  Rele o PATH do registro (maquina + usuario) para dentro desta janela.
rem  O "call set" faz uma segunda expansao, necessaria porque o valor no
rem  registro e REG_EXPAND_SZ e chega com coisas como %SystemRoot% literais.
set "REG_SYSPATH="
set "REG_USERPATH="
for /f "usebackq tokens=2,*" %%A in (`reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul`) do set "REG_SYSPATH=%%B"
for /f "usebackq tokens=2,*" %%A in (`reg query "HKCU\Environment" /v Path 2^>nul`) do set "REG_USERPATH=%%B"
if defined REG_SYSPATH call set "PATH=%%REG_SYSPATH%%"
if defined REG_USERPATH call set "PATH=%PATH%;%%REG_USERPATH%%"
goto :eof


:FIND_PYTHON_ON_DISK
rem  Ultimo recurso: procurar os executaveis onde o instalador os coloca,
rem  sem depender de PATH nenhum.
set "PY_CMD="
if exist "%LocalAppData%\Programs\Python\Launcher\py.exe" (
    set "PY_CMD="%LocalAppData%\Programs\Python\Launcher\py.exe" -3"
    goto :eof
)
if exist "%WINDIR%\py.exe" (
    set "PY_CMD="%WINDIR%\py.exe" -3"
    goto :eof
)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%~D\python.exe" set "PY_CMD="%%~D\python.exe""
)
if defined PY_CMD goto :eof
for /d %%D in ("%ProgramFiles%\Python3*") do (
    if exist "%%~D\python.exe" set "PY_CMD="%%~D\python.exe""
)
if defined PY_CMD goto :eof
for /d %%D in ("%ProgramFiles(x86)%\Python3*") do (
    if exist "%%~D\python.exe" set "PY_CMD="%%~D\python.exe""
)
goto :eof
