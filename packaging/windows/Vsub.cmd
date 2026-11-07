@echo off
rem vsub cho Windows: lan dau cai Python + thu vien, tao shortcut, roi mo app.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0vsub.ps1" %*
