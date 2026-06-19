from __future__ import annotations

import shlex
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess, pyqtSignal

from .config import LauncherProfile


class ProcessRunner(QObject):
    output = pyqtSignal(str)
    started = pyqtSignal(str)
    finished = pyqtSignal(str, int)
    failed_to_start = pyqtSignal(str)

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.proc: QProcess | None = None

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.state() != QProcess.NotRunning

    def start(self, cmd: list[str], cwd: Path | None = None) -> bool:
        if self.is_running():
            self.output.emit(f"[{self.name}] already running.")
            return False
        self.proc = QProcess(self)
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        if cwd:
            self.proc.setWorkingDirectory(str(cwd))
        self.proc.readyReadStandardOutput.connect(self._read_output)
        self.proc.started.connect(lambda: self.started.emit(self.name))
        self.proc.finished.connect(self._finished)
        self.proc.errorOccurred.connect(self._error)
        self.output.emit(f"[{self.name}] $ {' '.join(cmd)}")
        self.proc.start(cmd[0], cmd[1:])
        return True

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.state() != QProcess.NotRunning:
            self.output.emit(f"[{self.name}] stopping...")
            self.proc.terminate()
            if not self.proc.waitForFinished(3000):
                self.output.emit(f"[{self.name}] terminate timed out; killing process.")
                self.proc.kill()
                self.proc.waitForFinished(3000)
        self.proc = None

    def _read_output(self) -> None:
        if not self.proc:
            return
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.rstrip().splitlines():
            self.output.emit(f"[{self.name}] {line}")

    def _finished(self, exit_code: int, _exit_status: QProcess.ExitStatus) -> None:
        self.output.emit(f"[{self.name}] finished. exit_code={exit_code}")
        self.finished.emit(self.name, int(exit_code))

    def _error(self, error: QProcess.ProcessError) -> None:
        self.output.emit(f"[{self.name}] ERROR: process error {int(error)}")
        if error == QProcess.FailedToStart:
            self.failed_to_start.emit(self.name)


def build_sitl_command(
    profile: LauncherProfile,
    console: bool,
    mavproxy_map: bool,
    gcs_out: str,
    wipe_params: bool = False,
) -> tuple[list[str], Path]:
    args = [
        "./Tools/autotest/sim_vehicle.py",
        "-v",
        profile.aircraft.vehicle,
        "-f",
        profile.aircraft.frame,
        "-L",
        profile.start_location.name,
    ]
    if console:
        args.append("--console")
    if mavproxy_map:
        args.append("--map")
    if gcs_out.strip():
        args.append(f"--out={gcs_out.strip()}")
    if wipe_params:
        args.append("-w")
    param_file = profile.paths.resolve_project_path(profile.paths.param_file)
    if param_file.exists():
        args.append(f"--add-param-file={param_file}")

    shell_cmd = " ".join(shlex.quote(arg) for arg in args)
    return ["bash", "-lc", shell_cmd], profile.paths.ardupilot_root
