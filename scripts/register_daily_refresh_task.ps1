# 在 Windows「工作排程器」登記每天自動更新經濟部商工資料（python -m etl.daily_refresh）
#
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_refresh_task.ps1                  # 每天 06:00
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_refresh_task.ps1 -Time 07:30 -Python C:\path\to\.venv\Scripts\python.exe
#   powershell -ExecutionPolicy Bypass -File scripts\register_daily_refresh_task.ps1 -Remove          # 取消排程
#
# - 電腦在排定時間沒開機，開機後會補跑一次（StartWhenAvailable）
# - 執行紀錄附加在 data\logs\daily_refresh.log；每一步的結果另見 data\processed\_daily_refresh.json
# - 伺服器也設了 GCIS_DAILY_REFRESH=1 時不會重複跑（共用鎖檔）
param(
    [string]$Python = "python",
    [string]$Time = "06:00",
    [string]$TaskName = "GcisTalentRadarDailyRefresh",
    [switch]$Remove
)

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "已取消排程：$TaskName"
    return
}

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "data\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "daily_refresh.log"

$Command = "Set-Location '$Root'; `$env:PYTHONUTF8 = '1'; & '$Python' -m etl.daily_refresh *>> '$Log'"
$Action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -NonInteractive -Command `"$Command`""
$Trigger = New-ScheduledTaskTrigger -Daily -At $Time
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force `
    -Description "每天更新經濟部商工資料到 gcis-talent-radar 的資料庫（etl.daily_refresh）" | Out-Null
Write-Output "已登記排程：$TaskName，每天 $Time 執行；紀錄：$Log"
