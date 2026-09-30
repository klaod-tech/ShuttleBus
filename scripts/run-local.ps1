# 로컬 한 번에 실행 — DB·마이그레이션·시드·임시 좌표·API·화면 (작업 SB-0101)
# 사용법: 루트 서버.cmd [start|stop|status]  또는
#   powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 [start|stop|status] [-NoBrowser] [-NoWeb]
#   start  : PostgreSQL(55432) 기동·마이그레이션·시드 → 좌표 없는 정거장에만 임시 좌표 → API(8000) → 화면(3000) → 브라우저
#   stop   : 이 스크립트가 띄운 API·화면을 끄고 PostgreSQL도 끈다
#   status : 세 가지가 켜져 있는지
# 이미 켜져 있는 것은 다시 띄우지 않는다. 로그는 .tools\run\*.log
param(
    [ValidateSet('start', 'stop', 'status')][string]$Action = 'start',
    [switch]$NoBrowser,
    [switch]$NoWeb
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Api = Join-Path $Root 'api'
$Web = Join-Path $Root 'web'
$Py = Join-Path $Api '.venv\Scripts\python.exe'
$Run = Join-Path $Root '.tools\run'
$DevDb = Join-Path $PSScriptRoot 'dev-db.ps1'
$ApiUrl = 'http://127.0.0.1:8000'
$WebUrl = 'http://localhost:3000'

function Test-Url([string]$url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -lt 500)
    } catch { return $false }
}

function Wait-Url([string]$url, [int]$seconds, [string]$log) {
    for ($i = 0; $i -lt $seconds; $i++) {
        if (Test-Url $url) { return }
        Start-Sleep -Seconds 1
    }
    throw "$url 이(가) ${seconds}초 안에 응답하지 않는다. 로그: $log"
}

function Start-Hidden([string]$name, [string]$file, [string[]]$arguments, [string]$dir) {
    New-Item -ItemType Directory -Force $Run | Out-Null
    $out = Join-Path $Run "$name.log"
    $err = Join-Path $Run "$name.err.log"
    $p = Start-Process -FilePath $file -ArgumentList $arguments -WorkingDirectory $dir -WindowStyle Hidden `
        -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Set-Content -Path (Join-Path $Run "$name.pid") -Value $p.Id -Encoding ascii
    return $err
}

function Stop-Started([string]$name) {
    $pidFile = Join-Path $Run "$name.pid"
    if (-not (Test-Path $pidFile)) { return $false }
    $id = (Get-Content $pidFile -Raw).Trim()
    # npm·uvicorn은 자식 프로세스를 두므로 트리째 끈다
    & taskkill.exe /PID $id /T /F *> $null
    Remove-Item $pidFile
    return $true
}

switch ($Action) {
    'start' {
        if (-not (Test-Path $Py)) { throw 'api\.venv가 없다. 먼저 setup.cmd를 실행한다.' }
        if (-not $NoWeb -and -not (Test-Path (Join-Path $Web 'node_modules'))) { throw 'web\node_modules가 없다. 먼저 setup.cmd를 실행한다.' }

        # 1. DB — 없으면 내려받고 초기화. 마이그레이션·시드는 멱등이라 매번 돌아도 된다
        & $DevDb start

        # 2. 임시 좌표 — 좌표가 없는 정거장에만. 현장 확인값·손으로 넣은 값은 덮지 않는다 (PLAN-route-data.md)
        $env:PYTHONUTF8 = '1'
        Push-Location $Api
        try { & $Py -m app.stops import --file samples\stops-provisional.json --missing-only } finally { Pop-Location }

        # 3. API — REST·Socket.IO·배경 작업(회차 보충·상태 만료·전송)이 한 프로세스
        if (Test-Url "$ApiUrl/healthz") {
            Write-Host "API는 이미 켜져 있다: $ApiUrl"
        } else {
            $log = Start-Hidden 'api' $Py @('-m', 'uvicorn', 'app.main:asgi', '--host', '127.0.0.1', '--port', '8000') $Api
            Wait-Url "$ApiUrl/healthz" 60 $log
        }
        Write-Host "API: $ApiUrl/docs" -ForegroundColor Green

        # 4. 화면 — web/은 참고 구현 (CLAUDE.md 7장). 카카오 키는 web\.env.local
        if (-not $NoWeb) {
            if (Test-Url $WebUrl) {
                Write-Host "화면은 이미 켜져 있다: $WebUrl"
            } else {
                $log = Start-Hidden 'web' 'npm.cmd' @('run', 'dev') $Web
                Wait-Url $WebUrl 120 $log
            }
            Write-Host "화면: $WebUrl" -ForegroundColor Green
            if (-not $NoBrowser) { Start-Process $WebUrl }
        }
        Write-Host '끄기: 서버.cmd stop'
    }
    'stop' {
        foreach ($name in 'web', 'api') {
            if (Stop-Started $name) { Write-Host "$name 종료" } else { Write-Host "$name : 이 스크립트가 띄운 프로세스 없음" }
        }
        & $DevDb stop
    }
    'status' {
        & $DevDb status
        foreach ($item in @(@('API', "$ApiUrl/healthz"), @('화면', $WebUrl))) {
            if (Test-Url $item[1]) { Write-Host "$($item[0]) 실행 중: $($item[1])" -ForegroundColor Green } else { Write-Host "$($item[0]) 중지됨" }
        }
    }
}
