# ShuttleBus 개발 환경 설치 스크립트
# 사용법:  setup.cmd 더블클릭  또는  powershell -ExecutionPolicy Bypass -File setup.ps1
#          점검만 하려면        powershell -ExecutionPolicy Bypass -File setup.ps1 -Check
# 이미 설치된 것은 건너뛴다. 여러 번 실행해도 안전하다.

param([switch]$Check)

$ErrorActionPreference = 'Stop'
$Root = $PSScriptRoot

# 설치 대상 — 버전을 바꾸려면 여기만 고친다. 목록 설명은 SETUP.md
$Tools = @(
    @{ Name = 'Git';            Command = 'git';    WingetId = 'Git.Git' }
    @{ Name = 'Node.js (LTS)';  Command = 'node';   WingetId = 'OpenJS.NodeJS.LTS' }
    @{ Name = 'Python 3.13';    Command = 'python'; WingetId = 'Python.Python.3.13' }
    @{ Name = 'Docker Desktop'; Command = 'docker'; WingetId = 'Docker.DockerDesktop' }
)

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal $id).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Update-PathFromRegistry {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user    = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Test-Wsl {
    $ErrorActionPreference = 'Continue'
    try { & wsl.exe --status *> $null } catch { return $false }
    return ($LASTEXITCODE -eq 0)
}

function Get-ToolVersion($command) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { return $null }
    try { return (& $command --version 2>$null | Select-Object -First 1) } catch { return '설치됨' }
}

# ---------- 점검 ----------
Write-Host "`n== 현재 상태 ==" -ForegroundColor Cyan
$missing = @()
foreach ($t in $Tools) {
    $v = Get-ToolVersion $t.Command
    if ($v) { Write-Host ("  [OK]   {0,-15} {1}" -f $t.Name, $v) -ForegroundColor Green }
    else    { Write-Host ("  [없음] {0}" -f $t.Name) -ForegroundColor Yellow; $missing += $t }
}
$wslOk = Test-Wsl
if ($wslOk) { Write-Host "  [OK]   WSL2" -ForegroundColor Green }
else        { Write-Host "  [없음] WSL2 (Docker Desktop에 필요)" -ForegroundColor Yellow }

if ($Check) {
    if ($missing.Count -eq 0 -and $wslOk) { Write-Host "`n모두 설치되어 있다." -ForegroundColor Green }
    else { Write-Host "`n설치하려면 -Check 없이 다시 실행한다." }
    exit 0
}

# ---------- 설치 ----------
if (($missing.Count -gt 0 -or -not $wslOk) -and -not (Test-Admin)) {
    Write-Host "`n관리자 권한이 필요하다. 권한 요청 창에서 '예'를 누른다." -ForegroundColor Cyan
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit 0
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "winget이 없다. Microsoft Store에서 '앱 설치 관리자'를 설치한 뒤 다시 실행한다." -ForegroundColor Red
    exit 1
}

$needReboot = $false

if (-not $wslOk) {
    Write-Host "`n== WSL2 설치 ==" -ForegroundColor Cyan
    & wsl.exe --install --no-distribution
    $needReboot = $true
}

foreach ($t in $missing) {
    Write-Host "`n== $($t.Name) 설치 ==" -ForegroundColor Cyan
    & winget install --id $t.WingetId -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) { Write-Host "  $($t.Name) 설치 실패 (코드 $LASTEXITCODE)" -ForegroundColor Red }
    if ($t.Command -eq 'docker') { $needReboot = $true }
}
Update-PathFromRegistry

# ---------- 프로젝트 의존성 (코드가 생긴 뒤부터 동작) ----------
$apiReq = Join-Path $Root 'api\requirements-dev.txt'  # 시험 도구 포함. 운영 이미지는 requirements.txt만 쓴다
if (-not (Test-Path $apiReq)) { $apiReq = Join-Path $Root 'api\requirements.txt' }
if (Test-Path $apiReq) {
    Write-Host "`n== api Python 패키지 ==" -ForegroundColor Cyan
    $venv = Join-Path $Root 'api\.venv'
    if (-not (Test-Path $venv)) { & python -m venv $venv }
    & (Join-Path $venv 'Scripts\python.exe') -m pip install -r $apiReq
}

foreach ($dir in 'web', 'realtime') {
    $pkg = Join-Path $Root "$dir\package.json"
    if (Test-Path $pkg) {
        Write-Host "`n== $dir npm 패키지 ==" -ForegroundColor Cyan
        Push-Location (Join-Path $Root $dir)
        try { & npm install } finally { Pop-Location }
    }
}

# ---------- 마무리 ----------
Write-Host "`n== 완료 ==" -ForegroundColor Cyan
if ($needReboot) {
    Write-Host "컴퓨터를 재시작한 뒤 Docker Desktop을 한 번 실행한다." -ForegroundColor Yellow
    Write-Host "그 다음 이 스크립트를 -Check로 다시 실행해 전부 [OK]인지 확인한다." -ForegroundColor Yellow
} else {
    Write-Host "설치할 것이 없다." -ForegroundColor Green
}
