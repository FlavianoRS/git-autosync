param([string]$RepoPath = (Get-Location).Path)

$ScriptDir = $PSScriptRoot
& "$ScriptDir\AutoGitSync.ps1" -RepoPath $RepoPath -LogFile (Join-Path $ScriptDir "autosync.log")
