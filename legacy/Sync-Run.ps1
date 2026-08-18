param(
    [string]$ConfigFile = "$PSScriptRoot\config.json"
)

. "$PSScriptRoot\lib\GitSyncCore.ps1"

if (-not (Test-Path $ConfigFile)) {
    Write-Error "config nao encontrado: $ConfigFile"
    exit 1
}

$config = Get-Content $ConfigFile -Raw | ConvertFrom-Json

$logFile = if ([System.IO.Path]::IsPathRooted($config.logFile)) { $config.logFile } else { Join-Path $PSScriptRoot $config.logFile }
$statusFile = if ([System.IO.Path]::IsPathRooted($config.statusFile)) { $config.statusFile } else { Join-Path $PSScriptRoot $config.statusFile }

$paths = Resolve-SyncTargets -Targets $config.targets

$results = @()
foreach ($p in $paths) {
    $r = Invoke-GitAutoSync -RepoPath $p -LogFile $logFile
    $results += $r
}

$statusEntries = @{}
if (Test-Path $statusFile) {
    try {
        $existing = Get-Content $statusFile -Raw | ConvertFrom-Json
        foreach ($prop in $existing.repos.PSObject.Properties) {
            $statusEntries[$prop.Name] = $prop.Value
        }
    } catch {}
}

foreach ($r in $results) {
    $statusEntries[$r.Path] = [PSCustomObject]@{
        lastRun    = $r.Time.ToString("yyyy-MM-dd HH:mm:ss")
        success    = $r.Success
        hadChanges = $r.HadChanges
        message    = $r.Message
    }
}

$statusOut = [PSCustomObject]@{
    lastSyncRun = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    repos       = $statusEntries
}

$statusOut | ConvertTo-Json -Depth 5 | Set-Content -Path $statusFile -Encoding UTF8

$results
