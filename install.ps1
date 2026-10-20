<#
.SYNOPSIS
    Set up Jarvis on Windows 11 in one go: tools, Python packages, models, and config files.

.DESCRIPTION
    Run it from the project folder:

        powershell -ExecutionPolicy Bypass -File .\install.ps1

    It checks for uv and Ollama (and offers to install them with winget, asking first),
    installs Jarvis's Python packages (with GPU speech recognition when an NVIDIA GPU is
    present), downloads the models, creates config\local.toml and .env from their templates
    if they are missing, and downloads the speech models. Everything it does can be run again
    safely; steps that are already done are skipped.

    -DryRun only checks and reports, changing nothing.

.EXAMPLE
    .\install.ps1 -DryRun
    .\install.ps1
    .\install.ps1 -NoVoice -Model hermes3:3b
#>
[CmdletBinding()]
param(
    [switch]$DryRun,          # check and report only
    [switch]$NoVoice,         # skip the voice packages and speech models
    [switch]$NonInteractive,  # never prompt; system installs are then skipped
    [string]$Model = "hermes3:8b"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$script:Failed = 0
$script:Todo = New-Object System.Collections.Generic.List[string]

function Say([string]$Mark, [string]$Text) {
    $colors = @{ "ok" = "Green"; "todo" = "Yellow"; "skip" = "DarkGray"; "fail" = "Red"; ".." = "Cyan" }
    Write-Host ("[{0,-4}] " -f $Mark) -ForegroundColor $colors[$Mark] -NoNewline
    Write-Host $Text
}

function Ask([string]$Question) {
    if ($NonInteractive -or $DryRun) { return $false }
    $answer = Read-Host "$Question [y/N]"
    return $answer -match '^(y|yes)$'
}

function Have([string]$Command) {
    return [bool](Get-Command $Command -ErrorAction SilentlyContinue)
}

function Run([string]$What, [scriptblock]$Action) {
    if ($DryRun) { Say "todo" "would $What"; $script:Todo.Add($What); return }
    Say ".." $What
    & $Action
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        Say "fail" "$What (exit code $LASTEXITCODE)"
        $script:Failed++
    }
}

function Ensure-Tool([string]$Command, [string]$WingetId, [string]$Url) {
    if (Have $Command) { Say "ok" "$Command is installed"; return $true }
    if ($DryRun) { Say "todo" "$Command is missing (winget install --id $WingetId, or $Url)"; $script:Todo.Add("install $Command"); return $false }
    if ((Have "winget") -and (Ask "$Command is missing. Install it with winget ($WingetId)?")) {
        winget install --id $WingetId -e --accept-source-agreements
        $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
        if (Have $Command) { Say "ok" "$Command installed"; return $true }
    }
    Say "fail" "$Command is needed: install it from $Url, then run this script again"
    $script:Failed++
    return $false
}

Write-Host "Jarvis setup$(if ($DryRun) { ' (dry run: nothing is changed)' })`n" -ForegroundColor Cyan

# 1. Windows
$build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
if ($build -ge 22000) { Say "ok" "Windows 11 (build $build)" }
else { Say "todo" "Windows build ${build}: Jarvis is built for Windows 11; some features may not work" }

# 2. Tools
$hasUv = Ensure-Tool "uv" "astral-sh.uv" "https://docs.astral.sh/uv/"
$hasOllama = Ensure-Tool "ollama" "Ollama.Ollama" "https://ollama.com/download"

# 3. Python packages
$gpu = @(Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" })
$extras = @()
if (-not $NoVoice) { $extras += @("--extra", "voice", "--extra", "piper") }
if ($gpu.Count -gt 0 -and -not $NoVoice) {
    Say "ok" "NVIDIA GPU found ($($gpu[0].Name)): speech recognition will run on it"
    $extras += @("--extra", "gpu")
}
if ($hasUv) {
    Run "install the Python packages (uv sync $($extras -join ' '))" { uv sync @extras }
}

# 4. Models
$ollamaUp = $false
try {
    $version = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/version" -TimeoutSec 3
    Say "ok" "Ollama is running ($($version.version))"
    $ollamaUp = $true
} catch {
    if ($hasOllama) { Say "todo" "Ollama is not running: start the Ollama app, then run this script again" }
    $script:Todo.Add("start Ollama")
}
if ($ollamaUp) {
    $tags = (Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags").models | ForEach-Object { $_.name }
    foreach ($name in @($Model, "nomic-embed-text")) {
        $wanted = if ($name.Contains(":")) { $name } else { "$name`:latest" }
        if ($tags -contains $wanted) { Say "ok" "model $name is downloaded" }
        else { Run "download the model $name" { ollama pull $name } }
    }
    $alias = "jarvis-hermes3"
    $file = "config\ollama\hermes3-8b.Modelfile"
    if ($Model -eq "hermes3:3b") { $alias = "jarvis-hermes3-3b"; $file = "config\ollama\hermes3-3b.Modelfile" }
    if ($tags -contains "$alias`:latest") { Say "ok" "model alias $alias exists" }
    else { Run "create the model alias $alias" { ollama create $alias -f $file } }
}

# 5. Config files (never overwritten)
foreach ($pair in @(@(".env.example", ".env"), @("config\local.example.toml", "config\local.toml"))) {
    if (Test-Path $pair[1]) { Say "ok" "$($pair[1]) exists (kept as it is)" }
    else { Run "create $($pair[1]) from $($pair[0])" { Copy-Item $pair[0] $pair[1] } }
}

# 6. Speech models
if ($NoVoice) { Say "skip" "voice (-NoVoice)" }
elseif ($hasUv) { Run "download the speech, voice, and wake word models" { uv run jarvis setup-voice } }

# Summary
Write-Host ""
if ($script:Failed -gt 0) {
    Say "fail" "$($script:Failed) step(s) failed; fix them and run .\install.ps1 again"
    exit 1
}
if ($DryRun) {
    Say "ok" "dry run done: $($script:Todo.Count) step(s) would run"
    exit 0
}
Say "ok" "Jarvis is set up. Next:"
Write-Host @"
  uv run jarvis serve --wake          start it (say "Hey Jarvis" or hold Ctrl+Alt+J)
  uv run jarvis voice --train-wake    if "Hey Jarvis" misses your voice
  uv run jarvis startup enable        start it at every login
  docs\SETUP.md                       mail, calendar, GitHub, WhatsApp, and the rest
"@
exit 0
