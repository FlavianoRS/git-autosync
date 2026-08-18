# Git AutoSync

Ferramenta que varre repositórios git configurados, e quando encontra alterações:
gera uma mensagem de commit (via `claude` CLI, com fallback automático), faz commit
e dá `push` — tudo sozinho, em horários agendados ou sob demanda.

Versão atual e mantida: **`python/`** (multiplataforma — Windows e Linux).
`legacy/` guarda a versão original em PowerShell (Windows-only), mantida só como
referência histórica. Não desenvolva features novas nela.

## Requisitos

- Python 3.9+
- `git` no PATH
- (opcional, mas recomendado) [`claude` CLI](https://docs.claude.com/claude-code) no PATH,
  usado para gerar a mensagem de commit a partir do diff. Sem ele, cai no fallback
  `chore: auto-commit <data/hora>`.
- Linux: `python3-tk` e um backend de tray do ambiente gráfico (AppIndicator/GTK no
  GNOME, ou equivalente no KDE/XFCE) para o ícone da bandeja funcionar.

## Instalação (rodando com Python)

```bash
cd python
pip install -r requirements.txt
python app.py            # abre a GUI (Tkinter)
python app.py --tray     # abre só o ícone da bandeja
python app.py status     # linha de comando, sem GUI
```

## Uso via linha de comando

```bash
python app.py list                     # mostra alvos e horários configurados
python app.py add <caminho> --type repo   # adiciona um repositório
python app.py add <caminho> --type root   # adiciona uma pasta-raiz (sincroniza todo repo git dentro dela)
python app.py remove <caminho>
python app.py set-schedule "12:00,17:30"  # define horários e já reinstala a tarefa agendada
python app.py run-now                  # roda a sincronização imediatamente
python app.py status [--json]          # mostra o resultado da última rodada
python app.py log [--lines 40]         # mostra o final do log
python app.py install                  # instala/atualiza a tarefa agendada (Task Scheduler/cron)
python app.py uninstall                # remove tarefa agendada e autostart da tray
python app.py enable-tray              # instala tarefa agendada + autostart da bandeja no login
python app.py disable-tray
```

Sem nenhum argumento, `python app.py` abre a GUI — pensado pra quem só quer dar
duplo clique.

## Configuração e dados

Tudo fica em `~/.git-autosync/` (por usuário, não versionado):

- `config.json` — alvos monitorados, horários, nome da tarefa agendada
- `status.json` — resultado da última sincronização por repositório
- `autosync.log` — histórico de execuções

`legacy/config.example.json` mostra o formato antigo (PowerShell) — sirva só de
referência, não é importado automaticamente pela versão Python.

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

O sync faz `git add -A` + `git commit` + `git push` automaticamente, sem revisão
humana, e envia o diff (até 12000 caracteres) pro `claude` CLI pra gerar a
mensagem de commit. Não aponte para repositórios onde isso seja um problema
(ex: diffs com segredos/credenciais que não deveriam sair da máquina, ou onde
push automático sem revisão não é aceitável).

## Estrutura do projeto

```
python/     versão atual (Windows + Linux)
legacy/     versão original em PowerShell (Windows-only, referência histórica)
```
