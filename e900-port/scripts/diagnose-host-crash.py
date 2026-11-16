#!/usr/bin/env python3
"""Capture a host scanner backtrace after build failure; never change its sources."""
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys


def scanner_command(commands, python):
    matches = []
    for line in commands.splitlines():
        arguments = shlex.split(line)
        if "--output=gir/GLib-2.0.gir" in arguments:
            matches.append(arguments)
    if len(matches) != 1:
        raise ValueError("Could not identify one GLib scanner command")
    arguments = matches[0]
    environment = {}
    if arguments and arguments[0] == "env":
        arguments.pop(0)
    while arguments and re.match(r"^[A-Za-z_][A-Za-z_0-9]*=", arguments[0]):
        name, value = arguments.pop(0).split("=", 1)
        environment[name] = value
    if any(token in {"&&", "||", ";", "|", ">", "2>"} for token in arguments):
        raise ValueError("Shell compound command is not supported by the debugger")
    if not arguments or pathlib.Path(arguments[0]).name != "g-ir-scanner":
        raise ValueError("Unexpected scanner executable")
    return [str(python)] + arguments, environment


def diagnose(repo):
    work = pathlib.Path(os.environ.get("E900_WORK_ROOT", repo.parent))
    logs = work / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    destination = logs / "host-scanner-diagnostic.log"
    output = []

    def run(arguments, cwd=None, environment=None, timeout=30):
        output.append("COMMAND: " + shlex.join([str(arg) for arg in arguments]))
        try:
            result = subprocess.run(arguments, cwd=cwd, env=environment, timeout=timeout,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            output.append(result.stdout)
            output.append(f"EXIT CODE: {result.returncode}")
            return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            output.append(str(exc))
            return None

    try:
        cpuinfo = pathlib.Path("/proc/cpuinfo")
        if cpuinfo.exists():
            output.append(cpuinfo.read_text().split("\n\n", 1)[0])
        candidates = list(repo.glob("build.*/build/gobject-introspection-*/.x86_64-linux-gnu"))
        if len(candidates) != 1:
            output.append("No unique host introspection build directory; nothing to rerun.")
            return
        build = candidates[0]
        # build is <build-root>/build/<package>/.x86_64-linux-gnu.
        toolchain = build.parents[2] / "toolchain"
        python = toolchain / "bin/python3"
        ninja = toolchain / "bin/ninja"
        run(["file", str(python)])
        run(["ldd", str(python)])
        run([str(python), "-c", "import ctypes, platform; print(platform.platform()); print('Python/ctypes smoke passed')"])
        result = run([str(ninja), "-t", "commands", "gir/GLib-2.0.gir"], cwd=build)
        if not result or result.returncode:
            return
        command, environment = scanner_command(result.stdout, python)
        debugger = shutil.which("gdb")
        if not debugger:
            output.append("gdb unavailable; scanner rerun skipped.")
            return
        environment = dict(os.environ, **environment)
        environment["GI_SCANNER_DISABLE_CACHE"] = "1"
        environment["GI_SCANNER_DEBUG"] = "save-temps"
        run([debugger, "--batch", "--return-child-result",
             "-ex", "set pagination off", "-ex", "set confirm off",
             "-ex", "handle SIGILL stop print nopass", "-ex", "run",
             "-ex", "x/12i $pc-16", "-ex", "thread apply all bt",
             "-ex", "info sharedlibrary", "-ex", "quit", "--args"] + command,
            cwd=build, environment=environment, timeout=150)
    except Exception as exc:
        output.append(f"Diagnostic error: {exc}")
    finally:
        destination.write_text("\n".join(output) + "\n")
        print(f"Host scanner diagnostic saved: {destination}")
        print("\n".join(output)[-12000:])


if __name__ == "__main__":
    diagnose(pathlib.Path(sys.argv[1]).resolve())
