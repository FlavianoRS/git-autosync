"""Entry point invoked by the OS scheduler (Task Scheduler / cron). No GUI deps."""
import sys
import autosync_core as core

def main():
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
