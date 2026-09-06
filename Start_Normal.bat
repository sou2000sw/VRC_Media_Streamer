@echo off
cd /d "%~dp0"
echo Starting VRC_Media_Streamer (Normal Mode - Tunnel Enabled)...
python gui_streamer.py --tunnel
pause
