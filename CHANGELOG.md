# Changelog

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
