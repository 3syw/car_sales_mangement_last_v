Param(
    [string]$EnvFile = "env.production"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $EnvFile)) {
    Write-Error "Environment file not found: $EnvFile"
}

Get-Content $EnvFile |
    Where-Object { $_ -and -not $_.Trim().StartsWith('#') } |
    ForEach-Object {
        $parts = $_ -split '=', 2
        if ($parts.Count -eq 2) {
            [System.Environment]::SetEnvironmentVariable($parts[0].Trim(), $parts[1].Trim(), 'Process')
        }
    }

Write-Host "[1/6] Pulling latest code"
git pull

Write-Host "[2/6] Installing dependencies"
pip install -r requirements.txt

Write-Host "[3/7] Running default DB migrations"
python manage.py migrate --settings=core.settings_production

Write-Host "[4/7] Running tenant DB migrations"
python manage.py migrate_all_tenants --settings=core.settings_production

Write-Host "[5/7] Collecting static files"
python manage.py collectstatic --noinput --settings=core.settings_production

Write-Host "[6/7] Running deploy checks"
python manage.py check --deploy --settings=core.settings_production

Write-Host "[7/7] Deployment tasks completed"
Write-Host "Restart app services now (gunicorn/celery/nginx) according to your host setup."
