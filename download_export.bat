@echo off
REM Auto-generated SCP download script
REM Run this from your Windows laptop to download the export file

echo ========================================
echo Transferring export file to Windows...
echo ========================================
echo.
echo Command: scp bent-christiansen@100.93.207.76:/tmp/job_search_automation_export_20260124_155735.zip "%USERPROFILE%\Downloads\job_search_automation_export_20260124_155735.zip"
echo.

scp bent-christiansen@100.93.207.76:/tmp/job_search_automation_export_20260124_155735.zip "%USERPROFILE%\Downloads\job_search_automation_export_20260124_155735.zip"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo ✅ File downloaded successfully!
    echo ========================================
    echo.
    echo 📁 File saved to: %USERPROFILE%\Downloads\job_search_automation_export_20260124_155735.zip
    echo.
    echo Opening Downloads folder...
    start "" "%USERPROFILE%\Downloads"
) else (
    echo.
    echo ========================================
    echo ❌ Download failed
    echo ========================================
    echo.
    echo Please check:
    echo   1. You can SSH into the remote server
    echo   2. The remote file exists
    echo   3. You have write permissions to Downloads folder
    echo.
)

pause
