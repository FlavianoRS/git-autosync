param(
    [Parameter(Mandatory = $true)][string]$RepoPath,
    [string]$LogFile = "$PSScriptRoot\autosync.log"
)

. "$PSScriptRoot\lib\GitSyncCore.ps1"

$null = Invoke-GitAutoSync -RepoPath $RepoPath -LogFile $LogFile
