"""Application-facing API shared by CLI, GUI, and future presentations."""

from .models import RunRequest, RunResult, RunStatus
from .service import TestService

__all__ = ["RunRequest", "RunResult", "RunStatus", "TestService"]
