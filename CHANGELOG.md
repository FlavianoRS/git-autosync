# Changelog

## 3.8.0

- **Comando `preview`**: gera a mensagem de commit e mostra, sem commitar
  nem deixar nada staged (sempre desfaz o `git add` interno). Pensado pra
  quem chama via skill do Claude Code/Codex (sem terminal interativo pro
  `--review` funcionar) — a IA mostra a mensagem no chat, o usuário pede
  ajuste se quiser, e ela confirma com `commit -m "..."`/`sync -m "..."`.

## 3.7.0

- **Revisar/editar a mensagem gerada antes de commitar (e antes do push)**:
  - GUI: **Commitar**/**Sincronizar** agora abrem um diálogo que já mostra a
    mensagem gerada (via IA/fallback) pronta pra editar — confirma pra
    commitar (e enviar, no caso do Sincronizar) com o texto final; cancelar
    desfaz o staging, sem commitar nada.
  - CLI: `commit --review` / `sync --review` — mostra a mensagem gerada e
    pergunta `[S] usar essa` `[E] editar` `[C] cancelar` no terminal (exige
    terminal interativo; não combina com `--all`/`--message`).
  - Novo em `autosync_core.py`: `stage_and_generate_message()` (stage +
    gera, sem commitar), `finalize_commit()`/`finalize_sync()` (commita o
    que já foi revisado, com ou sem push) e `unstage()` (desfaz ao
    cancelar).

## 3.6.0

- **Mensagem de commit customizada** (commit/sync individuais, GUI e CLI) —
  antes só dava pra usar a mensagem gerada via IA/fallback. Agora:
  - CLI: `commit -m "..."` / `sync -m "..."` (não combina com `--all`).
  - GUI: **Commitar**/**Sincronizar** abrem um diálogo pra digitar a
    mensagem — vazio continua gerando automaticamente.
  - Ações em lote (`--all`, "Commitar tudo" etc) continuam sempre
    automáticas, sem diálogo — não faz sentido uma mensagem só pra vários
    repositórios.
- **Renomeado**: botão "Excluir da pasta" → **"Ignorar"** (o nome antigo
  dava a entender que apagaria a pasta do disco; não apaga nada, só tira o
  repositório da varredura do `root`).

## 3.5.1

- **Fix**: botão "Excluir da pasta" (GUI) não fazia nada quando o `path` do
  alvo `root` no `config.json` usava `/` em vez de `\` — comparação de
  string exata nunca dava match. `exclude_repo_from_root`/
  `include_repo_in_root` agora comparam via `Path(...) == Path(...)`.

## 3.5.0

- **Exclusão de repositórios dentro de um alvo `root`**: até aqui, um alvo
  tipo `root` (pasta com vários repos) sincronizava tudo que tivesse `.git`
  lá dentro, sem exceção. Agora dá pra excluir repositórios específicos:
  - CLI: `python app.py exclude <caminho-do-repo>` / `include <caminho>`
    (desfaz).
  - GUI: botão **"Excluir da pasta"** nos cards que vêm de um `root`
    (Status/Histórico), no lugar de Ativar/Remover.
  - Guardado em `exclude: [...]` no próprio alvo `root` do `config.json`.

## 3.4.0

- **Fix**: GUI mostrava só 1 card pra um alvo tipo `root` (a pasta inteira,
  que nem é repositório git) em vez de 1 card por repositório real dentro
  dela — sem controle individual de commit/push por repo. Status e Histórico
  agora resolvem os alvos de verdade (`resolve_targets_detailed`, novo em
  `autosync_core.py`): cada repositório dentro de uma pasta `root` ganha seu
  próprio card, com Commitar/Push/Sincronizar isolados nele. Esses cards
  mostram "via pasta: `<caminho>`" e não têm Ativar/Remover — quem controla é
  a pasta-raiz (`python app.py remove <pasta>`), não o repositório.
- **Push-only também verifica conexão antes** (GUI e CLI) — antes só o fluxo
  de commit+push (`sync`) fazia essa checagem; agora `push_repo_checked`
  cobre push puro também, com popup/prompt "Cancelar" no lugar de "Apenas
  commit" (não há commit num push isolado).
- **CLI consolidado**: `commit-now`/`push-now`/`run-now` saem de cena.
  `commit`/`push`/`sync` continuam agindo no repositório atual por padrão
  (ou `--repo <caminho>`), e ganham `--all` pra agir em todos os alvos
  configurados — um jeito só de escrever cada ação, com o mesmo "onde" pra
  todo mundo. Não afeta a tarefa agendada (chama `core.run_all()` direto,
  nunca passou pelo parser de comandos).

## 3.3.1

- **Fix**: o fix de icone da 3.3.0 (reaplicar `iconbitmap`) nao resolvia
  quando a GUI roda via `python app.py`/tray em vez do atalho instalado — a
  barra de tarefas continuava mostrando o icone generico de arquivo
  `.py`/`.pyw`. Causa real: sem um `AppUserModelID` explicito, o Windows
  agrupa a janela pelo host do processo (`pythonw.exe`) ou pelo icone do
  arquivo executado, ignorando o icone que a janela define. Adicionado
  `SetCurrentProcessExplicitAppUserModelID` no início da GUI (fix padrao
  documentado pra apps Python/Tk no Windows).

## 3.3.0

- **Fix**: icone da janela sumia da barra de tarefas depois de abrir (bug
  conhecido do customtkinter, que reseta o icone apos redesenhar o tema) —
  agora reaplica de novo em alguns momentos seguidos e usa
  `iconbitmap(default=...)`, mais robusto pro Windows.
- **Verificacao de push antes de commitar**: `sync_repo`/`run_all` (usados
  pela tarefa agendada, `run-now` e o novo comando `sync`) checam se o
  remoto esta acessivel ANTES de gerar o commit.
  - **Rodada agendada** (sem ninguem pra responder): tenta de novo sozinha
    algumas vezes e, se continuar sem acesso, segue so commitando — nunca
    trava esperando resposta.
  - **CLI** (`run-now`, `sync`, com terminal interativo): pergunta direto no
    terminal, `[T] tentar novamente` / `[C] apenas commit`.
  - **GUI**: novo botao "Sincronizar" (por repositorio e "Sincronizar tudo"
    no topo da aba Status) — mostra um popup com os mesmos dois botoes.
  - Corrigido de brinde: no Windows, o `timeout` do `subprocess` nao
    derrubava de fato um `git` tentando alcancar um remoto sem resposta
    (ficava pendurado ~20s+ mesmo pedindo poucos segundos, por causa de um
    processo auxiliar de rede que herdava os pipes) — agora mata a arvore de
    processos inteira quando o tempo esgota.
- **Icone da bandeja** reaproveita o mesmo desenho do icone do projeto
  (circulo + duas flechas de sync), so trocando a cor pelo status, em vez de
  uma bolinha lisa sem relacao visual com o resto do app.

## 3.2.0

- **Ponto de entrada único**: `instalar.bat` (Windows) / `instalar.sh`
  (Linux/macOS) na raiz do projeto — detecta Python automaticamente e chama o
  instalador; sem Python, cai pra instalação **standalone**.
- **Instalador standalone** (`installer/install_standalone.bat`/`.sh`): instala
  a partir dos binários já empacotados em `python/dist/` (gerados uma vez por
  alguém com Python via `build_windows.ps1`/`build_linux.sh`) — tarefa
  agendada, tray e atalho, tudo **sem exigir Python** na máquina de quem só
  vai instalar.
- **`COMO_INSTALAR.md`** na raiz: guia não-técnico explicando as 3 formas
  (GUI, CLI, Skill) e o que fazer sem Python instalado.

## 3.1.0

- **Fix**: diálogo "Adicionar repositório" tinha o botão "Adicionar" cortado
  (janela baixa demais pro conteúdo — agora com altura suficiente).
- **Comando `git-autosync` no PATH**: o instalador (opção CLI) cria um atalho
  chamado `git-autosync` (não mais `python app.py`) e oferece adicionar ao PATH
  do usuário, pra chamar de qualquer terminal.
- **Ações ad-hoc em um repositório só**: `commit`/`push`/`sync` (com `--repo`
  opcional, default o diretório atual) — não precisa cadastrar o repositório em
  `config.json` primeiro. Diferente de `commit-now`/`push-now`/`run-now`, que
  continuam agindo sobre todos os alvos configurados.
- **Ícone próprio** (`python/assets/icon.ico`/`icon.png`, gerado do zero com
  PIL — sem depender de nenhum asset de terceiros): usado na janela da GUI, no
  executável empacotado e no atalho criado pelo instalador.
- **Fix de build**: `build_windows.ps1`/`build_linux.sh` estavam gerando o
  executável direto de `app.py`, ignorando os `.spec` versionados (então
  `VERSION`/ícone/hiddenimports nunca eram de fato embutidos) — agora usam
  `git-autosync.spec`/`git-autosync-sync.spec`.

## 3.0.0

Redesign pra compartilhar a ferramenta com o time de desenvolvimento.

- **GUI reescrita** em customtkinter: sidebar (Status / Histórico / Agendamento /
  Log + Adicionar repositório) substituindo as 3 abas do Tkinter antigo.
- **Commit e push separados** nas ações manuais: `commit-now`/botão "Commitar"
  só verifica e commita; `push-now`/botão "Push" publica o que já foi commitado.
  A rodada agendada continua fazendo commit + push automaticamente, sem mudança.
- **Histórico**: comando `history` e aba correspondente na GUI, lendo o `git log`
  real de cada repositório configurado (com filtro de período), sem duplicar
  estado em arquivo próprio.
- **Indicador visual** por repositório: badge com quantos commits estão sem
  push e horário do último push (novo campo `lastPush` no `status.json`).
- **Sem flash de console no Windows**: todo subprocesso (`git`, `claude`,
  `schtasks`) roda com `CREATE_NO_WINDOW`; adicionado `gui_launcher.pyw` pra
  abrir a GUI com duplo clique sem passar pelo console.
- **Instalador** (`installer/install.py`): wizard único que deixa escolher
  Interface gráfica / CLI / Skill (Claude Code ou Codex) — pode marcar mais de
  um — e prepara o ambiente (venv, dependências, tarefa agendada, tray, atalho
  de área de trabalho, cópia da skill).
- **Skill versionada no repositório** (`skill/SKILL.md`), substituindo a cópia
  manual solta em `~/.claude/skills/git-autosync` que já tinha divergido do
  código real.
- Reorganização de repositório: versão PowerShell movida para `legacy/`, estado
  pessoal (`config.json`/`status.json`/`autosync.log`) tirado do controle de
  versão, `README.md` novo.
