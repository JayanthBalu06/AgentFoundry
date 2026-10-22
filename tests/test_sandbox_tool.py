from app.tools.sandbox_tool import SandboxViolation, _static_check, run_python


def test_benign_code_runs_and_captures_stdout():
    result = run_python("print('hello from sandbox')", timeout=5)
    assert result["ok"] is True
    assert "hello from sandbox" in result["stdout"]


def test_blocked_import_is_rejected_statically():
    try:
        _static_check("import os\nos.system('echo hi')")
        assert False, "expected SandboxViolation"
    except SandboxViolation:
        pass


def test_blocked_import_never_reaches_subprocess():
    result_ok_before = run_python("print('ok')", timeout=5)
    assert result_ok_before["ok"] is True
    try:
        run_python("import socket\nsocket.socket()", timeout=5)
        assert False, "expected SandboxViolation"
    except SandboxViolation:
        pass


def test_timeout_is_enforced():
    result = run_python("while True:\n    pass", timeout=1)
    assert result["ok"] is False
    assert "timeout" in result["stderr"].lower()


def test_dunder_escape_is_rejected():
    try:
        _static_check("().__class__.__base__.__subclasses__()")
        assert False, "expected SandboxViolation"
    except SandboxViolation:
        pass
