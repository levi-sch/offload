@echo off
rem Zet Offload in de Opstarten-map: het draait dan na elke login op de achtergrond
rem en opent het dashboard zodra je een SD-kaart insteekt.
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Offload.lnk'); $s.TargetPath=(Get-Command pythonw).Source; $s.Arguments='\"%~dp0app.py\"'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0brand\offload.ico'; $s.Save()"
echo Offload start nu automatisch bij het inloggen.
start "" pythonw "%~dp0app.py" --open
pause
