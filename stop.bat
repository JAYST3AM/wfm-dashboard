@echo off
for /f "tokens=5" %%p in ('netstat -ano ^| findstr :8787 ^| findstr LISTENING') do taskkill /F /PID %%p
echo WFM Trader stopped (if it was running).
