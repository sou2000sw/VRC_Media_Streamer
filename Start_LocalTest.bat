@echo off
cd /d "%~dp0"
echo Starting VRC_Media_Streamer in Local Test Mode (No Tunnel)...
python gui_streamer.py --no-tunnel
pause
