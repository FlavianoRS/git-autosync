# Changelog

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
