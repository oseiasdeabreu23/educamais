@echo off
REM ====================================================================
REM Script para iniciar o EducaMais automaticamente
REM Ativa venv, instala dependências, migra banco e executa o servidor
REM ====================================================================

cd /d "%~dp0"

echo.
echo ====== INICIALIZANDO EDUCAMAIS ======
echo.

REM 1. Ativar ambiente virtual
echo [1/5] Ativando ambiente virtual...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo ERRO: Falha ao ativar o ambiente virtual.
    pause
    exit /b 1
)
echo OK - Ambiente virtual ativado.
echo.

REM 2. Instalar dependências
echo [2/5] Instalando dependências (pode levar alguns minutos)...
pip install -r requirements.txt > nul 2>&1
if errorlevel 1 (
    echo AVISO: Verificar se pip funcionou corretamente.
)
echo OK - Dependências instaladas.
echo.

REM 3. Inicializar/migrar banco
echo [3/5] Migrando banco de dados...
python -m flask db upgrade
if errorlevel 1 (
    echo ERRO: Falha ao migrar banco de dados.
    pause
    exit /b 1
)
echo OK - Banco de dados migrado.
echo.

REM 4. Seed de dados (opcional)
echo [4/5] Carregar dados de exemplo?
echo Digite S para carregar seed_data.py, ou qualquer outra tecla para pular
set /p SEED="Opcao (S/N): "
if /i "%SEED%"=="S" (
    set PYTHONPATH=.
    python scripts\seed_data.py
    if errorlevel 1 (
        echo AVISO: Seed opcional nao executou. Continuando...
    ) else (
        echo OK - Dados de exemplo carregados.
    )
) else (
    echo Pulando seed de dados.
)
echo.

REM 5. Rodar servidor
echo [5/5] Iniciando servidor Flask...
echo.
echo ====== SERVIDOR INICIADO ======
echo Acesse: http://127.0.0.1:5555/login
echo.
echo Contas de teste:
echo   admin@escola.com / admin123
echo   prof@escola.com / prof123
echo   resp@escola.com / resp123
echo   aluno@escola.com / aluno123
echo.
echo Pressione CTRL+C para parar o servidor.
echo.

python run.py

REM Quando o servidor encerrar
pause
echo.
echo EducaMais encerrado.
