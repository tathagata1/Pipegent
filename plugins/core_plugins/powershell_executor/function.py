import subprocess
from pathlib import Path
from typing import Dict, Optional, Union


DEFAULT_TIMEOUT = 60.0


def powershell_executor(
    command: str,
    timeout: Optional[Union[int, float]] = None,
    working_directory: Optional[str] = None,
    stdin_data: Optional[str] = None,
) -> Dict[str, Union[int, str]]:
    """
    Run a PowerShell command and capture its results.
    Returns a dictionary with stdout, stderr, and exit_code fields.
    Provide stdin_data when you want to pipe large/multi-line data into the command.
    """

    if not command or not command.strip():
        raise ValueError("A PowerShell command is required.")

    if timeout is None:
        run_timeout = DEFAULT_TIMEOUT
    else:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero.")
        run_timeout = float(timeout)

    cwd: Optional[str] = None
    if working_directory:
        directory_path = Path(working_directory).expanduser()
        if not directory_path.exists() or not directory_path.is_dir():
            raise FileNotFoundError(f"Directory does not exist: {directory_path}")
        cwd = str(directory_path.resolve())

    ps_args = [
        "powershell",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        command,
    ]

    try:
        completed = subprocess.run(
            ps_args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=run_timeout,
            check=False,
            input=stdin_data,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"PowerShell command timed out after {run_timeout} seconds.") from exc

    # Strip trailing whitespace so logs coming back to the LLM stay compact.
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout.rstrip(),
        "stderr": completed.stderr.rstrip(),
    }
