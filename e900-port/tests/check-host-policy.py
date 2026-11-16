#!/usr/bin/env python3
"""Verify portable host flags, ownership guards and scanner diagnostic parsing."""
import hashlib
import importlib.util
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile

PORT = pathlib.Path(__file__).resolve().parents[1]
REFERENCE = pathlib.Path(os.environ.get("E900_CE_REFERENCE", PORT / "reference/CoreELEC"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


installer = load("host_policy_installer", PORT / "scripts/install-patches.py")
diagnostic = load("host_policy_diagnostic", PORT / "scripts/diagnose-host-crash.py")
with tempfile.TemporaryDirectory(prefix="e900-host-policy-") as directory:
    repo = pathlib.Path(directory)
    optimize = repo / "config/optimize"
    optimize.parent.mkdir()
    original = (REFERENCE / "config/optimize").read_text().replace(installer.HOST_CODEGEN["cflags"], "-march=native")
    assert hashlib.sha256(original.encode()).hexdigest() == installer.HOST_CODEGEN["upstream_optimize_sha256"]
    optimize.write_text(original)
    relative, content, metadata = installer.host_codegen_fix(repo)
    assert relative == "config/optimize" and "-march=native" not in content
    assert content.replace(installer.HOST_CODEGEN["cflags"], "-march=native") == original
    optimize.write_text(content)
    assert installer.host_codegen_fix(repo) == (relative, content, metadata)
    optimize.write_text(content + "# local edit\n")
    try:
        installer.host_codegen_fix(repo)
    except RuntimeError as exc:
        assert "local edits" in str(exc)
    else:
        raise AssertionError("Edited host configuration was overwritten")
    print("PASS: host flags are repeatable, guarded, and leave all target flags unchanged")

    compiler = shutil.which("gcc-12") or shutil.which("clang") or shutil.which("cc")
    macros = subprocess.check_output([compiler] + shlex.split(installer.HOST_CODEGEN["cflags"])
                                     + ["-dM", "-E", "-x", "c", "-"], input="", text=True)
    assert "__x86_64__" in macros
    assert not any(name in macros for name in ["__AVX__", "__AVX2__", "__AVX512F__"])
    print("PASS: host compiler accepts the generic x86-64 policy without AVX/AVX2/AVX-512")

    command = 'env GI_TEST=1 /tmp/tools/g-ir-scanner --output=gir/GLib-2.0.gir --c-include="glib header.h"'
    arguments, environment = diagnostic.scanner_command(command, pathlib.Path("/tmp/python3"))
    assert arguments == ["/tmp/python3", "/tmp/tools/g-ir-scanner", "--output=gir/GLib-2.0.gir", "--c-include=glib header.h"]
    assert environment == {"GI_TEST": "1"}
    try:
        diagnostic.scanner_command(command + " && echo other", pathlib.Path("/tmp/python3"))
    except ValueError:
        pass
    else:
        raise AssertionError("Debugger accepted a compound shell command")
    print("PASS: diagnostic reruns only the selected scanner command with its Python interpreter")
