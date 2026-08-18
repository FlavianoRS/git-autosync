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

Guia simplificado (não-técnico) em [`COMO_INSTALAR.md`](COMO_INSTALAR.md).

- **Windows**: duplo clique em `instalar.bat`
- **Linux/macOS**: `./instalar.sh`

Esses scripts detectam Python automaticamente e chamam o instalador
(`installer/install.py`). Se não acharem Python instalado, caem pra versão
standalone (usa os `.exe`/binários já empacotados em `python/dist/`, sem
precisar de Python na máquina de destino — ver `COMO_INSTALAR.md`) ou
explicam como resolver.

Rodando o instalador Python direto:

```bash
python installer/install.py
```

Wizard interativo — deixa escolher, marcando mais de uma opção se quiser:

1. **Interface gráfica + tray** — cria um venv isolado em `~/.git-autosync/venv`,
   instala as dependências da GUI, oferece já habilitar a tarefa agendada/tray e
   criar um atalho na área de trabalho.
2. **CLI** — não precisa de dependência nenhuma além de Python + git; oferece
   instalar a tarefa agendada e cria o comando `git-autosync` (com opção de
   adicionar ao PATH), pra rodar de dentro de qualquer repositório.
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
- **Status** — um card **por repositório real** (um alvo tipo `root` aparece
  como 1 card por repositório git dentro da pasta, não 1 card pra pasta
  inteira): badge com quantos commits estão sem push (verde = tudo enviado,
  amarelo/vermelho = N commits à frente, cinza = sem remoto configurado),
  horário do último push, botões **Commitar**/**Push**/**Sincronizar**
  individuais (cada um agindo só naquele repositório), e uma seta pra
  expandir e ver as últimas mensagens de commit geradas. **Commitar** e
  **Sincronizar** abrem um diálogo pra digitar a mensagem do commit — deixe
  vazio pra gerar automaticamente (via IA, com fallback se não tiver). Cards
  que vieram de uma pasta `root` mostram "via pasta: `<caminho>`" e, no lugar
  de Ativar/Desativar/Remover, têm um botão **"Ignorar"** — tira só aquele
  repositório da varredura do root (equivalente ao `exclude` do CLI), sem
  apagar nada do disco nem remover a pasta-raiz inteira. No topo, "Commitar
  tudo"/"Push tudo"/"Sincronizar tudo" agem em todos de uma vez (sem diálogo
  de mensagem — sempre automática, já que é pra vários repositórios de uma
  vez).
  `Push`/`Sincronizar` verificam se o remoto está acessível antes — se não
  estiver, um popup oferece tentar de novo ou desistir (cancelar o push, ou
  seguir só commitando, dependendo do botão).
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
python app.py exclude <caminho-do-repo>   # exclui 1 repo de dentro de uma pasta-raiz (root)
python app.py include <caminho-do-repo>   # desfaz um exclude anterior
python app.py set-schedule "12:00,17:30"  # define horários e já reinstala a tarefa agendada
python app.py commit --all                # so verifica e commita, SEM push, em TODOS os alvos
python app.py push --all                  # so da push do que ja foi commitado, em TODOS os alvos
python app.py sync --all                  # commit + push de verdade em TODOS os alvos configurados
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

### Escopo: repo atual, outro repo, ou todos

`commit`/`push`/`sync` sempre agem sobre **um repositório**: o diretório atual
por padrão — não precisa estar cadastrado em `config.json` pra isso — ou outro
via `--repo`. Use `--all` pra agir sobre todos os alvos configurados de uma vez
(equivalente ao que antes eram `commit-now`/`push-now`/`run-now`):

```bash
cd caminho/do/repo
python app.py commit          # so commita esse repo (sem push)
python app.py push            # so da push desse repo
python app.py sync            # commit + push desse repo

python app.py commit --repo outro/caminho   # ou aponte pra outro repo, sem precisar entrar nele
python app.py sync --all                    # ou ignore o diretorio atual e rode em todos os alvos configurados

python app.py commit -m "fix: ajuste manual"   # mensagem customizada, no lugar da gerada automaticamente
python app.py sync -m "feat: nova tela"        # idem, pro commit dentro do sync
```

`--repo` e `--all` são mutuamente exclusivos. `-m`/`--message` não pode ser
usado com `--all` (uma mensagem só não serve pra vários repositórios de uma
vez) — sem `-m`, a mensagem é gerada automaticamente (via IA, com fallback se
não tiver). `push`/`sync` verificam se o remoto está acessível antes de dar
push (ou antes de commitar, no caso do `sync`) — se não estiver, perguntam
`[T] tentar novamente` / `[C]` no terminal (cancelar o push, ou seguir só
commitando, dependendo do comando).

Se instalou o componente CLI pelo `installer/install.py`, esses comandos ficam
disponíveis como `git-autosync commit|push|sync` de qualquer lugar do terminal
(o instalador cria o atalho e oferece adicionar ao PATH).

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

A rodada agendada (e os comandos `commit`/`sync`) fazem `git add -A` +
`git commit` automaticamente, sem revisão humana, e enviam o diff (até 12000
caracteres) pro `claude` CLI pra gerar a mensagem de commit. `sync`/`push` e o
botão "Push tudo"/tarefa agendada também dão `push` de verdade. Não aponte para
repositórios onde isso seja um problema (ex: diffs com segredos/credenciais que
não deveriam sair da máquina, ou onde publicar sem revisão não é aceitável).

## Estrutura do projeto

```
instalar.bat / instalar.sh   ponto de entrada (detecta Python, cai pra standalone se faltar)
COMO_INSTALAR.md             guia simples pro time, nao-tecnico
python/                      versao atual (Windows + Linux): core, CLI, GUI (customtkinter)
installer/                   wizard de instalacao (GUI/CLI/Skill) + fallback standalone (sem Python)
skill/                       fonte versionada da skill do Claude Code/Codex (copiada pelo instalador)
legacy/                      versao original em PowerShell (Windows-only, referencia historica)
```

Ver `CHANGELOG.md` para o histórico de versões.
