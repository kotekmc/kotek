@echo off
title Kotek Deployer
echo ===========================================
echo   MISE A JOUR DU SITE KOTEK (ATM10)
echo ===========================================

:: 1. Synchronisation des données du serveur Minecraft
echo [1/3] Recuperation des stats depuis le serveur...
python sync_atm10.py
if %errorlevel% neq 0 (
    echo Erreur lors de la synchronisation Python.
    pause
    exit /b
)

:: 2. Recuperation des changements distants (evite les erreurs de push)
echo [2/3] Verification des mises a jour sur GitHub...
git pull origin main --no-rebase

:: 3. Envoi des modifications (Code + Data)
echo [3/3] Envoi vers GitHub Pages...
git add .
git commit -m "Mise a jour auto : %date% %time%"
git push origin main

echo ===========================================
echo   TERMINE ! Le site sera a jour dans 1 min.
echo ===========================================
pause