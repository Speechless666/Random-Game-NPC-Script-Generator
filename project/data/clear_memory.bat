@echo off
chcp 65001 >nul
echo ========================================
echo 长期记忆文件清理工具
echo ========================================

:: 设置文件路径
set "FILE_PATH=memory_longterm.csv"

:: 检查文件是否存在
if exist "%FILE_PATH%" (
    echo 找到长期记忆文件: %FILE_PATH%
    
    :: 备份原文件（可选）
    set "BACKUP_PATH=.cache\memory_longterm_backup_%date:~0,4%%date:~5,2%%date:~8,2%.csv"
    copy "%FILE_PATH%" "%BACKUP_PATH%" >nul
    echo 已创建备份: %BACKUP_PATH%
    
    :: 删除原文件
    del "%FILE_PATH%"
    echo 🗑️ 已清空长期记忆文件
    
    :: 重新创建空的CSV文件（带表头）
    echo player_id,npc_id,fact,emotion,timestamp > "%FILE_PATH%"
    echo 已重新创建空白的长期记忆文件（含表头）
) else (
    echo 长期记忆文件不存在: %FILE_PATH%
    echo 将创建新的长期记忆文件...
    
    :: 确保目录存在
    if not exist ".cache\data" mkdir ".cache\data"
    
    :: 创建新的CSV文件（带表头）
    echo player_id,npc_id,fact,emotion,timestamp > "%FILE_PATH%"
    echo ✅ 已创建新的长期记忆文件
)

echo.
echo 操作完成！
echo ========================================
pause