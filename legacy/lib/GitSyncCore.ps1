function Write-SyncLog {
    param([string]$LogFile, [string]$RepoPath, [string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') [$RepoPath] $Message"
    Add-Content -Path $LogFile -Value $line
    Write-Host $line
}

function Invoke-GitAutoSync {
    param(
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [Parameter(Mandatory = $true)][string]$LogFile
    )

    $result = [PSCustomObject]@{
        Path       = $RepoPath
        Time       = Get-Date
        Success    = $false
        HadChanges = $false
        Message    = ""
    }

    if (-not (Test-Path (Join-Path $RepoPath ".git"))) {
        $result.Message = "nao e repositorio git, pulando"
        Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message "ERRO: $($result.Message)."
        return $result
    }

    Push-Location $RepoPath
    try {
        $status = git status --porcelain
        if ([string]::IsNullOrWhiteSpace($status)) {
            $result.Success = $true
            $result.Message = "sem alteracoes, nada a fazer"
            Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message $result.Message
            return $result
        }

        $result.HadChanges = $true
        git add -A

        $diff = git diff --staged | Out-String
        if ($diff.Length -gt 12000) {
            $diff = $diff.Substring(0, 12000) + "`n...(diff truncado)..."
        }

        $prompt = @"
Gere APENAS uma mensagem de commit no padrao Conventional Commits (feat:, fix:, chore:, docs:, refactor:, etc), em portugues, uma linha, maximo 72 caracteres, baseada no diff abaixo. Responda SOMENTE com a mensagem, sem aspas, sem explicacao, sem markdown.

$diff
"@

        $commitMsg = $null
        try {
            $commitMsg = (claude -p $prompt --output-format text --disallowedTools "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch" 2>$null | Out-String).Trim()
        } catch {
            $commitMsg = $null
        }

        if ([string]::IsNullOrWhiteSpace($commitMsg)) {
            $commitMsg = "chore: auto-commit $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
            Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message "aviso: claude nao retornou mensagem, usando fallback."
        }

        $tmpMsgFile = [System.IO.Path]::GetTempFileName()
        Set-Content -Path $tmpMsgFile -Value $commitMsg -Encoding UTF8
        git commit -F $tmpMsgFile | Out-Null
        Remove-Item $tmpMsgFile -Force
        Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message "commit local ok: $commitMsg"

        $pushOutput = git push 2>&1
        if ($LASTEXITCODE -eq 0) {
            $result.Success = $true
            $result.Message = "commit: $commitMsg | push ok"
            Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message "push ok."
        } else {
            $result.Success = $false
            $result.Message = "commit: $commitMsg | push FALHOU: $pushOutput"
            Write-SyncLog -LogFile $LogFile -RepoPath $RepoPath -Message "AVISO: push falhou -> $pushOutput"
        }
    }
    finally {
        Pop-Location
    }

    return $result
}

function Resolve-SyncTargets {
    param([array]$Targets)

    $paths = New-Object System.Collections.Generic.List[string]
    foreach ($t in $Targets) {
        if (-not $t.enabled) { continue }
        if ($t.type -eq "root") {
            if (Test-Path $t.path) {
                Get-ChildItem -Path $t.path -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                    if (Test-Path (Join-Path $_.FullName ".git")) {
                        $paths.Add($_.FullName)
                    }
                }
            }
        } else {
            $paths.Add($t.path)
        }
    }
    return $paths
}
