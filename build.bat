@echo off
echo Installing tools (needs Python installed)...
pip install pyirsdk pyinstaller
echo Building the exe...
pyinstaller --onefile --name StintBoard --add-data "index.html;." server.py
echo.
echo Done. Your program is in the "dist" folder: StintBoard.exe
pause
