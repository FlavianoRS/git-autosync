"""Entry point invoked by the OS scheduler (Task Scheduler / cron). No GUI deps."""
import autosync_core as core

if __name__ == "__main__":
    status = core.run_all()
    for path, r in status["repos"].items():
        print(f"[{'OK' if r['success'] else 'ERRO'}] {path}: {r['message']}")
