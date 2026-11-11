# Run Slot 0 and Slot 1 in separate PowerShell tabs for four Players total.
# This is an opt-in launcher. It does not attach to or modify an existing run.
param(
    [Parameter(Mandatory=$true)][ValidateSet(0,1)][int]$Slot,
    [ValidateRange(0.01,168)][double]$Hours = 10
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$tag = (Get-Date -Format 'yyyyMMdd_HHmmss') + '_' + [guid]::NewGuid().ToString('N').Substring(0,8)
$out = "outputs\overnight_slot${Slot}_$tag"
$profiles = "outputs\overnight_profiles_slot${Slot}_$tag.json"
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$exe = Join-Path $PSScriptRoot '..\Unity\Builds\SyncOptimized_03\SuikaGameAI.exe'
if (!(Test-Path -LiteralPath $exe) -or !(Test-Path -LiteralPath $python)) { throw 'Player or Python is missing' }
$null = New-Item -ItemType Directory -Path 'outputs' -Force
@(
    @{depth=4;iterations=128;weight=0.50},
    @{depth=4;iterations=256;weight=0.30},
    @{depth=4;iterations=512;weight=0.10},
    @{depth=6;iterations=256;weight=0.10}
) | ConvertTo-Json | Set-Content -LiteralPath $profiles -Encoding UTF8
$gameSeed = 900000000 + $Slot * 10000000 + (Get-Random -Minimum 0 -Maximum 8000000)
$port = 43000 + $Slot * 100
Write-Host "Slot $Slot : $out; seed=$gameSeed; port=$port; two Players; drain after $Hours hours"
& $python .\collect_overnight_mcts.py --exe $exe --output $out --workers 2 `
    --hours $Hours --shutdown drain --think-seconds 30 --communication-timeout 720 `
    --profiles $profiles --game-seed $gameSeed --schedule-seed 20261028 `
    --max-jobs 1000 --max-steps 100000 --base-port $port
exit $LASTEXITCODE
