@echo off
setlocal

set "ROOT_DIR=%~dp0"
call "%ROOT_DIR%scripts\start_server.bat"
exit /b %errorlevel%
