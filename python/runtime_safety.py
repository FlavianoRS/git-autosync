"""Small, standard-library-only primitives shared by all entry points."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time

_locks = {}
_guard = threading.Lock()
_held = threading.local()


@contextlib.contextmanager
def file_lock(path, timeout=10):
    """Reentrant within a thread; OS locks are released even after a crash."""
    path = Path(path)
    key = os.path.normcase(str(path.resolve()))
    with _guard:
        local = _locks.setdefault(key, threading.RLock())
    if not local.acquire(timeout=timeout):
        raise RuntimeError("Outra operacao esta em andamento; tente novamente.")
    held = getattr(_held, "paths", None)
    if held is None:
        held = _held.paths = set()
    try:
        if key in held:
            yield
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a+b") as handle:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            deadline = time.monotonic() + timeout
            while True:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Outra instancia esta usando este recurso.")
                    time.sleep(0.05)
            held.add(key)
            try:
                yield
            finally:
                held.remove(key)
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        local.release()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Snapshot(dict):
    """Remember the baseline so stale GUI snapshots cannot overwrite new fields."""
    def __init__(self, value):
        super().__init__(value)
        self.baseline = json.loads(json.dumps(value))


def merge_snapshot(current, snapshot):
    if not isinstance(snapshot, Snapshot):
        return dict(snapshot)
    result = dict(current)
    for key in snapshot.baseline.keys() | snapshot.keys():
        before = snapshot.baseline.get(key)
        after = snapshot.get(key)
        if before == after and (key in snapshot.baseline) == (key in snapshot):
            continue
        if isinstance(before, dict) and isinstance(after, dict) and isinstance(current.get(key), dict):
            nested = Snapshot(before)
            nested.clear()
            nested.update(after)
            result[key] = merge_snapshot(current[key], nested)
            continue
        if current.get(key) != before and current.get(key) != after:
            raise RuntimeError(f"Configuracao alterada por outra instancia: {key}. Recarregue a tela.")
        if key in snapshot:
            result[key] = after
        else:
            result.pop(key, None)
    return result


def redact(text):
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", str(text))
    text = re.sub(r"\b(?:glpat-|ghp_|github_pat_)[A-Za-z0-9_-]+", "[redacted]", text)
    return re.sub(r"(?i)((?:token|password|secret|authorization)[\"']?\s*[:=]\s*)[^\s,]+", r"\1[redacted]", text)


def run_process(args, cwd=None, timeout=120, input=None, env=None):
    child_env = dict(os.environ)
    child_env.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
                      "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=10"})
    if env:
        child_env.update(env)
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(args, cwd=cwd, env=child_env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **flags)
    try:
        stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.kill()
        try:
            proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        raise RuntimeError(f"Tempo limite ({timeout}s) excedido: {Path(str(args[0])).name}")
    return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
