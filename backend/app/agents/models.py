from pydantic.v1 import Field
from uagents import Model
from typing import Optional, List


class SentryStackFrame(Model):
    filename: Optional[str] = None
    function: Optional[str] = None
    line_number: Optional[int] = None
    context_line: Optional[str] = None
    in_app: Optional[bool] = None


class IncidentMessage(Model):
    incident_id: int
    sentry_issue_id: str
    title: str
    culprit: Optional[str] = None
    permalink: Optional[str] = None
    repo_full_name: str
    default_branch: str = "main"
    event_id: Optional[str] = None
    level: Optional[str] = None
    environment: Optional[str] = None
    platform: Optional[str] = None
    release: Optional[str] = None
    transaction: Optional[str] = None
    error_type: Optional[str] = None
    error_value: Optional[str] = None
    request_method: Optional[str] = None
    request_url: Optional[str] = None
    request_path: Optional[str] = None
    status_code: Optional[int] = None
    tags: dict[str, str] = Field(default_factory=dict)
    stacktrace_frames: List[SentryStackFrame] = Field(default_factory=list)


class InvestigationResult(Model):
    incident_id: int
    sentry_issue_id: str
    repo_full_name: str
    severity: str
    suspected_root_cause: str
    files_to_inspect: List[str] = Field(default_factory=list)
    recommendation: str


class PatchRequest(Model):
    incident_id: int
    repo_full_name: str
    default_branch: str
    suspected_root_cause: str
    recommendation: str
    files_to_inspect: List[str] = Field(default_factory=list)


class PatchResult(Model):
    incident_id: int
    repo_full_name: str
    branch_name: str
    commit_message: str
    changed_files: List[str]
    patch_summary: str


class PullRequestResult(Model):
    incident_id: int
    repo_full_name: str
    pr_url: str
    branch_name: str
    changed_files: List[str]


class ValidationResult(Model):
    incident_id: int
    repo_full_name: str
    pr_url: str
    tests_passed: bool
    validation_summary: str
