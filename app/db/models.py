from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(default="full")
    yaml_filename: Mapped[str] = mapped_column(default="")
    yaml_instance_id: Mapped[str | None] = mapped_column(ForeignKey("yaml_instances.id"), nullable=True)
    status: Mapped[str] = mapped_column(default="running")
    retry_config_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sub_pipelines: Mapped[list["SubPipeline"]] = relationship(back_populates="pipeline")


class SubPipeline(Base):
    __tablename__ = "sub_pipeline_runs"

    id: Mapped[str] = mapped_column(primary_key=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
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
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
    agent_name: Mapped[str] = mapped_column(default="")
    agent_table: Mapped[str] = mapped_column(default="")
    agent_run_id: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PipelineLog(Base):
    __tablename__ = "pipeline_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
    mode: Mapped[str] = mapped_column(default="")
    level: Mapped[str] = mapped_column(default="info")
    component: Mapped[str] = mapped_column(default="pipeline")
    message: Mapped[str] = mapped_column(Text, default="")
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentRunMixin:
    id: Mapped[str] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(default="standalone")
    pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
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
    source_sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class FavoriteOutput(Base):
    __tablename__ = "favorite_outputs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(default="")
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    source_sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Artifact(Base):
    __tablename__ = "artifacts"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('yaml_rendered','question','layout','html','generated_asset','catalog_asset','rendered_image')",
            name="ck_artifacts_kind",
        ),
        Index("ix_artifacts_kind", "kind"),
        Index("ix_artifacts_is_favorite", "is_favorite"),
        Index("ix_artifacts_source_pipeline_id", "source_pipeline_id"),
        Index("ix_artifacts_source_sub_pipeline_id", "source_sub_pipeline_id"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text, default="")
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_bucket: Mapped[str | None] = mapped_column(Text, nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    source_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    source_sub_pipeline_id: Mapped[str | None] = mapped_column(ForeignKey("sub_pipeline_runs.id"), nullable=True)
    source_agent_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_agent_run_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CurriculumConstantNode(Base):
    __tablename__ = "curriculum_constant_nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "slug", name="uq_curriculum_constant_nodes_parent_slug"),
        UniqueConstraint("path", name="uq_curriculum_constant_nodes_path"),
        CheckConstraint(
            "node_type IN ('root','grade','subject','theme')",
            name="ck_curriculum_constant_nodes_node_type",
        ),
        CheckConstraint("depth >= 0", name="ck_curriculum_constant_nodes_depth_non_negative"),
        Index("ix_curriculum_constant_nodes_parent_id", "parent_id"),
        Index("ix_curriculum_constant_nodes_node_type", "node_type"),
        Index("ix_curriculum_constant_nodes_path", "path"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("curriculum_constant_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    node_type: Mapped[str] = mapped_column(Text, default="theme")
    name: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parent: Mapped["CurriculumConstantNode | None"] = relationship(
        back_populates="children",
        remote_side=lambda: [CurriculumConstantNode.id],
    )
    children: Mapped[list["CurriculumConstantNode"]] = relationship(back_populates="parent", cascade="all, delete-orphan")


class CurriculumFolderNode(Base):
    __tablename__ = "curriculum_folder_nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "slug", name="uq_curriculum_folder_nodes_parent_slug"),
        UniqueConstraint("path", name="uq_curriculum_folder_nodes_path"),
        CheckConstraint("node_type IN ('folder')", name="ck_curriculum_folder_nodes_node_type"),
        CheckConstraint("depth >= 0", name="ck_curriculum_folder_nodes_depth_non_negative"),
        Index("ix_curriculum_folder_nodes_parent_id", "parent_id"),
        Index("ix_curriculum_folder_nodes_grade", "grade"),
        Index("ix_curriculum_folder_nodes_subject", "subject"),
        Index("ix_curriculum_folder_nodes_theme", "theme"),
        Index("ix_curriculum_folder_nodes_path", "path"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    parent_id: Mapped[str | None] = mapped_column(
        ForeignKey("curriculum_folder_nodes.id", ondelete="CASCADE"),
        nullable=True,
    )
    node_type: Mapped[str] = mapped_column(Text, default="folder")
    name: Mapped[str] = mapped_column(Text, default="")
    slug: Mapped[str] = mapped_column(Text, default="")
    code: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(Text, default="")
    grade: Mapped[str] = mapped_column(Text, default="")
    subject: Mapped[str] = mapped_column(Text, default="")
    theme: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parent: Mapped["CurriculumFolderNode | None"] = relationship(
        back_populates="children",
        remote_side=lambda: [CurriculumFolderNode.id],
    )
    children: Mapped[list["CurriculumFolderNode"]] = relationship(back_populates="parent", cascade="all, delete-orphan")


class YamlTemplate(Base):
    __tablename__ = "yaml_templates"
    __table_args__ = (
        UniqueConstraint("template_code", name="uq_yaml_templates_template_code"),
        CheckConstraint("status IN ('active','archived')", name="ck_yaml_templates_status"),
        Index("ix_yaml_templates_curriculum_folder_node_id", "curriculum_folder_node_id"),
        Index("ix_yaml_templates_status", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    curriculum_folder_node_id: Mapped[str] = mapped_column(
        ForeignKey("curriculum_folder_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_code: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    field_schema_json: Mapped[str] = mapped_column(Text, default="{}")
    schema_version: Mapped[str] = mapped_column(Text, default="v1")
    status: Mapped[str] = mapped_column(Text, default="active")
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    curriculum_folder_node: Mapped[CurriculumFolderNode] = relationship()
    instances: Mapped[list["YamlInstance"]] = relationship(back_populates="template")


class YamlInstance(Base):
    __tablename__ = "yaml_instances"
    __table_args__ = (
        CheckConstraint("status IN ('draft','final','archived')", name="ck_yaml_instances_status"),
        Index("ix_yaml_instances_template_id", "template_id"),
        Index("ix_yaml_instances_status", "status"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("yaml_templates.id", ondelete="RESTRICT"),
        nullable=False,
    )
    instance_name: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(Text, default="draft")
    values_json: Mapped[str] = mapped_column(Text, default="{}")
    rendered_yaml_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    template: Mapped[YamlTemplate] = relationship(back_populates="instances")
    property_values: Mapped[list["YamlInstancePropertyValue"]] = relationship(back_populates="instance")


class YamlVariantRelationship(Base):
    __tablename__ = "yaml_variant_relationships"
    __table_args__ = (
        UniqueConstraint(
            "from_instance_id",
            "to_instance_id",
            "relation_type",
            name="uq_yaml_variant_relationships_edge_type",
        ),
        CheckConstraint("relation_type IN ('clone','variant','derived','merge')", name="ck_yaml_variant_relationships_type"),
        CheckConstraint("from_instance_id <> to_instance_id", name="ck_yaml_variant_relationships_no_self"),
        Index("ix_yaml_variant_relationships_from_instance_id", "from_instance_id"),
        Index("ix_yaml_variant_relationships_to_instance_id", "to_instance_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_instance_id: Mapped[str] = mapped_column(
        ForeignKey("yaml_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    to_instance_id: Mapped[str] = mapped_column(
        ForeignKey("yaml_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(Text, default="variant")
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PropertyDefinition(Base):
    __tablename__ = "property_definitions"
    __table_args__ = (
        UniqueConstraint("defined_at_curriculum_node_id", "canonical_path", name="uq_property_definitions_curriculum_node_path"),
        CheckConstraint(
            "data_type IN ('text','bool','number','json','array','enum','object')",
            name="ck_property_definitions_data_type",
        ),
        Index("ix_property_definitions_defined_at_curriculum_node_id", "defined_at_curriculum_node_id"),
        Index("ix_property_definitions_parent_property_id", "parent_property_id"),
        Index("ix_property_definitions_canonical_path", "canonical_path"),
    )

    id: Mapped[str] = mapped_column(primary_key=True)
    defined_at_curriculum_node_id: Mapped[str] = mapped_column(Text, nullable=False)
    parent_property_id: Mapped[str | None] = mapped_column(
        ForeignKey("property_definitions.id", ondelete="CASCADE"),
        nullable=True,
    )
    label: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    property_key: Mapped[str] = mapped_column(Text, default="")
    canonical_path: Mapped[str] = mapped_column(Text, default="")
    data_type: Mapped[str] = mapped_column(Text, default="text")
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    parent_property: Mapped["PropertyDefinition | None"] = relationship(
        back_populates="child_properties",
        remote_side=lambda: [PropertyDefinition.id],
    )
    child_properties: Mapped[list["PropertyDefinition"]] = relationship(
        back_populates="parent_property",
        cascade="all, delete-orphan",
    )
    instance_values: Mapped[list["YamlInstancePropertyValue"]] = relationship(back_populates="property_definition")


class YamlInstancePropertyValue(Base):
    __tablename__ = "yaml_instance_property_values"
    __table_args__ = (
        UniqueConstraint("instance_id", "property_definition_id", name="uq_yaml_instance_property_values_pair"),
        Index("ix_yaml_instance_property_values_instance_id", "instance_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instance_id: Mapped[str] = mapped_column(
        ForeignKey("yaml_instances.id", ondelete="CASCADE"),
        nullable=False,
    )
    property_definition_id: Mapped[str] = mapped_column(
        ForeignKey("property_definitions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    value_json: Mapped[str] = mapped_column(Text, default="null")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    instance: Mapped[YamlInstance] = relationship(back_populates="property_values")
    property_definition: Mapped[PropertyDefinition] = relationship(back_populates="instance_values")
