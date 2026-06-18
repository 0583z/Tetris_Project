@echo off
title 俄罗斯方块对战服务器
echo ================================
echo   俄罗斯方块 - 对战服务器
echo ================================
echo.
echo 服务器启动后，请将本机IP告诉好友
echo 本机IP地址：
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do echo   %%a
echo.
echo ================================
echo.
TetrisServer.exe
pause
