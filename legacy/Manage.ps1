param(
    [ValidateSet("Status","List","Add","Remove","SetSchedule","RunNow","Install","Uninstall","Log","EnableTray","DisableTray")]
    [string]$Action,
    [string]$RepoPath,
    [ValidateSet("repo","root")][string]$TargetType = "repo",
    [string]$Times,
    [switch]$Json,
    [int]$LogLines = 40
)

$ScriptDir = $PSScriptRoot
$ConfigFile = Join-Path $ScriptDir "config.json"
$StatusFile = Join-Path $ScriptDir "status.json"

function Load-Config { Get-Content $ConfigFile -Raw | ConvertFrom-Json }
function Save-Config($cfg) { $cfg | ConvertTo-Json -Depth 5 | Set-Content -Path $ConfigFile -Encoding UTF8 }

function Show-Status {
    param([switch]$AsJson)
    if (-not (Test-Path $StatusFile)) {
        if ($AsJson) { '{"lastSyncRun":null,"repos":{}}' | Write-Output }
        else { Write-Host "Ainda sem execucoes registradas. Use RunNow ou aguarde a tarefa agendada." }
        return
    }
    $status = Get-Content $StatusFile -Raw | ConvertFrom-Json
    if ($AsJson) {
        $status | ConvertTo-Json -Depth 5
        return
    }
    Write-Host "Ultima rodada geral: $($status.lastSyncRun)"
    Write-Host ""
    foreach ($prop in $status.repos.PSObject.Properties) {
        $r = $prop.Value
        $icon = if ($r.success) { "[OK]" } else { "[ERRO]" }
        Write-Host "$icon $($prop.Name)"
        Write-Host "     ultima execucao: $($r.lastRun) | alteracoes: $($r.hadChanges) | $($r.message)"
    }
}

function Show-List {
    $cfg = Load-Config
    Write-Host "Horarios agendados: $($cfg.schedules -join ', ')"
    Write-Host "Tarefa agendada: $($cfg.taskName)"
    Write-Host "Tray habilitada: $($cfg.trayEnabled)"
    Write-Host ""
    Write-Host "Alvos configurados:"
    $i = 0
    foreach ($t in $cfg.targets) {
        $i++
        $tag = if ($t.type -eq "root") { "ROOT (varre subpastas git)" } else { "REPO" }
        $en = if ($t.enabled) { "ativo" } else { "desativado" }
        Write-Host "  $i. [$tag][$en] $($t.path)"
    }
}

function Add-Target {
    param([string]$Path, [string]$Type)
    if (-not (Test-Path $Path)) {
        Write-Error "Caminho nao existe: $Path"
        return
    }
    $cfg = Load-Config
    $existing = $cfg.targets | Where-Object { $_.path -eq $Path }
    if ($existing) {
        Write-Host "Alvo ja existe: $Path"
        return
    }
    $cfg.targets = @($cfg.targets) + [PSCustomObject]@{ path = $Path; type = $Type; enabled = $true }
    Save-Config $cfg
    Write-Host "Adicionado ($Type): $Path"
}

function Remove-Target {
    param([string]$Path)
    $cfg = Load-Config
    $before = @($cfg.targets).Count
    $cfg.targets = @($cfg.targets | Where-Object { $_.path -ne $Path })
    Save-Config $cfg
    $after = @($cfg.targets).Count
    if ($before -eq $after) { Write-Host "Nenhum alvo encontrado com esse caminho." }
    else { Write-Host "Removido: $Path" }
}

function Set-Schedule {
    param([string]$TimesCsv)
    $times = $TimesCsv.Split(",") | ForEach-Object { $_.Trim() } | Where-Object { $_ -match '^\d{1,2}:\d{2}$' }
    if (-not $times -or $times.Count -eq 0) {
        Write-Error "Formato invalido. Use HH:mm separado por virgula, ex: 12:00,17:30"
        return
    }
    $cfg = Load-Config
    $cfg.schedules = @($times)
    Save-Config $cfg
    Write-Host "Horarios atualizados: $($times -join ', ')"
    Register-SyncTask -Cfg $cfg
    Write-Host "Tarefa agendada atualizada."
}

function Register-SyncTask {
    param($Cfg)
    $triggers = @()
    foreach ($t in $Cfg.schedules) {
        $triggers += New-ScheduledTaskTrigger -Daily -At $t
    }
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptDir\Sync-Run.ps1`""
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $Cfg.taskName -Trigger $triggers -Action $action -Settings $settings -Force | Out-Null
}

function Install-AutoSync {
    param([switch]$WithTray)
    $cfg = Load-Config
    Register-SyncTask -Cfg $cfg
    Write-Host "Tarefa agendada '$($cfg.taskName)' instalada/atualizada com horarios: $($cfg.schedules -join ', ')"

    if ($WithTray) {
        $startupDir = [Environment]::GetFolderPath("Startup")
        $shortcutPath = Join-Path $startupDir "GitAutoSyncTray.lnk"
        $wsh = New-Object -ComObject WScript.Shell
        $shortcut = $wsh.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = "powershell.exe"
        $shortcut.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptDir\Tray.ps1`""
        $shortcut.WorkingDirectory = $ScriptDir
        $shortcut.Save()
        $cfg.trayEnabled = $true
        Save-Config $cfg
        Write-Host "Tray configurada para iniciar com o Windows. Iniciando agora..."
        Start-Process powershell.exe -ArgumentList "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ScriptDir\Tray.ps1`""
    }
}

function Uninstall-AutoSync {
    $cfg = Load-Config
    Unregister-ScheduledTask -TaskName $cfg.taskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa agendada '$($cfg.taskName)' removida."
    $startupDir = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startupDir "GitAutoSyncTray.lnk"
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force
        Write-Host "Atalho da tray removido do Startup."
    }
    $cfg.trayEnabled = $false
    Save-Config $cfg
    Get-CimInstance Win32_Process -Filter "Name = 'powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*Tray.ps1*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function Enable-Tray {
    $cfg = Load-Config
    Install-AutoSync -WithTray
}

function Disable-Tray {
    $cfg = Load-Config
    $startupDir = [Environment]::GetFolderPath("Startup")
    $shortcutPath = Join-Path $startupDir "GitAutoSyncTray.lnk"
    if (Test-Path $shortcutPath) { Remove-Item $shortcutPath -Force }
    $cfg.trayEnabled = $false
    Save-Config $cfg
    Write-Host "Tray desabilitada. Feche manualmente o icone na bandeja se estiver aberto (menu Sair)."
}

function Show-Log {
    param([int]$Lines)
    $cfg = Load-Config
    $logFile = if ([System.IO.Path]::IsPathRooted($cfg.logFile)) { $cfg.logFile } else { Join-Path $ScriptDir $cfg.logFile }
    if (Test-Path $logFile) { Get-Content $logFile -Tail $Lines }
    else { Write-Host "Sem log ainda." }
}

function Run-Now {
    Write-Host "Rodando sync agora..."
    & "$ScriptDir\Sync-Run.ps1" | Format-Table -AutoSize
}

function Show-Menu {
    while ($true) {
        Write-Host ""
        Write-Host "=== Git AutoSync - Gerenciador ==="
        Write-Host "1. Ver status"
        Write-Host "2. Listar alvos e horarios"
        Write-Host "3. Adicionar diretorio"
        Write-Host "4. Remover diretorio"
        Write-Host "5. Definir horarios (ex: 12:00,17:30)"
        Write-Host "6. Rodar agora"
        Write-Host "7. Instalar/atualizar tarefa agendada"
        Write-Host "8. Instalar tarefa + tray (bandeja)"
        Write-Host "9. Desinstalar tudo"
        Write-Host "10. Ver log"
        Write-Host "0. Sair"
        $op = Read-Host "Escolha"
        switch ($op) {
            "1" { Show-Status }
            "2" { Show-List }
            "3" {
                $p = Read-Host "Caminho do diretorio"
                $t = Read-Host "Tipo (repo/root) [repo]"
                if ([string]::IsNullOrWhiteSpace($t)) { $t = "repo" }
                Add-Target -Path $p -Type $t
            }
            "4" {
                $p = Read-Host "Caminho do diretorio a remover"
                Remove-Target -Path $p
            }
            "5" {
                $t = Read-Host "Horarios (HH:mm, separados por virgula)"
                Set-Schedule -TimesCsv $t
            }
            "6" { Run-Now }
            "7" { Install-AutoSync }
            "8" { Install-AutoSync -WithTray }
            "9" { Uninstall-AutoSync }
            "10" { Show-Log -Lines 40 }
            "0" { return }
            default { Write-Host "Opcao invalida." }
        }
    }
}

switch ($Action) {
    "Status"      { Show-Status -AsJson:$Json }
    "List"        { Show-List }
    "Add"         { Add-Target -Path $RepoPath -Type $TargetType }
    "Remove"      { Remove-Target -Path $RepoPath }
    "SetSchedule" { Set-Schedule -TimesCsv $Times }
    "RunNow"      { Run-Now }
    "Install"     { Install-AutoSync }
    "Uninstall"   { Uninstall-AutoSync }
    "Log"         { Show-Log -Lines $LogLines }
    "EnableTray"  { Enable-Tray }
    "DisableTray" { Disable-Tray }
    default       { Show-Menu }
}
