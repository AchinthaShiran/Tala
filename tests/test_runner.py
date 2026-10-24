"""SubprocessRunner against the real OS, using the current Python as a portable child process."""

from __future__ import annotations

import sys
import time

from assistant.tools import SubprocessRunner

PY = sys.executable
runner = SubprocessRunner()


def run(code: str, **kw):
    kw.setdefault("timeout", 20)
    kw.setdefault("max_bytes", 10_000)
    return runner.run([PY, "-c", code], **kw)


def test_captures_stdout_stderr_and_exit_code():
    result = run("import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)")
    assert result.exit_code == 3 and not result.ok
    assert "out" in result.stdout and "err" in result.stderr
    assert "exited with code 3" in result.render()


def test_success_status():
    result = run("print('hi')")
    assert result.ok and result.status == "ok" and result.stdout.strip() == "hi"


def test_timeout_kills_the_process():
    started = time.monotonic()
    result = run("import time; time.sleep(30)", timeout=1)
    assert result.timed_out and result.status == "timeout"
    assert time.monotonic() - started < 15
    assert "timed out" in result.render()


def test_timeout_kills_child_processes_too():
    code = (
        "import subprocess, sys, time;"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)']);"
        "time.sleep(30)"
    )
    started = time.monotonic()
    result = run(code, timeout=1)
    assert result.timed_out
    assert time.monotonic() - started < 15  # would hang on pipe EOF if the grandchild survived


def test_output_is_bounded_head_and_tail():
    result = run("print('HEAD' + 'x' * 100000 + 'TAIL')", max_bytes=2000)
    assert result.truncated
    assert len(result.stdout) < 2500
    assert result.stdout.startswith("HEAD") and result.stdout.strip().endswith("TAIL")
    assert "omitted" in result.stdout


def test_missing_executable_is_an_error_result_not_an_exception():
    result = runner.run(["definitely-not-a-real-binary-xyz"], timeout=5, max_bytes=1000)
    assert result.error and result.status == "error"
    assert "Error:" in result.render()


def test_arguments_are_never_interpreted_by_a_shell():
    result = runner.run(
        [PY, "-c", "import sys; print(sys.argv[1])", "a & echo INJECTED; $(whoami)"],
        timeout=10,
        max_bytes=1000,
    )
    assert result.stdout.strip() == "a & echo INJECTED; $(whoami)"


def test_stdin_is_closed_so_interactive_prompts_cannot_hang():
    result = run("import sys; print(repr(sys.stdin.read()))", timeout=5)
    assert result.ok and "''" in result.stdout


def test_undecodable_bytes_do_not_crash():
    result = run("import sys; sys.stdout.buffer.write(b'ok \\xff\\xfe end')")
    assert "ok" in result.stdout and "end" in result.stdout
