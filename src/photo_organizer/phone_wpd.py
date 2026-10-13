"""Windows WPD transport, isolated from Qt and local filesystem copy policy.

The bundled C# helper uses Windows COM APIs only. Object IDs are session scoped.
Replacement stages and verifies a new object before exchanging names. A successful upload means Commit plus
name/size verification, not a byte-for-byte integrity comparison.
"""
from __future__ import annotations

import base64
from collections import deque
import json
import logging
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from uuid import uuid4
from typing import Callable


class WpdBackend:
    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None
        self._owner: int | None = None
        self._messages: queue.Queue[str | None] = queue.Queue()
        self._errors: deque[str] = deque(maxlen=20)
        self._activity_callback: Callable[[str, bool], None] | None = None
        self._activity_phase = 'prepare'
        self._activity_cancellable = True

    def set_activity_callback(self, callback: Callable[[str, bool], None] | None) -> None:
        """Optional observational callback; it cannot change transport safety decisions."""
        if callback is not None and not callable(callback):
            raise TypeError('activity callback must be callable or None')
        self._activity_callback = callback

    def _notify_activity(self, phase: str, cancellable: bool) -> None:
        if self._activity_callback is not None:
            try:
                self._activity_callback(phase, cancellable)
            except Exception:
                logging.getLogger(__name__).warning('휴대폰 전송 단계 표시 실패', exc_info=True)

    def __enter__(self):
        self._ensure_started()
        return self

    def __exit__(self, *_):
        self.close()

    def _ensure_started(self) -> None:
        owner = threading.get_ident()
        if self._owner is not None and self._owner != owner:
            raise RuntimeError("WPD 세션은 생성한 작업 스레드에서만 사용할 수 있습니다.")
        if self._process is not None:
            if self._process.poll() is not None:
                raise OSError("휴대폰 연결 도우미가 종료되었습니다. 다시 연결해주세요.")
            return
        if os.name != "nt":
            raise OSError("휴대폰 USB 전송은 Windows에서 지원합니다.")
        self._owner = owner
        self._messages = queue.Queue()
        self._errors = deque(maxlen=20)
        messages, errors = self._messages, self._errors
        helper = Path(__file__).with_name("resources") / "phone_wpd.cs"
        command = (
            "$ErrorActionPreference='Stop'; "
            "Add-Type -Path '" + str(helper).replace("'", "''") + "' "
            "-ReferencedAssemblies System.dll,System.Core.dll,System.Web.Extensions.dll; "
            "[PhotoOrganizerWpd.Server]::Run()"
        )
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        powershell = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        self._process = subprocess.Popen(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-STA", "-EncodedCommand", encoded],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        process = self._process

        def stdout_reader():
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    messages.put(line)
            finally:
                messages.put(None)

        def stderr_reader():
            assert process.stderr is not None
            for line in process.stderr:
                errors.append(line.strip())

        threading.Thread(target=stdout_reader, daemon=True).start()
        threading.Thread(target=stderr_reader, daemon=True).start()
        try:
            ready = self._receive(45)
            if ready.get("event") != "ready":
                raise OSError("WPD 도우미 초기화에 실패했습니다.")
        except Exception:
            self._terminate()
            raise

    def _send(self, message: dict) -> None:
        assert self._process is not None and self._process.stdin is not None
        try:
            self._process.stdin.write(json.dumps(message, ensure_ascii=True) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise OSError("휴대폰 연결 도우미 통신이 끊겼습니다.") from exc

    def _receive(self, timeout: float, cancelled: Callable[[], bool] | None = None) -> dict:
        deadline = time.monotonic() + timeout
        waiting_reported = False
        while (now := time.monotonic()) < deadline:
            if not waiting_reported and now >= deadline - timeout + 2:
                self._notify_activity('waiting:' + self._activity_phase, self._activity_cancellable)
                waiting_reported = True
            try:
                line = self._messages.get(timeout=min(.1, max(.001, deadline - now)))
            except queue.Empty:
                continue
            if line is None:
                raise OSError("WPD 도우미 연결 종료: " + " / ".join(self._errors))
            try:
                value = json.loads(line)
            except ValueError as exc:
                raise OSError("WPD 도우미 응답 해석 실패: " + line[:300]) from exc
            if not isinstance(value, dict):
                raise OSError("잘못된 WPD 도우미 응답입니다.")
            return value
        self._terminate()
        message = "휴대폰 응답 시간이 초과되었습니다. 현재 파일의 완료 여부를 다시 확인해주세요."
        raise OSError(message)

    @staticmethod
    def _result(message: dict):
        if not message.get("ok"):
            error = {"exists": FileExistsError, "cancelled": InterruptedError}.get(message.get("kind"), OSError)
            raise error(message.get("error") or "휴대폰 작업에 실패했습니다.")
        return message.get("result")

    def _progress(self, message: dict, progress: Callable[[int], None], cancelled: Callable[[], bool]) -> None:
        self._activity_phase = str(message.get('phase', 'write'))
        self._activity_cancellable = message.get('cancellable', True) is not False
        self._notify_activity(self._activity_phase, self._activity_cancellable)
        try:
            progress(int(message["bytes"]))
            proceed = message.get("cancellable", True) is False or not cancelled()
        except Exception:
            self._send({"continue": False})
            raise
        self._send({"continue": proceed})

    def _request(self, operation: str, *, progress=None, cancelled=None, **arguments):
        if self._owner is not None and self._owner != threading.get_ident():
            raise RuntimeError("WPD 세션은 생성한 작업 스레드에서만 사용할 수 있습니다.")
        try:
            self._activity_phase, self._activity_cancellable = operation, True
            self._notify_activity(operation, True)
            self._ensure_started()
            self._send({"op": operation, **arguments})
            while True:
                message = self._receive(60, cancelled)
                if message.get("event") == "progress":
                    self._progress(message, progress or (lambda _: None), cancelled or (lambda: False))
                else:
                    return self._result(message)
        except (FileExistsError, InterruptedError):
            raise
        except Exception:
            self._terminate()  # Do not reuse a session with uncertain protocol/COM state.
            raise

    @staticmethod
    def _entry(value: dict):
        from .phone_transfer import RemoteEntry
        return RemoteEntry(value["id"], value["name"], bool(value["is_folder"]), value.get("size"))

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or name in {".", ".."} or any(char in name for char in "/\\\x00"):
            raise ValueError("휴대폰 파일명에는 경로를 넣을 수 없습니다.")

    def list_devices(self):
        # WPD also exposes filesystem volumes through SWD/WPDBUSENUM. This
        # feature targets physically connected USB WPD devices, not those drives.
        return [self._entry(value) for value in self._request("devices")
                if value["id"].casefold().startswith("\\\\?\\usb#")]

    def open_device(self, device_id: str) -> None:
        self._request("open", id=device_id)

    def list_children(self, parent_id: str = "DEVICE"):
        return [self._entry(value) for value in self._request("children", parent=parent_id)]

    def create_folder(self, parent_id: str, name: str):
        self._validate_name(name)
        return self._entry(self._request("folder", parent=parent_id, name=name))

    def upload_new(self, parent_id: str, name: str, source: Path, progress: Callable[[int], None], cancelled: Callable[[], bool]):
        self._validate_name(name)
        if cancelled():
            raise InterruptedError("휴대폰 전송을 취소했습니다.")
        expected_size = source.stat().st_size
        value = self._request("upload", parent=parent_id, name=name, source=str(source.resolve()), progress=progress, cancelled=cancelled)
        entry = self._entry(value)
        if entry.name != name or entry.is_folder or entry.size != expected_size:
            raise OSError("휴대폰 전송 후 이름/크기 확인 실패: 생성된 파일을 확인해주세요.")
        return entry

    def overwrite_file(self, parent_id: str, name: str, source: Path, progress: Callable[[int], None], cancelled: Callable[[], bool], existing_id: str):
        self._validate_name(name)
        if cancelled():
            raise InterruptedError("휴대폰 전송을 취소했습니다.")
        expected_size = source.stat().st_size
        stage_name = ".photoorganizer_stage_" + uuid4().hex + Path(name).suffix
        backup_name = ".photoorganizer_backup_" + uuid4().hex + Path(name).suffix
        try:
            value = self._request("overwrite", parent=parent_id, name=name, source=str(source.resolve()), existing_id=existing_id, stage_name=stage_name, backup_name=backup_name, progress=progress, cancelled=cancelled)
        except (FileExistsError, InterruptedError):
            raise
        except OSError as exc:
            raise OSError(f"{exc} 복구 파일 확인: {stage_name}, {backup_name}") from exc
        entry = self._entry(value)
        if entry.name != name or entry.is_folder or entry.size != expected_size:
            raise OSError(f"휴대폰 교체 후 이름/크기 확인 실패. 복구 파일 확인: {stage_name}, {backup_name}")
        return entry

    def _terminate(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()

    def close(self) -> None:
        if self._process is None:
            return
        if self._owner != threading.get_ident():
            raise RuntimeError("WPD 세션은 생성한 작업 스레드에서 닫아주세요.")
        try:
            self._send({"op": "close"})
            self._receive(5)
        except Exception:
            pass
        finally:
            self._terminate()
