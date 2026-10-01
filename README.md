# Git AutoSync

Ferramenta que varre repositórios git configurados e, quando encontra alterações,
gera uma mensagem de commit localmente ou, com autorização explícita, via
**Claude, Codex ou OpenCode**, faz commit e dá `push`. A rodada
**agendada** (Task Scheduler/cron) faz commit + push sozinha, sem intervenção. As
ações **manuais** (GUI ou CLI) vêm separadas: primeiro commita (pra você revisar a
mensagem gerada), depois você decide se dá push.

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

O instalador Python copia primeiro uma release versionada e identificada pelo
conteúdo para `~/.git-autosync/releases/`. CLI, tray, atalhos e tarefa agendada
apontam para essa cópia, não para o checkout que pode ser movido ou alterado.
Uma release já existente só é reutilizada se sua integridade conferir. Para
reinstalar uma cópia existente: `python installer/install.py --release <id>`.

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
  **Sincronizar** abrem um diálogo que já mostra a mensagem gerada
  automaticamente (fallback local ou IA autorizada) — revise, edite se
  quiser, e só então confirme. A prévia usa índice Git privado: cancelar não
  altera o stage que já existia. Cards que vieram de uma pasta `root` mostram "via
  pasta: `<caminho>`" e, no lugar
  de Ativar/Desativar/Remover, têm um botão **"Ignorar"** — tira só aquele
  repositório da varredura do root (equivalente ao `exclude` do CLI), sem
  apagar nada do disco nem remover a pasta-raiz inteira. No topo, "Commitar
  tudo"/"Push tudo"/"Sincronizar tudo" agem em todos de uma vez (sem diálogo
  de mensagem — sempre automática, já que é pra vários repositórios de uma
  vez).
  `Push`/`Sincronizar` verificam se o remoto está acessível antes — se não
  estiver, um popup oferece tentar de novo ou desistir (cancelar o push, ou
  seguir só commitando, dependendo do botão). Botão **▤ Lista / ▦ Cards** no
  topo troca entre dois layouts — preferência salva no `config.json`
  (`viewMode`): **Cards** organiza numa grade horizontal (vários por linha,
  nome no topo/badges no meio/botões na base); **Lista** é uma linha
  compacta por repositório.
- **Histórico** — os mesmos cards em modo leitura, com filtro de período
  (7 dias / 30 dias / 90 dias / tudo), expansíveis pra ver o log completo de
  cada repositório, com o mesmo alternador Lista/Cards.
- **Agendamento** — só configuração/monitoramento (horários, tarefa agendada,
  tray). Não tem botão de commit/push manual aqui de propósito: a rodada
  agendada já faz isso sozinha por definição.
- **Log** — últimas linhas do log de execução.

No fim da sidebar tem um seletor **Tema: Sistema / Claro / Escuro** — troca a
aparência na hora, sem reiniciar, e salva a escolha (`theme` no
`config.json`).

Na aba **Agendamento** também há autorização de envio do diff e seletor de
**Agente de IA** (Automático / Claude / Codex / OpenCode) — ver seção abaixo.

## Mensagem de commit e IA

Envio de diff à IA vem **desabilitado por padrão**. Nesse modo, mensagens
automáticas usam o fallback local `chore: auto-commit <data/hora>`. Ative
explicitamente na GUI ou com `set-ai on`; `set-ai off` revoga a autorização.

Quando autorizado, suporta **Claude**, **Codex** e **OpenCode** — detecta o que estiver instalado
e usa (ordem padrão: Claude → Codex → OpenCode), ou force um deles em
"Agente de IA" na aba Agendamento da GUI, `set-agent` no CLI, ou `--agent` só
numa chamada. Os três são chamados com o diff já embutido no prompt (nunca
pedimos pra eles "olharem o repositório"), então nenhum precisa de acesso a
arquivo/shell pra responder:

- **Claude**: `claude -p ... --disallowedTools ...` — sem ferramenta nenhuma.
- **Codex**: `codex exec --sandbox read-only` — só leitura, sem escrita/execução.
- **OpenCode**: usa um agente restrito (`git-autosync-safe`, sem
  write/edit/bash/webfetch) que o próprio git-autosync cria/mantém em
  `~/.config/opencode/opencode.json` (sem substituir configuração válida existente).

Antes do envio, arquivos sensíveis conhecidos, possíveis chaves/tokens e
arquivos acima do limite são bloqueados. Políticas por repositório podem limitar
branches, inclusões, exclusões, tamanho de arquivo e autorização de IA. O diff
enviado é limitado a 12.000 caracteres e não usa filtros externos do Git.

**Quando o agendamento é criado através de uma skill** (Claude Code/Codex
rodando `install`/`set-schedule` via chat), a rodada agendada fica fixada
nesse mesmo agente — não na preferência geral, que pode nunca ter sido
configurada. Isso acontece uma vez só, na primeira criação; pra mudar depois,
use "Limpar" na aba Agendamento ou edite `scheduleAgent` com `set-agent`.

## Aviso de falha na rodada agendada

Se algum repositório falhar na rodada agendada (`run_sync.py`), o Windows
mostra um balão de notificação nativo com quantos/quais falharam — não
depende da GUI ou da tray estarem abertas. Sem isso, dá pra ver os detalhes
igual antes, em `~/.git-autosync/autosync.log` ou `python app.py status`.

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
python app.py set-agent codex             # preferencia geral de agente: auto | claude | codex | opencode
python app.py set-ai on                    # autoriza envio de diff a IA; use off para revogar
python app.py set-policy --repo <repo> --branch "feature/*" --exclude "secrets/*"
python app.py set-policy --repo <repo> --max-file-bytes 1048576 --ai off
python app.py doctor                       # valida Git, configuracao, repos e agendamento
python app.py doctor --network             # inclui teste de acesso aos remotos
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

python app.py commit --review   # mostra a mensagem gerada, deixa usar/editar/cancelar antes de commitar
python app.py sync --review     # idem, e só dá push depois de confirmar

python app.py preview            # so gera e mostra a mensagem, sem commitar nada (nem deixa staged)

python app.py commit --agent opencode   # forca um agente so nesta chamada (nao altera a preferencia salva)
```

Em `--review`, escolher `[E] editar` abre seu editor de texto de verdade
(`$GIT_EDITOR`/`$EDITOR`, com fallback pro Notepad no Windows ou `nano` no
Linux/macOS) num arquivo temporário pré-preenchido — igual o `git commit`
tradicional — em vez de digitar tudo numa linha só.

`--repo` e `--all` são mutuamente exclusivos. `-m`/`--message` e `--review`
não podem ser usados com `--all` (uma mensagem/revisão só não serve pra
vários repositórios de uma vez), e são mutuamente exclusivos entre si.
`--review` precisa de terminal interativo — pra revisar sem um terminal de
verdade (ex: pedindo pela skill do Claude Code/Codex, via chat), use
`preview` pra ver a mensagem gerada e depois `commit -m "..."`/`sync -m "..."`
com a versão final. Sem `-m`/`--review`, a mensagem é gerada automaticamente
(fallback local ou IA autorizada). `push`/`sync` verificam se o remoto
está acessível antes de dar push (ou antes de
commitar, no caso do `sync`) — se não estiver, perguntam `[T] tentar
novamente` / `[C]` no terminal (cancelar o push, ou seguir só commitando,
dependendo do comando).

Commit criado sem push confirmado não é sucesso: fica como `pending_push`, o
comando retorna código diferente de zero e a GUI/status mostram falha pendente.
Uma rodada posterior tenta enviar commits locais mesmo quando não há novas
alterações. Falhas conhecidas de upstream/non-fast-forward oferecem correção
somente em fluxos interativos; execução agendada apenas registra a sugestão.

Se instalou o componente CLI pelo `installer/install.py`, esses comandos ficam
disponíveis como `git-autosync commit|push|sync` de qualquer lugar do terminal
(o instalador cria o atalho e oferece adicionar ao PATH).

## Configuração e dados

Tudo fica em `~/.git-autosync/` (por usuário, não versionado):

- `config.json` — alvos monitorados, horários, nome da tarefa agendada
- `status.json` — resultado da última sincronização por repositório (incluindo
  `lastPush`)
- `autosync.log` — histórico de execuções
- `releases/` — cópias instaladas, versionadas e identificadas pelo conteúdo

Escritas de configuração/status são atômicas e protegidas contra concorrência.
Logs têm rotação e remoção de tokens reconhecíveis. Para testes/automação, use
`GIT_AUTOSYNC_HOME` para isolar todo estado da aplicação.

Histórico de commits (aba Histórico / comando `history`) não fica em nenhum
arquivo próprio — é lido direto do `git log` de cada repositório configurado, já
que a mensagem exibida É a mensagem gerada (é o que foi commitado).

`legacy/config.example.json` mostra o formato antigo (PowerShell) — sirva só de
referência, não é importado automaticamente pela versão Python.

## Credenciais

A ferramenta sempre chama o `git` do sistema (`subprocess`, dentro da pasta do
próprio repositório) — nunca guarda nem manuseia credencial própria. Ela reusa o
que já estiver configurado na máquina de quem a executa: Git Credential Manager
no Windows, agente SSH, token HTTPS em cache, `.netrc`, etc. Se `git push`
funciona manual naquele repositório, funciona pelo autosync também.

Para criar Merge Requests no GitLab, salve token vinculado ao host:

```bash
python app.py set-gitlab-token --host gitlab.empresa.com
python app.py mr --repo <repo> --target main
python app.py set-gitlab-token --clear
```

No Windows, token é protegido por DPAPI. No Linux, usa Secret Service via
`secret-tool`. Alternativamente, defina juntas
`GIT_AUTOSYNC_GITLAB_TOKEN` e `GIT_AUTOSYNC_GITLAB_HOST`; token só será usado
para host exatamente autorizado. Token legado em texto puro é recusado.

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

## Segurança operacional

A rodada agendada faz commit e push sem revisão humana. Cada repositório possui
lock entre processos; operações Git em andamento, conflitos, HEAD destacado,
políticas violadas e arquivos sensíveis bloqueiam o commit inteiro. O índice
real do usuário é preservado em cancelamentos e falhas. Ainda assim, configure
políticas adequadas e não monitore repositórios onde publicação automática seja
inaceitável.

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

## Licença

MIT — uso livre, inclusive comercial, sem garantia. Ver [LICENSE](LICENSE).
