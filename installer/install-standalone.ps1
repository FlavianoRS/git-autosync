<#
.SYNOPSIS
    Instalacao standalone, silenciosa e idempotente do Git AutoSync.

.DESCRIPTION
    Sucessor nao-interativo do `install_standalone.bat`. Existe para ser chamado pelo
    instalador do Sankhya Hub (NSIS/electron-builder, Fase 4), onde nao ha ninguem para
    responder pergunta: aqui cada efeito colateral e' uma flag, e rodar duas vezes com as
    mesmas flags deixa a maquina no mesmo estado.

    Tres diferencas para o `.bat` que ele substitui:

      1. O agendamento NAO e' criado com `schtasks` na mao. Quem instala a tarefa e' o
         proprio `git-autosync set-schedule`, que ja' e' idempotente, deduplica
         `GitAutoSyncPy_\d+` e sabe fazer rollback (ver python/scheduler.py). Criar a
         tarefa por fora e' o que produzia uma tarefa que a interface nao gerencia.
      2. Instala as skills e, opcionalmente, o PATH - o `.bat` nao fazia nenhum dos dois.
      3. Escreve `bin\VERSION`. Com ele, o hub e o instalador descobrem a versao
         instalada LENDO UM ARQUIVO, sem executar binario nenhum do autosync.

    Nao exige Python na maquina de destino. Exige que os dois executaveis ja' existam
    (gerados por `python\build_windows.ps1` na maquina de quem empacota).

.PARAMETER Source
    Pasta com `git-autosync.exe` e `git-autosync-sync.exe`. Default: `python\dist` do
    proprio repositorio.

.PARAMETER Version
    Versao gravada em `bin\VERSION`. Default: conteudo de `python\VERSION`.

.PARAMETER TaskTime
    Horarios da rodada agendada, ex. `17:30` ou `12:00,17:30`. Sem este parametro,
    nenhuma tarefa e' criada nem alterada.

.PARAMETER EnableTray
    Bandeja subindo junto com o login do usuario.

.PARAMETER Shortcut
    Atalhos na area de trabalho e no menu Iniciar.

.PARAMETER Skills
    Copia `skill/SKILL.md` para `~/.claude/skills/git-autosync` e, se a pasta existir,
    para `~/.codex/skills/git-autosync`.

.PARAMETER AddToPath
    Poe a pasta `bin` no PATH do usuario (nunca no PATH da maquina).

.PARAMETER Uninstall
    Remove binarios, tarefa, bandeja, atalhos e skills. Preserva `config.json`,
    `status.json` e `autosync.log`, a menos que `-PurgeData` seja passado.

.PARAMETER PurgeData
    So' com `-Uninstall`: apaga tambem os dados do usuario.

.EXAMPLE
    .\install-standalone.ps1 -TaskTime 17:30 -EnableTray -Shortcut -Skills

.EXAMPLE
    .\install-standalone.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string] $Source,
    [string] $Version,
    [string] $TaskTime,
    [switch] $EnableTray,
    [switch] $Shortcut,
    [switch] $Skills,
    [switch] $AddToPath,
    [switch] $Uninstall,
    [switch] $PurgeData,
    [switch] $Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$RaizRepo = Split-Path -Parent $PSScriptRoot
$PastaAutosync = Join-Path $env:USERPROFILE '.git-autosync'
$PastaBin = Join-Path $PastaAutosync 'bin'
$ExeGui = Join-Path $PastaBin 'git-autosync.exe'
$ExeSync = Join-Path $PastaBin 'git-autosync-sync.exe'
$ArquivoVersao = Join-Path $PastaBin 'VERSION'
$TrayStartup = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\GitAutoSyncTray.bat'

# `GetFolderPath('Desktop')` devolve string VAZIA em processo nao interativo - que e'
# exatamente como o instalador chama este script. Medido no PowerShell 7 sem perfil.
# O caminho por baixo do perfil cobre o caso; a API continua na frente porque ela e' a
# unica que acerta quando a area de trabalho e' redirecionada (OneDrive, pasta de rede).
$PastaDesktop = [Environment]::GetFolderPath('Desktop')
if (-not $PastaDesktop) { $PastaDesktop = Join-Path $env:USERPROFILE 'Desktop' }
$AtalhoDesktop = Join-Path $PastaDesktop 'Git AutoSync.lnk'
$AtalhoMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Git AutoSync.lnk'

<# Horario da rodada agendada: formato validado aqui para a mensagem ser em portugues,
   e nao um traceback do Python la' dentro. #>
$FORMATO_HORARIO = '^([01][0-9]|2[0-3]):[0-5][0-9]$'

function Escrever {
    param([string] $Texto)
    if (-not $Quiet) { Write-Host $Texto }
}

function Falhar {
    param([string] $Texto)
    Write-Error $Texto
    exit 1
}

<# Copia so' quando muda. Alem de barato, mantem o `LastWriteTime` estavel, que e' o que
   deixa uma reinstalacao identica parecer identica em qualquer inspecao posterior. #>
function Copiar-SeDiferente {
    param([string] $De, [string] $Para)

    if (Test-Path -LiteralPath $Para) {
        $origem = (Get-FileHash -LiteralPath $De -Algorithm SHA256).Hash
        $destino = (Get-FileHash -LiteralPath $Para -Algorithm SHA256).Hash
        if ($origem -eq $destino) {
            Escrever "  = $(Split-Path -Leaf $Para) ja' esta' na versao correta"
            return
        }
    }
    Copy-Item -LiteralPath $De -Destination $Para -Force
    Escrever "  + $(Split-Path -Leaf $Para)"
}

<#
Atalho e' cosmetico: falhar nele NAO pode derrubar a instalacao. Antes de existir este
try/catch, uma area de trabalho ausente ou redirecionada abortava o script DEPOIS de
copiar os binarios e ANTES das skills - a instalacao ficava pela metade por causa de um
`.lnk`. A pasta e' criada quando falta, que e' a causa mais comum.
#>
function Criar-Atalho {
    param([string] $Caminho, [string] $Alvo, [string] $Pasta)

    try {
        $pastaDoAtalho = Split-Path -Parent $Caminho
        if (-not (Test-Path -LiteralPath $pastaDoAtalho)) {
            New-Item -ItemType Directory -Path $pastaDoAtalho -Force | Out-Null
        }

        $shell = New-Object -ComObject WScript.Shell
        try {
            $atalho = $shell.CreateShortcut($Caminho)
            $atalho.TargetPath = $Alvo
            $atalho.WorkingDirectory = $Pasta
            $atalho.Description = 'Git AutoSync'
            $atalho.Save()
        } finally {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($shell)
        }
        return $true
    } catch {
        Escrever "  ! nao consegui criar o atalho em $Caminho ($($_.Exception.Message))"
        return $false
    }
}

function Remover-SeExistir {
    param([string] $Caminho)
    if (Test-Path -LiteralPath $Caminho) {
        Remove-Item -LiteralPath $Caminho -Recurse -Force
        Escrever "  - $Caminho"
    }
}

# ---------------------------------------------------------------- desinstalacao -----

if ($Uninstall) {
    Escrever '=== Desinstalando o Git AutoSync ==='

    # A tarefa e a bandeja saem primeiro, e pelo PROPRIO binario (`uninstall` faz as
    # duas): se o executavel sumir antes, a tarefa fica no Agendador apontando para um
    # caminho morto e ninguem mais sabe o nome dela. O fallback so' entra se o binario
    # ja' nao estiver la' ou recusar.
    $removeuPeloBinario = $false
    if (Test-Path -LiteralPath $ExeGui) {
        & $ExeGui uninstall 2>&1 | Out-Null
        $removeuPeloBinario = $LASTEXITCODE -eq 0
    }
    if (-not $removeuPeloBinario) {
        Escrever '  ! removendo tarefa agendada pelo schtasks (o binario nao respondeu)'
        & schtasks /Query /FO CSV /NH 2>$null |
            ForEach-Object { ($_ -split '","')[0].Trim('"').TrimStart('\') } |
            Where-Object { $_ -match '^GitAutoSyncPy(_\d+)?$' } |
            ForEach-Object { & schtasks /Delete /TN $_ /F | Out-Null }
    }

    Remover-SeExistir $TrayStartup
    Remover-SeExistir $AtalhoDesktop
    Remover-SeExistir $AtalhoMenu
    Remover-SeExistir (Join-Path $env:USERPROFILE '.claude\skills\git-autosync')
    Remover-SeExistir (Join-Path $env:USERPROFILE '.codex\skills\git-autosync')
    Remover-SeExistir $PastaBin

    if ($PurgeData) {
        Remover-SeExistir $PastaAutosync
        Escrever 'Dados do usuario apagados (-PurgeData).'
    } else {
        Escrever "Dados preservados em $PastaAutosync (config.json, status.json, autosync.log)."
    }

    Escrever 'Desinstalacao concluida.'
    exit 0
}

# ------------------------------------------------------------------ instalacao ------

if (-not $Source) { $Source = Join-Path $RaizRepo 'python\dist' }

<# A versao e a skill sao procuradas AO LADO DOS BINARIOS antes do layout do
   repositorio. Quando o instalador do Sankhya Hub chama este script, o que existe e' a
   pasta de recursos do pacote (binarios + VERSION + SKILL.md juntos) - nao ha repo
   nenhum por perto. Rodando do checkout, nada muda: o `-Source` padrao e' `python\dist`,
   que nao tem VERSION, e a busca cai no arquivo do repositorio. #>
if (-not $Version) {
    $Version = 'desconhecida'
    foreach ($candidato in @((Join-Path $Source 'VERSION'), (Join-Path $RaizRepo 'python\VERSION'))) {
        if (Test-Path -LiteralPath $candidato) {
            $Version = (Get-Content -LiteralPath $candidato -Raw).Trim()
            break
        }
    }
}

$origemGui = Join-Path $Source 'git-autosync.exe'
$origemSync = Join-Path $Source 'git-autosync-sync.exe'

foreach ($arquivo in @($origemGui, $origemSync)) {
    if (-not (Test-Path -LiteralPath $arquivo)) {
        Falhar "nao encontrei $arquivo - gere os executaveis com python\build_windows.ps1 antes de instalar"
    }
}

if ($TaskTime -and ($TaskTime -split ',' | Where-Object { $_.Trim() -notmatch $FORMATO_HORARIO })) {
    Falhar "-TaskTime fora do formato HH:mm (aceita lista: `"12:00,17:30`"): $TaskTime"
}

# Pre-requisito real e unico: o autosync executa `git` de verdade.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Falhar 'git nao encontrado no PATH - instale o Git antes de instalar o Git AutoSync'
}

Escrever "=== Git AutoSync $Version (standalone, sem Python) ==="

New-Item -ItemType Directory -Path $PastaBin -Force | Out-Null
Copiar-SeDiferente -De $origemGui -Para $ExeGui
Copiar-SeDiferente -De $origemSync -Para $ExeSync

# Lido pelo hub e pelo proximo instalador para decidir instalar/atualizar/nao mexer, sem
# executar binario nenhum - diagnostico nao pode ter efeito colateral.
Set-Content -LiteralPath $ArquivoVersao -Value $Version -Encoding ASCII -NoNewline
Escrever "  + VERSION ($Version)"

if ($TaskTime) {
    # Delegado de proposito: `set-schedule` valida o horario, aponta a tarefa para o
    # `git-autosync-sync.exe` ao lado, deduplica tarefas antigas e restaura a anterior se
    # a nova falhar. Um `schtasks /Create` aqui criaria uma segunda tarefa que a
    # interface nao enxerga como sua.
    $saida = & $ExeGui set-schedule $TaskTime 2>&1
    if ($LASTEXITCODE -ne 0) { Falhar "falha ao agendar ($TaskTime): $saida" }
    Escrever "  + tarefa agendada ($TaskTime)"
}

if ($EnableTray) {
    # Delegado pelo mesmo motivo do agendamento: `enable-tray` escreve o `.bat` da pasta
    # Startup E grava `trayEnabled` no `config.json`. Escrever so' o `.bat` deixaria a
    # interface mostrando a bandeja como desligada enquanto ela sobe todo login.
    $saida = & $ExeGui enable-tray 2>&1
    if ($LASTEXITCODE -ne 0) { Falhar "falha ao habilitar a bandeja: $saida" }
    Escrever '  + bandeja iniciando com o login'
}

if ($Shortcut) {
    $criados = @()
    if (Criar-Atalho -Caminho $AtalhoDesktop -Alvo $ExeGui -Pasta $PastaBin) { $criados += 'area de trabalho' }
    if (Criar-Atalho -Caminho $AtalhoMenu -Alvo $ExeGui -Pasta $PastaBin) { $criados += 'menu Iniciar' }
    if ($criados) { Escrever "  + atalhos ($($criados -join ', '))" }
}

if ($Skills) {
    # Mesma ordem da versao: ao lado dos binarios primeiro (pacote), repositorio depois.
    $fonteSkill = @((Join-Path $Source 'SKILL.md'), (Join-Path $RaizRepo 'skill\SKILL.md')) |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $fonteSkill) { Falhar "nao encontrei o SKILL.md (procurei em $Source e em $RaizRepo\skill)" }

    # A versao no cabecalho da skill acompanha a do produto - mesma substituicao que o
    # `installer/install.py` faz.
    $texto = (Get-Content -LiteralPath $fonteSkill -Raw) -replace '(?m)^version:\s*.*$', "version: $Version"

    $destinos = @(Join-Path $env:USERPROFILE '.claude\skills\git-autosync')
    if (Test-Path -LiteralPath (Join-Path $env:USERPROFILE '.codex')) {
        $destinos += Join-Path $env:USERPROFILE '.codex\skills\git-autosync'
    }
    foreach ($destino in $destinos) {
        New-Item -ItemType Directory -Path $destino -Force | Out-Null
        Set-Content -LiteralPath (Join-Path $destino 'SKILL.md') -Value $texto -Encoding UTF8
        Escrever "  + skill em $destino"
    }
}

if ($AddToPath) {
    # PATH do USUARIO, nunca o da maquina: a instalacao inteira e' per-user e nao pede
    # elevacao. Comparacao sem diferenciar maiuscula porque o Windows nao diferencia.
    $atual = [Environment]::GetEnvironmentVariable('Path', 'User')
    $entradas = @($atual -split ';' | Where-Object { $_ })
    if ($entradas | Where-Object { $_.TrimEnd('\') -ieq $PastaBin.TrimEnd('\') }) {
        Escrever "  = $PastaBin ja' esta' no PATH do usuario"
    } else {
        $novo = (@($entradas) + $PastaBin) -join ';'
        [Environment]::SetEnvironmentVariable('Path', $novo, 'User')
        Escrever "  + $PastaBin no PATH do usuario (vale em terminal novo)"
    }
}

Escrever ''
Escrever "Instalado em $PastaBin"
if (-not $TaskTime) {
    Escrever 'Sem tarefa agendada nesta instalacao - use a aba Agendamento da interface quando quiser uma.'
}
exit 0
