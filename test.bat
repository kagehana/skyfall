@echo off
cd /d "%~dp0"
py -3.13 -m pytest tests/ -v %*
