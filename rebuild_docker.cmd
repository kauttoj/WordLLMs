@echo off
REM Mount the container's profile folder onto the host user's Documents folder
REM so conversations + settings live somewhere the user can actually find.
REM Override by setting WORDLLMS_HOST_DIR before running this script.
if "%WORDLLMS_HOST_DIR%"=="" set "WORDLLMS_HOST_DIR=%USERPROFILE%\Documents\WordLLMs"
if not exist "%WORDLLMS_HOST_DIR%" mkdir "%WORDLLMS_HOST_DIR%"

docker build -t kauttoj/wordllms .
docker stop wordllms 2>nul
docker rm wordllms 2>nul
docker run -d --name wordllms -p 3000:8000 ^
  -v "%WORDLLMS_HOST_DIR%:/app/data" ^
  -e "WORDLLMS_HOST_PATH=%WORDLLMS_HOST_DIR%" ^
  kauttoj/wordllms

docker image prune -f

echo Profile data on host: %WORDLLMS_HOST_DIR%
