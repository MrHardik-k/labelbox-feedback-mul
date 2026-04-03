@echo off
echo Starting data extraction...
python extact_ids_html.py
if %errorlevel% neq 0 (
    echo extact_ids_html.py encountered an error! Stopping.
    pause
    exit /b %errorlevel%
)

echo Starting task correlation...
python correlate_tasks.py
if %errorlevel% neq 0 (
    echo correlate_tasks.py encountered an error! Stopping.
    pause
    exit /b %errorlevel%
)

echo Launching dashboard...
call start_dashboard.bat

echo Sequence complete!
pause