---
name: git-autosync
version: 3.1.0
description: Gerencia o sistema de commit+push automatico (Git AutoSync) - status, horarios, diretorios monitorados, instalacao da tarefa agendada/cron e da tray. Cross-platform (Windows/Linux), auto-contido nesta pasta de skill.
---

Skill auto-contida: todo o codigo necessario esta em `scripts/` dentro desta mesma
pasta de skill (`app.py`, `autosync_core.py`, `gui.py`, `run_sync.py`). Essa pasta e
gerada pelo instalador do projeto (`installer/install.py`) a partir de `python/` no
repositorio `git-autosync` — nao edite os arquivos aqui na mao, edite o repositorio e
rode o instalador de novo.

Faz commit (mensagem gerada via `claude -p`) e push automatico em repositorios git
configurados, em horarios agendados (Task Scheduler no Windows / cron no Linux) e/ou
por um icone na bandeja do sistema.

Acionar esta skill quando o usuario pedir coisas como: "status do autosync", "rodar
autosync agora", "commitar sem dar push", "dar push do que ja foi commitado",
"adicionar repositorio ao autosync", "remover diretorio do autosync", "mudar horario
do autosync", "instalar o autosync", "configurar sync automatico de git", "ver
historico de commits do autosync", "ativar/desativar a tray do autosync", "ver log do
autosync", "abrir a interface do autosync".

## Pre-requisitos na maquina de quem for usar

- Python 3.9+ na PATH (`python` ou `python3`).
- Git na PATH.
- Opcional, so para GUI/tray: `pip install -r requirements.txt` (customtkinter +
  pystray + Pillow) dentro da pasta `scripts/` desta skill.
- Opcional: `claude` CLI na PATH, para gerar a mensagem de commit automaticamente; sem
  ela o script usa uma mensagem fallback (`chore: auto-commit <data>`).

Estado do usuario (config/alvos/log) fica sempre em `~/.git-autosync/` (fora da skill,
por pessoa) - nunca dentro da pasta da skill. Isso e o que torna a skill compartilhavel
sem vazar os diretorios/repos de quem a instalou originalmente.

## Como localizar o script (resolver antes de rodar qualquer comando)

Esta skill roda de dentro de `~/.claude/skills/git-autosync/scripts/` OU
`~/.codex/skills/git-autosync/scripts/` (ou `$CLAUDE_CONFIG_DIR`/`$CODEX_HOME` quando
configurados). Resolva o diretorio de config antes do primeiro comando:

**PowerShell (Windows):**
```powershell
$cfg = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR }
       elseif ($env:CODEX_HOME) { $env:CODEX_HOME }
       elseif (Test-Path "$env:USERPROFILE\.codex\skills\git-autosync") { "$env:USERPROFILE\.codex" }
       else { "$env:USERPROFILE\.claude" }
$script = Join-Path $cfg "skills\git-autosync\scripts\app.py"
python "$script" status --json
```

**Bash (Linux/macOS):**
```bash
cfg="${CLAUDE_CONFIG_DIR:-}"
[ -z "$cfg" ] && [ -n "${CODEX_HOME:-}" ] && cfg="$CODEX_HOME"
[ -z "$cfg" ] && [ -d "$HOME/.codex/skills/git-autosync" ] && cfg="$HOME/.codex"
[ -z "$cfg" ] && cfg="$HOME/.claude"
script="$cfg/skills/git-autosync/scripts/app.py"
python3 "$script" status --json
```

Use `$script` (ou `python "$script"` no Windows / `python3 "$script"` no Linux) no lugar
de `python app.py` nos comandos abaixo.

## Comandos

```
<python> "<script>" status --json
<python> "<script>" list
<python> "<script>" add "<caminho do repo>" --type repo      # ou --type root p/ pasta com varios repos
<python> "<script>" remove "<caminho do repo>"
<python> "<script>" set-schedule "12:00,17:30"
<python> "<script>" run-now                    # commit + push de verdade em TODOS os alvos configurados
<python> "<script>" commit-now                 # so verifica e commita, SEM push, em TODOS os alvos
<python> "<script>" push-now                    # so da push do que ja foi commitado, em TODOS os alvos
<python> "<script>" commit [--repo <caminho>]   # commit ad-hoc de UM repo (default: diretorio atual)
<python> "<script>" push [--repo <caminho>]     # push ad-hoc de UM repo (default: diretorio atual)
<python> "<script>" sync [--repo <caminho>]     # commit + push ad-hoc de UM repo (default: diretorio atual)
<python> "<script>" history --since 7d          # ou 30d / 90d / all, --repo <caminho>, --json
<python> "<script>" install            # so a tarefa agendada/cron
<python> "<script>" enable-tray        # tarefa agendada/cron + tray com autostart no login
<python> "<script>" disable-tray       # remove autostart da tray (mantem tarefa agendada)
<python> "<script>" uninstall          # remove tarefa agendada/cron + tray
<python> "<script>" log --lines 60
<python> "<script>" --version
```

GUI grafica (sidebar Status/Historico/Agendamento/Log): `<python> "<script>" --gui`.
Nao rode isso a partir desta skill sem avisar o usuario, pois abre uma janela
interativa — prefira sempre os subcomandos de CLI acima para responder no chat.

## Regras

- Sempre resolva o caminho completo do repo antes de Add/Remove (nao aceite caminho
  relativo ambiguo).
- `set-schedule` reescreve a tarefa agendada/cron inteira (idempotente); avise o
  usuario que os horarios antigos serao substituidos.
- Nunca edite `~/.git-autosync/status.json` ou `config.json` manualmente com Edit/Write
  - sempre pelos subcomandos, que sao a fonte de verdade e mantem o schema coerente.
- `run-now` executa commit **e** push de verdade nos repos configurados que tiverem
  mudancas pendentes — avise o usuario antes de rodar em um alvo que ele nao pediu
  explicitamente para sincronizar agora, ja que isso cria commits e publica de verdade.
  Se o usuario so quer revisar antes de publicar, prefira `commit-now` e pergunte antes
  de rodar `push-now` depois.
- Em maquina nova, apos instalar a skill: nao ha config previo. Primeiro comando
  ja cria `~/.git-autosync/config.json` vazio (sem alvos) - use `add` para configurar
  os diretorios da pessoa antes de `install`/`run-now`.
- Empacotamento em executavel standalone (PyInstaller, sem Python na maquina de
  destino): `scripts/build_windows.ps1` ou `scripts/build_linux.sh` (rodar no SO alvo,
  nao ha cross-compile). Isso e uma conveniencia a parte, nao e necessario para o uso
  via skill/chat.
