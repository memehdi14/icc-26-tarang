@echo off
setlocal EnableExtensions
rem ============================================================
rem  Tarang dashboard - TV demo launcher (Windows)
rem  Opens the dashboard fullscreen at a uniform device scale so
rem  every element grows equally on a TV. Same mechanism the Pi
rem  kiosk uses: --force-device-scale-factor.
rem
rem  Usage: start_tv_demo.bat [url] [scale]
rem    url    default http://localhost:3000
rem    scale  default 2.0  (1080p: 2.0 compact-big / 1.75 desktop,
rem                         4K: 2.5-3.0)
rem ============================================================

set "URL=%~1"
set "SCALE=%~2"

if /i "%URL%"=="--help" goto :usage
if /i "%URL%"=="-h" goto :usage
if "%URL%"=="" set "URL=http://localhost:3000"
if "%SCALE%"=="" set "SCALE=2.0"

echo %SCALE%| findstr /r "^[0-9][0-9.]*$" >nul
if errorlevel 1 set "SCALE=2.0"

rem -- Find a Chromium browser: Chrome first, then Edge ----------
set "BROWSER="
for %%P in ("%ProgramFiles%\Google\Chrome\Application\chrome.exe" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" "%LocalAppData%\Google\Chrome\Application\chrome.exe") do (
  if not defined BROWSER if exist "%%~P" set "BROWSER=%%~P"
)
for %%P in ("%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe") do (
  if not defined BROWSER if exist "%%~P" set "BROWSER=%%~P"
)

if not defined BROWSER (
  echo [ERROR] Neither Google Chrome nor Microsoft Edge was found.
  echo         Install Chrome, or set BROWSER in this script to your browser path.
  exit /b 1
)

rem -- Fresh profile dir so the scale flags are honored even if a
rem    normal browser window is already running ------------------
set "PROFILE=%TEMP%\tarang_tv_demo_profile"

echo Tarang TV demo launcher
echo   Browser : %BROWSER%
echo   URL     : %URL%
echo   Scale   : %SCALE%   ^(2.0 compact-big, 1.75 desktop layout, 2.5-3.0 for 4K^)
echo   Profile : %PROFILE%
echo.

start "" "%BROWSER%" --app="%URL%" --start-fullscreen --window-size=1920,1080 --force-device-scale-factor=%SCALE% --autoplay-policy=no-user-gesture-required --no-first-run --no-default-browser-check --user-data-dir="%PROFILE%"

echo Launched. If the window opened on the laptop screen, move it with
echo Win+Shift+Arrow, then press F11 for fullscreen.
exit /b 0

:usage
echo Starts the Tarang dashboard fullscreen on a TV with uniform scaling.
echo.
echo Usage: %~nx0 [url] [scale]
echo   url    Dashboard URL. Default: http://localhost:3000
echo   scale  Device scale factor. Default: 2.0
echo.
echo Examples:
echo   %~nx0
echo   %~nx0 http://localhost:3000 1.75
echo   %~nx0 http://192.168.1.50:3000 2.5
echo.
echo Tips:
echo   1080p TV: 2.0 = compact kiosk layout at 2x (recommended),
echo             1.75 = full desktop layout with patient rail
echo   4K TV:    2.5 - 3.0
echo   Manual fallback: F11 then Ctrl+Plus to 200%%
exit /b 0
