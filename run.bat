@echo off
title Host

:: Launch main.py in a new terminal
start "Host - A" cmd /k "cd /d d:\Hardik_file\Projects\Ai-projects\labelbox-feedback-mul && call venv\Scripts\activate && python autoeval\main.py"

:: Launch mouse_movement.py in a new terminal
start "Host - B" cmd /k "cd /d d:\Hardik_file\Projects\Ai-projects\labelbox-feedback-mul && call venv\Scripts\activate && python evaluation\mouse_movement.py"

echo Both scripts launched in separate terminals.
