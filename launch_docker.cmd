@echo off
REM Pull the latest published WordLLMs image and launch it.
REM Profile data lives on the host so it survives image updates and restarts.
REM Override the host folder by setting WORDLLMS_HOST_DIR before running.
if "%WORDLLMS_HOST_DIR%"=="" set "WORDLLMS_HOST_DIR=%USERPROFILE%\Documents\WordLLMs"
if not exist "%WORDLLMS_HOST_DIR%" mkdir "%WORDLLMS_HOST_DIR%"

docker pull kauttoj/wordllms
docker stop wordllms 2>nul
docker rm wordllms 2>nul
docker run -d --name wordllms -p 3000:8000 ^
  -v "%WORDLLMS_HOST_DIR%:/app/data" ^
  -e "WORDLLMS_HOST_PATH=%WORDLLMS_HOST_DIR%" ^
  kauttoj/wordllms
echo Profile data on host: %WORDLLMS_HOST_DIR%
echo Open Word and load the add-in; backend is on http://localhost:3000
