"""Options shared by non-interactive metadata and video child processes."""
from __future__ import annotations

import os
import subprocess
from time import monotonic


def hidden_process_kwargs() -> dict:
    options = {'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        options.update(creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startupinfo)
    return options


def run_process(command, *, capture_output=False, check=False, timeout=None, **options):
    """subprocess.run semantics, with bounded polling and cancellation cleanup."""
    from .operation_control import current_control
    control = current_control()
    if control is None:
        return subprocess.run(command, capture_output=capture_output, check=check,
                              timeout=timeout, **options)
    control.raise_if_interrupted()
    if capture_output:
        options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    from .isolated_work import ProcessTree, suspended_options, resume_process
    process = subprocess.Popen(command, **suspended_options(options))
    tree = None
    deadline = monotonic() + timeout if timeout is not None else None
    try:
        tree = ProcessTree(process)
        resume_process(process)
        while True:
            control.raise_if_interrupted()
            remaining = deadline - monotonic() if deadline is not None else .05
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        control.raise_if_interrupted()
        if check and process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command, stdout, stderr)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    finally:
        if tree is not None:
            tree.close()
        if process.poll() is None:
            process.kill()
        process.communicate()
