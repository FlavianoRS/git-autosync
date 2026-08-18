# Como instalar o Git AutoSync

Existem 3 formas de usar essa ferramenta. Você pode instalar mais de uma ao
mesmo tempo. Se não sabe qual escolher, veja a tabela abaixo.

| Forma | Pra quem é | O que faz |
|---|---|---|
| **1. Interface gráfica + bandeja** | Quem quer ver os repositórios, clicar em "commitar"/"push" e acompanhar visualmente | Abre uma janela com status de cada repositório, histórico de commits, e um ícone na bandeja do sistema |
| **2. CLI (linha de comando)** | Quem prefere terminal, ou já usa `git-autosync commit`/`push` dentro de um repo | Comandos de terminal, sem janela nenhuma |
| **3. Skill (Claude Code / Codex)** | Quem já usa Claude Code ou Codex e quer pedir por chat ("roda o autosync", "status do autosync") | A IA usa a ferramenta por trás dos panos, sem você digitar comando nenhum |

As três fazem a mesma coisa por baixo: verificam os repositórios configurados,
geram uma mensagem de commit e (se você deixar agendado) sobem pro remoto
sozinhas em um horário fixo.

## Passo a passo

1. Baixe/clone esta pasta (`git-autosync`) inteira na sua máquina.
2. Dê duplo clique (Windows) ou rode no terminal (Linux/macOS) o instalador:

   - **Windows**: duplo clique em **`instalar.bat`** (na raiz da pasta)
   - **Linux/macOS**: abra um terminal nesta pasta e rode `./instalar.sh`

3. Vai abrir um menu perguntando o que você quer instalar (pode marcar mais de
   uma opção, separando por vírgula: `1,2`):
   - `1` = Interface gráfica + bandeja
   - `2` = CLI
   - `3` = Skill (Claude Code/Codex)
4. Responda as perguntas seguintes (ele explica cada uma) e pronto — o
   instalador já prepara tudo: baixa o que falta, agenda a tarefa automática
   se você quiser, e cria atalho na área de trabalho.

## E se eu não tiver Python instalado?

Sem problema — o `instalar.bat`/`instalar.sh` detecta isso sozinho e te dá
duas saídas:

1. **Instalar o Python** — [python.org/downloads](https://www.python.org/downloads/).
   No Windows, marque a caixinha **"Add python.exe to PATH"** durante a
   instalação. Depois disso, roda o instalador de novo, agora funciona normal.

2. **Pedir a versão "pronta" pra alguém do time** — alguém que já tenha
   Python pode gerar dois arquivos executáveis (que não precisam de Python
   pra rodar) com:
   - Windows: `python\build_windows.ps1`
   - Linux: `./python/build_linux.sh`

   Isso gera `git-autosync.exe`/`git-autosync-sync.exe` (ou sem `.exe` no
   Linux) dentro de `python\dist\`. Copiando essa pasta `dist` pra dentro do
   `git-autosync` de quem não tem Python, o `instalar.bat`/`instalar.sh`
   detecta os arquivos prontos automaticamente e instala **sem precisar de
   Python nenhum** naquela máquina.

## Depois de instalar

- **GUI**: abre um atalho "Git AutoSync" na área de trabalho, ou peça pra
  alguém te mostrar onde ficou o `.exe`/script.
- **CLI**: abra um terminal e digite `git-autosync status` (se marcou a opção
  de adicionar ao PATH) ou use o caminho completo que o instalador mostrou no
  final.
- **Skill**: dentro do Claude Code/Codex, é só pedir em português mesmo:
  "adiciona esse repositório no autosync", "roda o autosync agora", "qual o
  status do autosync".

Em qualquer uma das três, o primeiro passo depois de instalar é **adicionar
os repositórios que você quer sincronizar** — a ferramenta não sincroniza
nada até você indicar quais pastas.

Mais detalhes técnicos (comandos completos, como funciona por dentro) estão
no [`README.md`](README.md).
