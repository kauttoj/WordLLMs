@echo off
docker build -t kauttoj/wordllms .
docker stop wordllms 2>nul
docker rm wordllms 2>nul
docker run -d --name wordllms -p 3000:8000 -v "C:\temp\WordLLMs:/app/data" kauttoj/wordllms
