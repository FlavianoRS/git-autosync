"""Entry point invoked by the OS scheduler (Task Scheduler / cron). No GUI deps.

Este executavel NAO aceita argumento nenhum alem de `--version` e `--help`. Ate a
versao 4.0.0 ele ignorava `sys.argv` inteiro: quem chamasse `git-autosync-sync --version`
para descobrir a versao (instalador, diagnostico do hub) disparava uma sincronizacao de
verdade em todos os alvos configurados, com commit e push. Argumento desconhecido agora
sai com codigo 2 sem tocar em repositorio nenhum.
"""
import sys
from pathlib import Path

import autosync_core as core

USO = (
    "uso: git-autosync-sync [--version | --help]\n"
    "Sem argumento, sincroniza todos os alvos configurados (e o que o agendador chama).\n"
    "Para operar repositorios avulsos use o `git-autosync`."
)


def version():
    """VERSION de dentro do bundle PyInstaller, ou da pasta do fonte."""
    base = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    arquivo = base / "VERSION"
    if arquivo.exists():
        return arquivo.read_text(encoding="utf-8").strip()
    return "desconhecida"


def tratar_argumentos(argv):
    """`None` = pode sincronizar. Inteiro = codigo de saida, sem sincronizar."""
    if not argv:
        return None
    if argv in (["--version"], ["-V"]):
        print(f"git-autosync-sync {version()}")
        return 0
    if argv[0] in ("--help", "-h", "/?"):
        print(USO)
        return 0
    print(f"[ERRO] argumento nao reconhecido: {' '.join(argv)}\n{USO}", file=sys.stderr)
    return 2


def main(argv=None):
    core.force_utf8_stdio()
    codigo = tratar_argumentos(list(sys.argv[1:] if argv is None else argv))
    if codigo is not None:
        return codigo

    try:
        with core.file_lock(core.CONFIG_DIR / "batch.lock", timeout=0):
            status = core.run_all()
    except Exception as exc:
        print(f"[ERRO] {core.redact(str(exc))}", file=sys.stderr)
        return 1
    failures = []
    for path, r in status["repos"].items():
        print(f"[{'OK' if r['success'] else 'ERRO'}] {path}: {r['message']}")
        if not r.get("success"):
            failures.append(path)

    if failures:
        resumo = f"{len(failures)} repositorio(s) com erro na rodada agendada:\n" + "\n".join(
            p.rsplit("\\", 1)[-1].rsplit("/", 1)[-1] for p in failures[:5]
        )
        if len(failures) > 5:
            resumo += f"\n...e mais {len(failures) - 5}."
        core.notify_windows("Git AutoSync - falha na sincronizacao", resumo)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
