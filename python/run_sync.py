"""Entry point invoked by the OS scheduler (Task Scheduler / cron). No GUI deps."""
import autosync_core as core

if __name__ == "__main__":
    status = core.run_all()
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
