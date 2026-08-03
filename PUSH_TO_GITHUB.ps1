param(
  [Parameter(Mandatory=$true)]
  [string]$RepoUrl
)
$ErrorActionPreference = "Stop"
Write-Host "Initializing CotatQ v1.3 repository..."
if (-not (Test-Path ".git")) { git init }
git add .
git commit -m "CotatQ v1.3 locked remote reproduction kit"
git branch -M main
git remote remove origin 2>$null
$LASTEXITCODE = 0
git remote add origin $RepoUrl
git push -u origin main
Write-Host "Done. Open the repository Actions tab and run CotatQ Remote STANDARD."
