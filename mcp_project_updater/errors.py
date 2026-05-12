from __future__ import annotations

from dataclasses import dataclass

from .constants import ExitCode


@dataclass(slots=True)
class UpdaterError(Exception):
    message: str
    exit_code: int

    def __str__(self) -> str:
        return self.message


class ConfigValidationError(UpdaterError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, exit_code=ExitCode.CONFIG_ERROR)


class WorkflowNotImplementedError(UpdaterError):
    def __init__(self, message: str = "Workflow is not implemented yet.") -> None:
        super().__init__(message=message, exit_code=ExitCode.SUCCESS_WITH_WARNINGS)

