#!/usr/bin/env python3
"""Exercise compatibility keys and selective refresh of a restored build tree."""
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

PORT = pathlib.Path(__file__).resolve().parents[1]
REFERENCE = pathlib.Path(os.environ.get("E900_CE_REFERENCE", PORT / "reference/CoreELEC"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cache = load("build_cache_test", PORT / "scripts/build-cache.py")
with tempfile.TemporaryDirectory(prefix="e900-cache-check-") as temporary:
    root = pathlib.Path(temporary)
    port = root / "port"
    for name in ["scripts", "patches", "boards"]:
        shutil.copytree(PORT / name, port / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(PORT / "pins.json", port / "pins.json")
    host = dict(os_release="Ubuntu 22.04", machine="x86_64", packages="gcc-12=12.3;libc6=2.35")
    first = cache.identities(port, "identify", root / "work", host)
    legacy = dict(first["details"], schema=1)
    legacy.pop("host_codegen")
    assert first["compat"] != cache.digest(legacy)
    assert first["compiler"] != cache.digest(dict(schema=1, pins=legacy["pins"], host=host))
    policy_source = port / "scripts/install-patches.py"
    policy_content = policy_source.read_text()
    policy_source.write_text(policy_content.replace("-march=x86-64 -mtune=generic", "-march=x86-64-v2 -mtune=generic"))
    different_isa = cache.identities(port, "identify", root / "work", host)
    assert first["compat"] != different_isa["compat"] and first["compiler"] != different_isa["compiler"]
    policy_source.write_text(policy_content)
    print("PASS: legacy native caches and a different host ISA cannot restore into the portable policy")
    assert first == cache.identities(port, "identify", root / "work", host)
    assert first["compat"] != cache.identities(port, "identify", root / "other-work", host)["compat"]
    assert first["compat"] != cache.identities(port, "hdmi", root / "work", host)["compat"]
    assert first["compat"] != cache.identities(port, "identify", root / "work", dict(host, packages="gcc-12=12.4"))["compat"]
    print("PASS: host, absolute build root and profile isolate incompatible toolchains")

    decoder_identity = cache.identities(port, "decoder", root / "work", host)
    options = port / "boards/usb-build.options"
    original_options = options.read_bytes()
    options.write_bytes(original_options + b"\n# test option revision\n")
    updated_identity = cache.identities(port, "decoder", root / "work", host)
    assert decoder_identity["compat"] == updated_identity["compat"]
    assert decoder_identity["state"] != updated_identity["state"]
    options.write_bytes(original_options)
    print("PASS: board option changes alter build state without discarding compatible toolchains")

    installer = load("cache_installer_test", port / "scripts/install-patches.py")
    previous = dict(pins=installer.PINS, profile="decoder", patches=[], build_options=None)
    updated = dict(previous, build_options=dict(sha256="new-options"))
    assert installer.invalidated_packages(previous, updated) == ["linux", "media_modules-aml"]
    repo = root / "work/CoreELEC-identify"
    for relative in ["projects/Amlogic-ce/packages/linux/package.mk",
                     "projects/Amlogic-ce/packages/linux-drivers/amlogic/media_modules-aml/package.mk",
                     "packages/sysutils/keyutils/package.mk",
                     "packages/sysutils/usbutils/package.mk",
                     "packages/network/connman/package.mk",
                     "packages/network/wireguard-linux-compat/package.mk",
                     "packages/network/wireguard-tools/package.mk",
                     "projects/Amlogic-ce/packages/tools/u-boot-tools/package.mk",
                     "packages/tools/megatools/package.mk",
                     "config/optimize"]:
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REFERENCE / relative, target)

    with mock.patch.object(installer.subprocess, "check_output", return_value=installer.PINS["coreelec"]):
        installer.install(repo, "identify")
        sentinel = repo / "build.test/toolchain/keep-me"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("installed cross compiler")
        optimize = repo / "config/optimize"
        portable_optimize = optimize.read_text()
        optimize.write_text(portable_optimize.replace(installer.HOST_CODEGEN["cflags"], "-march=native"))
        try:
            installer.install(repo, "identify")
        except RuntimeError as exc:
            assert "Locally edited host optimization" in str(exc)
        else:
            raise AssertionError("Native flags restored beneath a portable cache marker were accepted")
        optimize.write_text(portable_optimize)
        state_path = repo / ".e900-profile.json"
        portable_state = json.loads(state_path.read_text())
        unsafe_state = dict(portable_state)
        unsafe_state.pop("host_codegen")
        state_path.write_text(json.dumps(unsafe_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            try:
                installer.install(repo, "identify")
            except RuntimeError as exc:
                assert "host binary cache" in str(exc)
            else:
                raise AssertionError("Unknown native binaries accepted for incremental reuse")
        assert sentinel.exists() and not (repo / ".e900-invalidate.json").exists()
        state_path.write_text(json.dumps(portable_state))
        print("PASS: installer refuses unsafe legacy host binaries without deleting the old build")
        # An unchanged resumed build must not schedule any clean operation.
        installer.install(repo, "identify")
        assert not (repo / ".e900-invalidate.json").exists()

        marker = repo / ".e900-profile.json"
        previous_state = json.loads(marker.read_text())
        previous_state["source_downloads"] = [entry for entry in previous_state["source_downloads"]
                                              if entry["package"] != "megatools"]
        marker.write_text(json.dumps(previous_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["megatools"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            cleaner.assert_called_once_with(["bash", "./scripts/clean", "megatools"], cwd=repo, check=True)
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: megatools source migration cleans only megatools and preserves the toolchain")

        marker = repo / ".e900-profile.json"
        previous_state = json.loads(marker.read_text())
        previous_state["source_downloads"] = [entry for entry in previous_state["source_downloads"]
                                              if entry["package"] != "u-boot-tools"]
        marker.write_text(json.dumps(previous_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["u-boot-tools"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            cleaner.assert_called_once_with(["bash", "./scripts/clean", "u-boot-tools"], cwd=repo, check=True)
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: u-boot-tools source migration cleans only its host/target package state")

        marker = repo / ".e900-profile.json"
        previous_state = json.loads(marker.read_text())
        previous_state["source_downloads"] = [entry for entry in previous_state["source_downloads"]
                                              if entry["package"] not in {"wireguard-linux-compat", "wireguard-tools"}]
        marker.write_text(json.dumps(previous_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["wireguard-linux-compat", "wireguard-tools"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            assert [call.args[0][-1] for call in cleaner.call_args_list] == ["wireguard-linux-compat", "wireguard-tools"]
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: WireGuard source migration cleans only its two packages, retaining kernel/toolchain")

        marker = repo / ".e900-profile.json"
        previous_state = json.loads(marker.read_text())
        previous_state["source_downloads"] = [entry for entry in previous_state["source_downloads"]
                                              if entry["package"] != "connman"]
        marker.write_text(json.dumps(previous_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["connman"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            cleaner.assert_called_once_with(["bash", "./scripts/clean", "connman"], cwd=repo, check=True)
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: ConnMan source switch cleans only connman and preserves the toolchain")

        # Resume the real previous schema (only keyutils had a download override).
        marker = repo / ".e900-profile.json"
        previous_state = json.loads(marker.read_text())
        previous_state["source_downloads"] = [entry for entry in previous_state["source_downloads"]
                                              if entry["package"] != "usbutils"]
        marker.write_text(json.dumps(previous_state))
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["usbutils"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            cleaner.assert_called_once_with(["bash", "./scripts/clean", "usbutils"], cwd=repo, check=True)
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: prior cached source schema resumes by cleaning only usbutils")

        media_patch = port / "patches/media/0001-gxlx2-identity-and-firmware-trace.patch"
        media_patch.write_text(media_patch.read_text() + "\n")
        changed = cache.identities(port, "identify", root / "work", host)
        assert first["compat"] == changed["compat"] and first["state"] != changed["state"]
        # CI enables reuse globally; this rejection case must explicitly disable it.
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "0"}):
            try:
                installer.install(repo, "identify")
            except RuntimeError as exc:
                assert "incremental reuse" in str(exc)
            else:
                raise AssertionError("Unapproved local incremental update accepted")
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        assert json.loads((repo / ".e900-invalidate.json").read_text()) == ["media_modules-aml"]
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            cleaner.assert_called_once_with(["bash", "./scripts/clean", "media_modules-aml"], cwd=repo, check=True)
        assert sentinel.read_text() == "installed cross compiler"
        print("PASS: unchanged state resumes; media patch changes clean only media, retaining toolchain")

        linux_patch = port / "patches/linux/0001-gxlx2-identity.patch"
        linux_patch.write_text(linux_patch.read_text() + "\n")
        with mock.patch.dict(os.environ, {"E900_INCREMENTAL_REUSE": "1"}):
            installer.install(repo, "identify")
        pending = repo / ".e900-invalidate.json"
        assert set(json.loads(pending.read_text())) == {"linux", "media_modules-aml"}
        with mock.patch.object(cache.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "clean")):
            try:
                cache.invalidate(repo)
            except subprocess.CalledProcessError:
                pass
            else:
                raise AssertionError("Failed clean was ignored")
        assert pending.exists()
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            cache.invalidate(repo)
            assert [call.args[0][-1] for call in cleaner.call_args_list] == ["media_modules-aml", "linux"]
        assert not pending.exists() and sentinel.exists()
        print("PASS: kernel changes rebuild kernel and media; failed clean remains pending for retry")

        pending.write_text('["toolchain"]')
        with mock.patch.object(cache.subprocess, "run") as cleaner:
            try:
                cache.invalidate(repo)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalidation could remove the toolchain")
            cleaner.assert_not_called()
        assert sentinel.exists()
        print("PASS: cache invalidation rejects toolchain removal")

    # Exercise the CLI in distinct processes: set ordering changes with hash seeds.
    cleaner_script = repo / "scripts/clean"
    cleaner_script.parent.mkdir(exist_ok=True)
    cleaner_script.write_text('printf \'%s\\n\' "$1" >> e900-clean-order.txt\n')
    clean_log = repo / "e900-clean-order.txt"
    for seed in ["0", "1", "2", "3", "42", "123", "random"]:
        pending = repo / ".e900-invalidate.json"
        pending.write_text(json.dumps(["wireguard-tools", "linux", "media_modules-aml",
                                       "wireguard-linux-compat", "wireguard-tools"]))
        clean_log.unlink(missing_ok=True)
        subprocess.run([sys.executable, str(PORT / "scripts/build-cache.py"), "invalidate", str(repo)],
                       env=dict(os.environ, PYTHONHASHSEED=seed), check=True)
        assert clean_log.read_text().splitlines() == ["media_modules-aml", "wireguard-linux-compat",
                                                       "wireguard-tools", "linux"], seed
        assert not pending.exists() and sentinel.exists()
    print("PASS: CLI cleanup is deterministic across seven hash seeds, deduplicates and keeps Linux last")

    # Exercise the real CoreELEC build/build/<package> layout, not a simplified path.
    build = repo / "build.test/build"
    kernel = build / "linux-amlogic-4.9-test"
    image = kernel / "arch/arm64/boot/Image.lzo"
    image.parent.mkdir(parents=True, exist_ok=True)
    image.write_bytes(b"test kernel")
    (kernel / ".config").write_text("CONFIG_TEST=y\n")
    module = build / "media_modules-aml-test/drivers/decoder/example.ko"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_bytes(b"test module")
    environment = dict(os.environ, E900_WORK_ROOT=str(root / "work"))
    subprocess.run([sys.executable, str(PORT / "scripts/export-artifacts.py"),
                    str(repo), "identify", "media", "1"], env=environment, check=True)
    metadata = json.loads((root / "work/export/identify/build-metadata.json").read_text())
    assert metadata["last_action_exit_code"] == 1
    exported = {entry["path"] for entry in metadata["artifacts"]}
    assert {str(path.relative_to(repo)) for path in [image, kernel / ".config", module]} <= exported
    print("PASS: kernel/config/module outputs export from the real build tree, including failed-run status")

print("CACHE LOGIC CHECKS PASSED. GitHub restore/save still needs a workflow run.")
