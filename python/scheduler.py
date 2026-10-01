"""Validated scheduler updates with rollback of the previous definitions."""
import csv
import io
import os
from pathlib import Path
import re
import shlex
import sys
import tempfile
import xml.etree.ElementTree as ET
from runtime_safety import run_process


def validate_schedules(times):
    if not isinstance(times, list) or not times or len(times) > 20:
        raise ValueError("Informe de 1 a 20 horarios HH:mm.")
    if any(not isinstance(t, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in times):
        raise ValueError("Horario invalido; use HH:mm entre 00:00 e 23:59.")
    if len(times) != len(set(times)):
        raise ValueError("Horarios duplicados.")
    return times


def checked(args, **kwargs):
    result = run_process(args, **kwargs)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout).strip() or f"Falha: {args[0]}")
    return result.stdout


def _task_names(name):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", name):
        raise ValueError("Nome de tarefa invalido.")
    listing = checked(["schtasks", "/Query", "/FO", "CSV", "/NH"])
    names = [row[0].lstrip("\\") for row in csv.reader(io.StringIO(listing)) if row]
    return [n for n in names if n == name or re.fullmatch(re.escape(name) + r"_\d+", n)]


def _put_task(name, xml):
    fd, path = tempfile.mkstemp(suffix=".xml")
    try:
        with os.fdopen(fd, "w", encoding="utf-16") as stream:
            stream.write(xml)
        checked(["schtasks", "/Create", "/TN", name, "/XML", path, "/F"])
    finally:
        Path(path).unlink(missing_ok=True)


def _xml(target, times):
    ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ET.register_namespace("", ns)
    def child(parent, name, text=None, **attrs):
        element = ET.SubElement(parent, "{" + ns + "}" + name, attrs)
        element.text = text
        return element
    root = ET.Element("{" + ns + "}Task", version="1.2")
    triggers = child(root, "Triggers")
    for t in times:
        trigger = child(triggers, "CalendarTrigger")
        child(trigger, "StartBoundary", f"2020-01-01T{t}:00")
        child(trigger, "Enabled", "true")
        child(child(trigger, "ScheduleByDay"), "DaysInterval", "1")
    sid = list(csv.reader(io.StringIO(checked(["whoami", "/user", "/fo", "csv", "/nh"]))))[0][1]
    principal = child(child(root, "Principals"), "Principal", id="Author")
    child(principal, "UserId", sid)
    child(principal, "LogonType", "InteractiveToken")
    child(principal, "RunLevel", "LeastPrivilege")
    settings = child(root, "Settings")
    child(settings, "MultipleInstancesPolicy", "IgnoreNew")
    child(settings, "DisallowStartIfOnBatteries", "false")
    child(settings, "StopIfGoingOnBatteries", "false")
    child(settings, "StartWhenAvailable", "true")
    child(settings, "ExecutionTimeLimit", "PT2H")
    action = child(child(root, "Actions", Context="Author"), "Exec")
    is_script = target.suffix.lower() == ".py"
    child(action, "Command", sys.executable if is_script else str(target))
    if is_script:
        child(action, "Arguments", f'"{target}"')
    child(action, "WorkingDirectory", str(target.parent))
    return ET.tostring(root, encoding="unicode")


def _read_cron():
    result = run_process(["crontab", "-l"], env={"LC_ALL": "C"})
    if result.returncode and "no crontab for" not in result.stderr.lower():
        raise RuntimeError(result.stderr.strip() or "Nao foi possivel ler o crontab.")
    return result.stdout


def install(target, times, name, windows):
    validate_schedules(times)
    target = Path(target).resolve(strict=True)
    if any(c in str(target) for c in "\r\n"):
        raise ValueError("Caminho invalido.")
    if windows:
        old = {n: checked(["schtasks", "/Query", "/TN", n, "/XML"]) for n in _task_names(name)}
        try:
            _put_task(name, _xml(target, times))
            checked(["schtasks", "/Query", "/TN", name, "/XML"])
            for previous in old:
                if previous != name:
                    checked(["schtasks", "/Delete", "/TN", previous, "/F"])
        except Exception as exc:
            errors = []
            for previous, xml in old.items():
                try:
                    _put_task(previous, xml)
                except Exception as rollback:
                    errors.append(str(rollback))
            if name not in old:
                run_process(["schtasks", "/Delete", "/TN", name, "/F"])
            raise RuntimeError(f"Instalacao falhou: {exc}. Falhas de restauracao: {errors}") from exc
    else:
        old = _read_cron()
        lines = [line for line in old.splitlines() if line.rstrip().endswith("# git-autosync") is False]
        argv = ([sys.executable, str(target)] if target.suffix == ".py" else [str(target)])
        command = " ".join(shlex.quote(a) for a in argv)
        command = ("env " + shlex.quote("PATH=" + os.environ.get("PATH", "/usr/bin:/bin")) + " " + command).replace("%", r"\%")
        for t in times:
            hh, mm = t.split(":")
            lines.append(f"{int(mm)} {int(hh)} * * * {command} # git-autosync")
        new = "\n".join(lines) + "\n"
        try:
            checked(["crontab", "-"], input=new)
            if _read_cron() != new:
                raise RuntimeError("Verificacao do crontab falhou.")
        except Exception:
            checked(["crontab", "-"], input=old)
            raise


def uninstall(name, windows):
    if windows:
        for existing in _task_names(name):
            checked(["schtasks", "/Delete", "/TN", existing, "/F"])
    else:
        old = _read_cron()
        lines = [line for line in old.splitlines() if not line.rstrip().endswith("# git-autosync")]
        checked(["crontab", "-"], input="\n".join(lines) + ("\n" if lines else ""))
