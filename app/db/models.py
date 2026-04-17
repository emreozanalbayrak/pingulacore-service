from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline(Base):
    __tablename__ = "pipelines"

    id: Mapped[str] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(default="full")
    yaml_filename: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="running")
    retry_config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sub_pipelines: Mapped[list["SubPipeline"]] = relationship(back_populates="pipeline")


class SubPipeline(Base):
    __tablename__ = "sub_pipelines"

    id: Mapped[str] = mapped_column(primary_key=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    mode: Mapped[str] = mapped_column(default="sub")
    kind: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(default="running")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pipeline: Mapped[Pipeline | None] = relationship(back_populates="sub_pipelines")


class PipelineAgentLink(Base):
    __tablename__ = "pipeline_agent_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipelines.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(default="")
    agent_table: Mapped[str] = mapped_column(default="")
    agent_run_id: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipelines.id"), nullable=True)
    mode: Mapped[str] = mapped_column(default="")
    level: Mapped[str] = mapped_column(default="info")
    component: Mapped[str] = mapped_column(default="pipeline")
    message: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRunMixin:
    id: Mapped[str] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(default="standalone")
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipelines.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipelines.id"), nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(default="success")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str] = mapped_column(default="")
    question_id: Mapped[str | None] = mapped_column(nullable=True)
    schema_version: Mapped[str | None] = mapped_column(nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AgentMainQuestionRun(AgentRunMixin, Base):
    __tablename__ = "agent_main_question_runs"


class AgentMainLayoutRun(AgentRunMixin, Base):
    __tablename__ = "agent_main_layout_runs"


class AgentMainHtmlRun(AgentRunMixin, Base):
    __tablename__ = "agent_main_html_runs"


class AgentRuleExtractionRun(AgentRunMixin, Base):
    __tablename__ = "agent_rule_extraction_runs"


class AgentRuleEvaluationRun(AgentRunMixin, Base):
    __tablename__ = "agent_rule_evaluation_runs"


class AgentQuestionLayoutValidationRun(AgentRunMixin, Base):
    __tablename__ = "agent_question_layout_validation_runs"


class AgentLayoutHtmlValidationRun(AgentRunMixin, Base):
    __tablename__ = "agent_layout_html_validation_runs"


class AgentCompositeImageRun(AgentRunMixin, Base):
    __tablename__ = "agent_composite_image_runs"


class StoredJsonOutput(Base):
    __tablename__ = "stored_json_outputs"
    __table_args__ = (UniqueConstraint("kind", "filename", name="uq_stored_json_outputs_kind_filename"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(default="")
    filename: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    source_sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipelines.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FavoriteOutput(Base):
    __tablename__ = "favorite_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(default="")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    source_sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipelines.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
