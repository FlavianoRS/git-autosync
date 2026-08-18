---
name: git-autosync
version: 3.9.0
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
<python> "<script>" exclude "<caminho do repo>"    # tira 1 repo de dentro de um alvo root (nao remove a pasta)
<python> "<script>" include "<caminho do repo>"    # desfaz o exclude
<python> "<script>" set-schedule "12:00,17:30"
<python> "<script>" preview [--repo <caminho>] [--json]                            # gera a mensagem e mostra, SEM commitar nada
<python> "<script>" commit [--repo <caminho> | --all] [-m "mensagem" | --review]   # commita, sem push
<python> "<script>" push [--repo <caminho> | --all]                                # da push do que ja foi commitado
<python> "<script>" sync [--repo <caminho> | --all] [-m "mensagem" | --review]     # commit + push de verdade
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
- `-m "mensagem"` em `commit`/`sync` usa exatamente esse texto no commit, sem
  gerar nada via IA - use quando o usuario ditar a mensagem que quer no chat.
  Nao pode ser combinado com `--all`.
- `--review` (existe em `commit`/`sync`) exige terminal interativo pra
  perguntar `[S]/[E]/[C]` - rodando via chamada de ferramenta (o seu caso)
  isso sempre falha com "precisa de terminal interativo". NAO use `--review`.
- Quando o usuario quiser ver/editar a mensagem antes de commitar (e voce
  esta rodando via chamada de ferramenta, sem terminal interativo): use
  `preview` primeiro - ele gera a mensagem e mostra, sem commitar nem deixar
  nada staged (sempre desfaz o `git add` que faz internamente pra gerar).
  Mostre essa mensagem pro usuario no chat, deixe ele pedir ajuste se quiser,
  e só depois rode `commit -m "<mensagem final>"` (ou `sync -m "..."` se ele
  tambem quiser publicar). Nunca commite sem mostrar a mensagem gerada
  primeiro quando o pedido do usuario for algo como "deixa eu ver a
  mensagem antes"/"quero revisar o commit".
- `set-schedule` reescreve a tarefa agendada/cron inteira (idempotente); avise o
  usuario que os horarios antigos serao substituidos.
- Nunca edite `~/.git-autosync/status.json` ou `config.json` manualmente com Edit/Write
  - sempre pelos subcomandos, que sao a fonte de verdade e mantem o schema coerente.
- `sync` (com ou sem `--all`) executa commit **e** push de verdade nos repos
  que tiverem mudancas pendentes — avise o usuario antes de rodar num alvo
  que ele nao pediu explicitamente para sincronizar agora, ja que isso cria
  commits e publica de verdade. Se o usuario so quer revisar antes de
  publicar, prefira `commit` e pergunte antes de rodar `push` depois.
- `--repo <caminho>` e `--all` sao mutuamente exclusivos. Sem nenhum dos dois,
  `commit`/`push`/`sync` agem no diretorio atual (cwd de quem rodou o
  comando) — normalmente NAO e o que voce quer ao rodar via chat, prefira
  sempre `--repo <caminho completo>` ou `--all` explicito.
- `push`/`sync` verificam se o remoto esta acessivel ANTES de dar push (ou
  antes de commitar, no caso do `sync`). Se nao estiver e o comando estiver
  rodando com terminal interativo, ele PERGUNTA no proprio terminal
  (`[T] tentar novamente` / `[C] ...`) e fica esperando resposta ali mesmo —
  nao tem como essa pergunta ser respondida por voce, avise o usuario que
  precisa responder no terminal. Sem terminal interativo (chamado via
  script/tool call, que e o seu caso), ele so avisa e segue (commitando sem
  dar push, ou cancelando o push), sem travar.
- Em maquina nova, apos instalar a skill: nao ha config previo. Primeiro comando
  ja cria `~/.git-autosync/config.json` vazio (sem alvos) - use `add` para configurar
  os diretorios da pessoa antes de `install`/`sync --all`.
- Empacotamento em executavel standalone (PyInstaller, sem Python na maquina de
  destino): `scripts/build_windows.ps1` ou `scripts/build_linux.sh` (rodar no SO alvo,
  nao ha cross-compile). Isso e uma conveniencia a parte, nao e necessario para o uso
  via skill/chat.
