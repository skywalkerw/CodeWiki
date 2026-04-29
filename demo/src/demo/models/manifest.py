from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class ProjectInfo(BaseModel):
    name: str = ""
    group_id: str = ""
    artifact_id: str = ""
    description: str = ""


class SnapshotInfo(BaseModel):
    vcs: str = "git"
    commit_sha: str = ""
    commit_date: str | None = None
    branch: str | None = None


class BuildInfo(BaseModel):
    tool: str = "unknown"
    maven_version: str | None = None
    jdk: str | None = None
    active_profiles: list[str] = Field(default_factory=list)


class AnalysisInfo(BaseModel):
    run_id: str = ""
    generated_at: str = ""
    engine: str = "jdtls-lsp-py"
    notes: list[str] = Field(default_factory=list)


class AnalysisManifest(BaseModel):
    """Aligns with docs/samples/1.1-analysis_manifest.json shape."""

    schema_version: str = "1.0"
    project: ProjectInfo = Field(default_factory=ProjectInfo)
    snapshot: SnapshotInfo = Field(default_factory=SnapshotInfo)
    build: BuildInfo = Field(default_factory=BuildInfo)
    analysis: AnalysisInfo = Field(default_factory=AnalysisInfo)

    def model_dump_json_compatible(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
