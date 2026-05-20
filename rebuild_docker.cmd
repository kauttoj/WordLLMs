@echo off
docker build -t kauttoj/wordllms .
docker run -d -p 3000:8000 -v "C:\temp\WordLLMs:/app/data" kauttoj/wordllms
