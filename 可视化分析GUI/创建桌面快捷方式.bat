@echo off
chcp 65001 >nul
echo 正在创建桌面快捷方式...
powershell -NoProfile -Command "$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut('$env:USERPROFILE\Desktop\光谱可视化分析工具.lnk'); $sc.TargetPath='C:\Python311\pythonw.exe'; $sc.Arguments='launch_hidden.py'; $sc.WorkingDirectory='%~dp0'; $sc.Save()"
if errorlevel 1 (
  echo [失败] 无法写入桌面，请手动复制 光谱可视化分析工具.lnk 到桌面
) else (
  echo [成功] 已创建桌面快捷方式
)
pause
