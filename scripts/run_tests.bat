@echo off
setlocal
set "ROOT_DIR=%~dp0.."
call "%ROOT_DIR%pytest.bat" %*
exit /b %errorlevel%
