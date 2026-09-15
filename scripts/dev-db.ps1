# Docker 없이 쓰는 로컬 PostgreSQL (관리자 권한 불필요)
# 사용법: powershell -ExecutionPolicy Bypass -File scripts\dev-db.ps1 [start|stop|status|reset]
#   start  : 없으면 내려받고 초기화한 뒤 55432 포트로 기동, DB 생성·마이그레이션·시드
#   reset  : 개발 DB를 비우고 다시 마이그레이션·시드
param([ValidateSet('start', 'stop', 'status', 'reset')][string]$Action = 'start')

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root '.tools'
$Bin = Join-Path $Tools 'pgsql\bin'
$Data = Join-Path $Tools 'pgdata'
$Port = 55432
$PgZipUrl = 'https://get.enterprisedb.com/postgresql/postgresql-18.3-1-windows-x64-binaries.zip'
$Api = Join-Path $Root 'api'
$Py = Join-Path $Api '.venv\Scripts\python.exe'

function Invoke-Psql([string]$db, [string]$sql) {
    & (Join-Path $Bin 'psql.exe') -h localhost -p $Port -U postgres -d $db -v ON_ERROR_STOP=1 -qtAc $sql
}

function Test-Running {
    & (Join-Path $Bin 'pg_isready.exe') -h localhost -p $Port *> $null
    return ($LASTEXITCODE -eq 0)
}

function Install-Postgres {
    if (Test-Path (Join-Path $Bin 'postgres.exe')) { return }
    Write-Host 'PostgreSQL 휴대용 바이너리를 내려받는다 (약 320MB)...'
    New-Item -ItemType Directory -Force $Tools | Out-Null
    $zip = Join-Path $Tools 'pg.zip'
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $PgZipUrl -OutFile $zip -UseBasicParsing
    Expand-Archive $zip -DestinationPath $Tools -Force
    Remove-Item $zip
}

function Invoke-MigrateSeed {
    $env:PYTHONUTF8 = '1'
    Push-Location $Api
    try {
        & $Py -m alembic upgrade head
        & $Py -m app.seed
    } finally { Pop-Location }
}

switch ($Action) {
    'start' {
        Install-Postgres
        if (-not (Test-Path $Data)) {
            & (Join-Path $Bin 'initdb.exe') -D $Data -U postgres -A trust -E UTF8 --locale=C | Out-Null
        }
        if (-not (Test-Running)) {
            # pg_ctl은 자식 프로세스 핸들을 잡고 있어 Start-Process로 분리한다
            Start-Process -FilePath (Join-Path $Bin 'pg_ctl.exe') -ArgumentList @('-D', "`"$Data`"", '-l', "`"$Tools\pg.log`"", '-o', "`"-p $Port`"", 'start') -WindowStyle Hidden -Wait:$false
            for ($i = 0; $i -lt 30 -and -not (Test-Running); $i++) { Start-Sleep -Milliseconds 500 }
        }
        foreach ($db in 'shuttlebus', 'shuttlebus_test') {
            if (-not (Invoke-Psql 'postgres' "select 1 from pg_database where datname='$db'")) {
                Invoke-Psql 'postgres' "create database $db" | Out-Null
            }
        }
        Invoke-MigrateSeed
        Write-Host "PostgreSQL 기동: localhost:$Port (DB shuttlebus, shuttlebus_test)" -ForegroundColor Green
    }
    'stop' {
        & (Join-Path $Bin 'pg_ctl.exe') -D $Data stop
    }
    'status' {
        if (Test-Running) { Write-Host "실행 중: localhost:$Port" -ForegroundColor Green } else { Write-Host '중지됨' }
    }
    'reset' {
        Invoke-Psql 'shuttlebus' 'drop schema public cascade; create schema public;' | Out-Null
        Invoke-MigrateSeed
        Write-Host '개발 DB를 초기화했다.' -ForegroundColor Green
    }
}
