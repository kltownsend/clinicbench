"""Run the ``fizz`` model checker over a contract's embedded FizzBee block.

Importable from both the offline verification script and the pytest suite so
there is exactly one definition of "model-check this contract".
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .contract_doc import ContractDoc

__all__ = ["FizzResult", "fizz_available", "model_check"]

_DEFAULT_FIZZ_BIN = "fizz"


class FizzResult:
    """Outcome of a single ``fizz`` run."""

    __slots__ = ("passed", "output")

    def __init__(self, passed: bool, output: str) -> None:
        self.passed = passed
        self.output = output

    def __bool__(self) -> bool:
        return self.passed


def fizz_available(fizz_bin: str = _DEFAULT_FIZZ_BIN) -> bool:
    """True if the ``fizz`` binary can be located."""
    return shutil.which(fizz_bin) is not None or Path(fizz_bin).exists()


def model_check(doc: ContractDoc, *, fizz_bin: str = _DEFAULT_FIZZ_BIN) -> FizzResult:
    """Extract the FizzBee block from ``doc`` and run ``fizz`` over it."""
    with tempfile.TemporaryDirectory() as tmp:
        fizz_path = Path(tmp) / f"{doc.workflow_id}.fizz"
        fizz_path.write_text(doc.fizzbee_text, encoding="utf-8")
        proc = subprocess.run(
            [fizz_bin, str(fizz_path)],
            capture_output=True,
            text=True,
            cwd=tmp,
        )
    output = proc.stdout + proc.stderr
    passed = proc.returncode == 0 and "PASSED" in output
    return FizzResult(passed, output)
