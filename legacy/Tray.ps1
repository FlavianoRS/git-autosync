Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$ScriptDir = $PSScriptRoot
$ConfigFile = Join-Path $ScriptDir "config.json"
$StatusFile = Join-Path $ScriptDir "status.json"

function Get-Cfg { Get-Content $ConfigFile -Raw | ConvertFrom-Json }

function New-DotIcon {
    param([string]$Color)
    $bmp = New-Object System.Drawing.Bitmap 32,32
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.Clear([System.Drawing.Color]::Transparent)
    $brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::$Color)
    $g.FillEllipse($brush, 2, 2, 28, 28)
    $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::Black), 1
    $g.DrawEllipse($pen, 2, 2, 28, 28)
    $icon = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
    return $icon
}

$iconOk    = New-DotIcon -Color "ForestGreen"
$iconErr   = New-DotIcon -Color "Crimson"
$iconWarn  = New-DotIcon -Color "Gold"
$iconIdle  = New-DotIcon -Color "Gray"

$notifyIcon = New-Object System.Windows.Forms.NotifyIcon
$notifyIcon.Icon = $iconIdle
$notifyIcon.Text = "Git AutoSync"
$notifyIcon.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$itemStatus = $menu.Items.Add("Status: carregando...")
$itemStatus.Enabled = $false
$menu.Items.Add("-") | Out-Null
$itemRunNow = $menu.Items.Add("Rodar agora")
$itemLog = $menu.Items.Add("Ver log")
$itemConfig = $menu.Items.Add("Abrir configuracao")
$menu.Items.Add("-") | Out-Null
$itemExit = $menu.Items.Add("Sair")
$notifyIcon.ContextMenuStrip = $menu

function Update-TrayStatus {
    if (-not (Test-Path $StatusFile)) {
        $notifyIcon.Icon = $iconIdle
        $notifyIcon.Text = "Git AutoSync: sem execucoes ainda"
        $itemStatus.Text = "Status: sem execucoes ainda"
        return
    }
    try {
        $status = Get-Content $StatusFile -Raw | ConvertFrom-Json
    } catch {
        $notifyIcon.Icon = $iconWarn
        $notifyIcon.Text = "Git AutoSync: erro ao ler status"
        return
    }
    $repos = @($status.repos.PSObject.Properties)
    $errors = @($repos | Where-Object { -not $_.Value.success })
    $changed = @($repos | Where-Object { $_.Value.hadChanges })

    if ($errors.Count -gt 0) {
        $notifyIcon.Icon = $iconErr
        $summary = "$($errors.Count) repo(s) com erro"
    } elseif ($changed.Count -gt 0) {
        $notifyIcon.Icon = $iconOk
        $summary = "$($changed.Count) repo(s) sincronizados"
    } else {
        $notifyIcon.Icon = $iconOk
        $summary = "tudo em dia"
    }

    $tooltip = "Git AutoSync - $summary`nUltima rodada: $($status.lastSyncRun)"
    if ($tooltip.Length -gt 127) { $tooltip = $tooltip.Substring(0,127) }
    $notifyIcon.Text = $tooltip
    $itemStatus.Text = "Status: $summary ($($status.lastSyncRun))"
}

$itemRunNow.Add_Click({
    $itemStatus.Text = "Status: rodando..."
    $notifyIcon.Icon = $iconWarn
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptDir\Sync-Run.ps1`"" -WindowStyle Hidden -Wait
    Update-TrayStatus
    $notifyIcon.ShowBalloonTip(3000, "Git AutoSync", $itemStatus.Text, [System.Windows.Forms.ToolTipIcon]::Info)
})

$itemLog.Add_Click({
    $cfg = Get-Cfg
    $logFile = if ([System.IO.Path]::IsPathRooted($cfg.logFile)) { $cfg.logFile } else { Join-Path $ScriptDir $cfg.logFile }
    if (Test-Path $logFile) { Start-Process notepad.exe $logFile }
})

$itemConfig.Add_Click({
    Start-Process -FilePath "powershell.exe" -ArgumentList "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$ScriptDir\Manage.ps1`""
})

$itemExit.Add_Click({
    $notifyIcon.Visible = $false
    $timer.Stop()
    [System.Windows.Forms.Application]::Exit()
})

$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 60000
$timer.Add_Tick({ Update-TrayStatus })
$timer.Start()

Update-TrayStatus
[System.Windows.Forms.Application]::Run()
