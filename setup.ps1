# Immersion Tracker — one-command setup (Windows)
#   git clone … ; cd immersion-tracker ; .\setup.ps1
#   .\setup.ps1 -Wizard          # core + guided Tadoku/Plex/GSM/Hoshi
#   .\scripts\setup-wizard.ps1   # features only (app already running)
& "$PSScriptRoot\scripts\docker\setup.ps1" @args
