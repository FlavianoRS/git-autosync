# Git AutoSync

Ferramenta que varre repositórios git configurados e, quando encontra alterações,
gera uma mensagem de commit (via `claude` CLI, com fallback automático), faz commit
e dá `push`. A rodada **agendada** (Task Scheduler/cron) faz commit + push sozinha,
sem intervenção. As ações **manuais** (GUI ou CLI) vêm separadas: primeiro commita
(pra você revisar a mensagem gerada), depois você decide se dá push.

Versão atual e mantida: **`python/`** (multiplataforma — Windows e Linux).
`legacy/` guarda a versão original em PowerShell (Windows-only), mantida só como
referência histórica. Não desenvolva features novas nela.

## Instalação rápida (recomendada)

```bash
python installer/install.py
```

Wizard interativo — deixa escolher, marcando mais de uma opção se quiser:

1. **Interface gráfica + tray** — cria um venv isolado em `~/.git-autosync/venv`,
   instala as dependências da GUI, oferece já habilitar a tarefa agendada/tray e
   criar um atalho na área de trabalho.
2. **CLI** — não precisa de dependência nenhuma além de Python + git; oferece
   instalar só a tarefa agendada, sem GUI.
3. **Skill (Claude Code / Codex)** — copia os scripts + `SKILL.md` pra
   `~/.claude/skills/git-autosync` (e `~/.codex/skills/git-autosync` se detectar
   Codex instalado), pra usar a ferramenta via chat.

Roda igual em Windows e Linux.

## Requisitos (se for rodar sem o instalador)

- Python 3.9+
- `git` no PATH
- (opcional, mas recomendado) [`claude` CLI](https://docs.claude.com/claude-code) no PATH,
  usado para gerar a mensagem de commit a partir do diff. Sem ele, cai no fallback
  `chore: auto-commit <data/hora>`.
- Linux: `python3-tk` e um backend de tray do ambiente gráfico (AppIndicator/GTK no
  GNOME, ou equivalente no KDE/XFCE) para o ícone da bandeja funcionar.

```bash
cd python
pip install -r requirements.txt   # so necessario pra GUI/tray (customtkinter, pystray, Pillow)
python app.py                     # abre a GUI
python app.py --tray              # abre so o icone da bandeja
python app.py status              # linha de comando, sem GUI
```

No Windows, pra abrir a GUI sem passar pelo console, use `pythonw` ou dê duplo
clique em `python/gui_launcher.pyw`.

## Interface gráfica

Sidebar com:

- **+ Adicionar repositório** — abre um diálogo (caminho + tipo repo/root).
- **Status** — um card por repositório: badge com quantos commits estão sem push
  (verde = tudo enviado, amarelo/vermelho = N commits à frente, cinza = sem
  remoto configurado), horário do último push, botões **Commitar**/**Push**
  individuais, e uma seta pra expandir e ver as últimas mensagens de commit
  geradas. No topo, "Commitar tudo" e "Push tudo" pra agir em todos de uma vez.
- **Histórico** — os mesmos cards em modo leitura, com filtro de período
  (7 dias / 30 dias / 90 dias / tudo), expansíveis pra ver o log completo de cada
  repositório.
- **Agendamento** — só configuração/monitoramento (horários, tarefa agendada,
  tray). Não tem botão de commit/push manual aqui de propósito: a rodada
  agendada já faz isso sozinha por definição.
- **Log** — últimas linhas do log de execução.

## Uso via linha de comando

```bash
python app.py list                        # mostra alvos e horários configurados
python app.py add <caminho> --type repo   # adiciona um repositório
python app.py add <caminho> --type root   # adiciona uma pasta-raiz (sincroniza todo repo git dentro dela)
python app.py remove <caminho>
python app.py set-schedule "12:00,17:30"  # define horários e já reinstala a tarefa agendada
python app.py run-now                     # commit + push de verdade (mesmo comportamento da tarefa agendada)
python app.py commit-now                  # so verifica e commita, SEM push
python app.py push-now                    # so da push do que ja foi commitado
python app.py history --since 7d          # 7d | 30d | 90d | all, --repo <caminho>, --json
python app.py status [--json]             # resultado da ultima rodada
python app.py log [--lines 40]            # mostra o final do log
python app.py install                     # instala/atualiza a tarefa agendada (Task Scheduler/cron)
python app.py uninstall                   # remove tarefa agendada e autostart da tray
python app.py enable-tray                 # instala tarefa agendada + autostart da bandeja no login
python app.py disable-tray
python app.py --version
```

Sem nenhum argumento, `python app.py` abre a GUI — pensado pra quem só quer dar
duplo clique.

## Configuração e dados

Tudo fica em `~/.git-autosync/` (por usuário, não versionado):

- `config.json` — alvos monitorados, horários, nome da tarefa agendada
- `status.json` — resultado da última sincronização por repositório (incluindo
  `lastPush`)
- `autosync.log` — histórico de execuções

Histórico de commits (aba Histórico / comando `history`) não fica em nenhum
arquivo próprio — é lido direto do `git log` de cada repositório configurado, já
que a mensagem exibida É a mensagem gerada (é o que foi commitado).

`legacy/config.example.json` mostra o formato antigo (PowerShell) — sirva só de
referência, não é importado automaticamente pela versão Python.

## Credenciais do git

A ferramenta sempre chama o `git` do sistema (`subprocess`, dentro da pasta do
próprio repositório) — nunca guarda nem manuseia credencial própria. Ela reusa o
que já estiver configurado na máquina de quem a executa: Git Credential Manager
no Windows, agente SSH, token HTTPS em cache, `.netrc`, etc. Se `git push`
funciona manual naquele repositório, funciona pelo autosync também.

## Empacotando como executável standalone

Pra distribuir pro time sem exigir Python instalado na máquina de destino:

```bash
# Windows (rodar no Windows)
powershell -File python/build_windows.ps1

# Linux (rodar em um Linux de verdade — PyInstaller não faz cross-compile)
./python/build_linux.sh
```

Gera em `python/dist/`:
- `git-autosync` (ou `.exe`) — GUI + tray + CLI
- `git-autosync-sync` (ou `.exe`) — usado pela tarefa agendada, roda silencioso e loga em arquivo

## Aviso de segurança

A rodada agendada (e os comandos `run-now`/`commit-now`) fazem `git add -A` +
`git commit` automaticamente, sem revisão humana, e enviam o diff (até 12000
caracteres) pro `claude` CLI pra gerar a mensagem de commit. `run-now` e o botão
"Push tudo"/tarefa agendada também dão `push` de verdade. Não aponte para
repositórios onde isso seja um problema (ex: diffs com segredos/credenciais que
não deveriam sair da máquina, ou onde publicar sem revisão não é aceitável).

## Estrutura do projeto

```
python/       versao atual (Windows + Linux): core, CLI, GUI (customtkinter)
installer/    wizard de instalacao (GUI/CLI/Skill)
skill/        fonte versionada da skill do Claude Code/Codex (copiada pelo instalador)
legacy/       versao original em PowerShell (Windows-only, referencia historica)
```

Ver `CHANGELOG.md` para o histórico de versões.
