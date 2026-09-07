@echo off
REM Servidores locais para testar o Dispensa Planejada (webapp)
cd /d "%~dp0"
start "" http://localhost:8080
start "Dispensa Planejada API" /D "%~dp0backend" cmd /k python -m uvicorn main:app --host 127.0.0.1 --port 8000
python -m http.server 8080
