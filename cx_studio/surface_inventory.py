"""Docs-driven CX Agent Studio surface inventory and portability builders."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Callable

from portability.types import (
    ExportReadinessStatus,
    ImportCoverageStatus,
    ParityStatus,
    PortabilityStatus,
    PortabilitySurface,
    ProjectionQualityStatus,
)

from .types import CxAgentSnapshot


_AGENT_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents"
_PLAYBOOK_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.playbooks"
_FLOW_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.flows"
_PAGE_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.flows.pages"
_INTENT_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.intents"
_ENTITY_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.entityTypes"
_WEBHOOK_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.webhooks"
_TEST_CASE_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.testCases"
_ENVIRONMENT_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.environments"
_TOOL_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.tools"
_GENERATOR_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.generators"
_ROUTE_GROUP_DOC = (
    "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3/projects.locations.agents.transitionRouteGroups"
)
_OVERVIEW_DOC = "https://docs.cloud.google.com/dialogflow/cx/docs/reference/rest/v3-overview"


@dataclass(frozen=True)
class SurfaceEvidence:
    """Concrete evidence captured for one surface in a specific snapshot."""

    coverage_status: ImportCoverageStatus
    source_refs: list[str]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CxSurfaceDefinition:
    """One docs-backed CX surface and its current support classification."""

    surface_id: str
    label: str
    parity_status: ParityStatus
    portability_when_present: PortabilityStatus
    export_when_present: ExportReadinessStatus
    optimization_surface_id: str
    documentation_refs: tuple[str, ...]
    code_refs: tuple[str, ...]
    notes: str
    detector: Callable[[CxAgentSnapshot], SurfaceEvidence]
    projection_quality_when_present: ProjectionQualityStatus | None = None

    def build_surface(self, snapshot: CxAgentSnapshot) -> PortabilitySurface:
        """Materialize one runtime portability row for the given snapshot."""

        evidence = self.detector(snapshot)
        portability_status = (
            self.portability_when_present
            if evidence.coverage_status != ImportCoverageStatus.MISSING
            else PortabilityStatus.UNSUPPORTED
        )
        export_status = (
            self.export_when_present
            if evidence.coverage_status != ImportCoverageStatus.MISSING
            else ExportReadinessStatus.BLOCKED
        )

        return PortabilitySurface(
            surface_id=self.surface_id,
            label=self.label,
            coverage_status=evidence.coverage_status,
            parity_status=self.parity_status,
            portability_status=portability_status,
            export_status=export_status,
            optimization_surface_id=self.optimization_surface_id,
            projection_quality=(
                self.projection_quality_when_present
                if evidence.coverage_status != ImportCoverageStatus.MISSING
                else None
            ),
            rationale=[self.notes],
            source_refs=evidence.source_refs,
            documentation_refs=list(self.documentation_refs),
            code_refs=list(self.code_refs),
            metadata=evidence.metadata,
        )


@dataclass(frozen=True)
class CxSurfaceInventoryRow:
    """Serialized docs-driven checklist row for the repo and API consumers."""

    surface_id: str
    label: str
    support_level: str
    import_contract: str
    optimization_contract: str
    export_contract: str
    documentation_refs: list[str]
    code_refs: list[str]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""

        return asdict(self)


def _evidence(
    coverage_status: ImportCoverageStatus,
    source_refs: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> SurfaceEvidence:
    """Construct a normalized evidence record."""

    return SurfaceEvidence(
        coverage_status=coverage_status,
        source_refs=source_refs or [],
        metadata=metadata or {},
    )


def _instruction_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [playbook.name for playbook in snapshot.playbooks if playbook.instruction_text]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs, {"playbook_count": len(refs)})
    if snapshot.agent.description:
        return _evidence(ImportCoverageStatus.IMPORTED, [snapshot.agent.name])
    return _evidence(ImportCoverageStatus.MISSING)


def _model_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    llm_settings = snapshot.agent.generative_settings.get("llmModelSettings", {})
    model = llm_settings.get("model") if isinstance(llm_settings, dict) else None
    if isinstance(model, str) and model:
        return _evidence(ImportCoverageStatus.IMPORTED, [snapshot.agent.name], {"model": model})
    return _evidence(ImportCoverageStatus.MISSING)


def _webhook_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.webhooks:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [webhook.name for webhook in snapshot.webhooks],
            {"webhook_count": len(snapshot.webhooks)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _routing_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    flow_routes = [
        flow.name
        for flow in snapshot.flows
        if flow.transition_routes or flow.event_handlers or any(page.transition_routes for page in flow.pages)
    ]
    if flow_routes or snapshot.intents:
        refs = flow_routes + [intent.name for intent in snapshot.intents]
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            refs,
            {"route_count": sum(len(flow.transition_routes) for flow in snapshot.flows)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _flows_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.flows:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [flow.name for flow in snapshot.flows],
            {"flow_count": len(snapshot.flows), "page_count": sum(len(flow.pages) for flow in snapshot.flows)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _intents_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.intents:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [intent.name for intent in snapshot.intents],
            {"intent_count": len(snapshot.intents)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _entity_types_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.entity_types:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [entity_type.name for entity_type in snapshot.entity_types],
            {"entity_type_count": len(snapshot.entity_types)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _test_case_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.test_cases:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [test_case.name for test_case in snapshot.test_cases],
            {"test_case_count": len(snapshot.test_cases)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _missing_evidence(_snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    return _evidence(ImportCoverageStatus.MISSING)


def _topology_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.flows:
        refs = [flow.name for flow in snapshot.flows]
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            refs,
            {"page_count": sum(len(flow.pages) for flow in snapshot.flows)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _tool_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.tools:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [tool.name for tool in snapshot.tools],
            {"tool_count": len(snapshot.tools)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _speech_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.agent.speech_to_text_settings or snapshot.agent.text_to_speech_settings:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [snapshot.agent.name],
            {
                "has_speech_to_text_settings": bool(snapshot.agent.speech_to_text_settings),
                "has_text_to_speech_settings": bool(snapshot.agent.text_to_speech_settings),
            },
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _playbook_parameters_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [
        playbook.name
        for playbook in snapshot.playbooks
        if playbook.input_parameter_definitions or playbook.output_parameter_definitions
    ]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _playbook_handlers_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [playbook.name for playbook in snapshot.playbooks if playbook.handlers]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _playbook_code_blocks_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [playbook.name for playbook in snapshot.playbooks if playbook.code_block]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _playbook_examples_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [playbook.name for playbook in snapshot.playbooks if playbook.examples]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _page_forms_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [
        page.name
        for flow in snapshot.flows
        for page in flow.pages
        if page.form
    ]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _intent_parameters_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [intent.name for intent in snapshot.intents if intent.parameters]
    if refs:
        return _evidence(ImportCoverageStatus.IMPORTED, refs)
    return _evidence(ImportCoverageStatus.MISSING)


def _transition_route_groups_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.transition_route_groups:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [route_group.name for route_group in snapshot.transition_route_groups],
            {"transition_route_group_count": len(snapshot.transition_route_groups)},
        )

    refs = [
        route_group
        for flow in snapshot.flows
        for route_group in flow.transition_route_groups
    ]
    refs.extend(
        route_group
        for flow in snapshot.flows
        for page in flow.pages
        for route_group in page.transition_route_groups
    )
    if refs:
        return _evidence(
            ImportCoverageStatus.PARTIAL,
            list(dict.fromkeys(refs)),
            {"transition_route_group_count": len(set(refs))},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _generator_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.generators:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [generator.name for generator in snapshot.generators],
            {"generator_count": len(snapshot.generators)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _environment_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    if snapshot.environments:
        return _evidence(
            ImportCoverageStatus.IMPORTED,
            [environment.name for environment in snapshot.environments],
            {"environment_count": len(snapshot.environments)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


def _version_evidence(snapshot: CxAgentSnapshot) -> SurfaceEvidence:
    refs = [
        str(version_config.get("version", ""))
        for environment in snapshot.environments
        for version_config in environment.version_configs
        if version_config.get("version")
    ]
    if refs:
        return _evidence(
            ImportCoverageStatus.REFERENCED,
            refs,
            {"referenced_version_count": len(refs)},
        )
    return _evidence(ImportCoverageStatus.MISSING)


_DEFINITIONS: tuple[CxSurfaceDefinition, ...] = (
    CxSurfaceDefinition(
        surface_id="instructions",
        label="Instructions",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="instructions",
        documentation_refs=(_PLAYBOOK_DOC, _AGENT_DOC),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_agent_mapper.py", "cx_studio/exporter.py"),
        notes="Playbook instructions and fallback agent descriptions map cleanly into AgentLab prompts and round-trip back.",
        detector=_instruction_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="model",
        label="Model Selection",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="model_selection",
        documentation_refs=(_AGENT_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_agent_mapper.py", "cx_studio/exporter.py"),
        notes="The current contract supports the active LLM model path inside agent generative settings.",
        detector=_model_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="webhooks",
        label="Webhooks",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="tool_runtime_config",
        documentation_refs=(_WEBHOOK_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py", "adapters/cx_agent_mapper.py", "cx_studio/exporter.py"),
        notes="Webhook URL, headers, timeout, and enabled state import into the workspace and round-trip back today.",
        detector=_webhook_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="routing",
        label="Routing",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="routing",
        documentation_refs=(_FLOW_DOC, _PAGE_DOC, _INTENT_DOC),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_agent_mapper.py", "cx_studio/exporter.py"),
        notes="Flow routes, page routes, route-group references, and intent cues are now exposed as editable CX-native routing structures.",
        detector=_routing_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="flows",
        label="Flows and Pages",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="workflow_topology",
        documentation_refs=(_FLOW_DOC, _PAGE_DOC),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py", "cx_studio/portability.py"),
        notes="Flow and page resources are fetched into typed CX-native structures and the writable subset now round-trips through the exporter.",
        detector=_flows_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="workflow_topology",
        label="Workflow Topology",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="workflow_topology",
        documentation_refs=(_FLOW_DOC, _PAGE_DOC),
        code_refs=("cx_studio/surface_inventory.py", "cx_studio/portability.py"),
        notes="The report exposes graph shape for review, but structural topology edits are not part of the editable workspace contract.",
        detector=_topology_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="intents",
        label="Intents",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="routing",
        documentation_refs=(_INTENT_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py", "adapters/cx_agent_mapper.py"),
        notes="Intent training phrases are now imported into typed CX-native records and written back through the exporter.",
        detector=_intents_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="intent_parameters",
        label="Intent Parameters",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="routing",
        documentation_refs=(_INTENT_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Intent parameter schemas are now imported into editable CX-native records and exported with their parent intent.",
        detector=_intent_parameters_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="entity_types",
        label="Entity Types",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="tool_runtime_config",
        documentation_refs=(_ENTITY_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py", "cx_studio/exporter.py"),
        notes="Entity types are now represented as editable CX-native records and round-trip through the exporter.",
        detector=_entity_types_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="app_tools",
        label="App Tools",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="tool_runtime_config",
        documentation_refs=(_TOOL_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py", "adapters/cx_agent_mapper.py"),
        notes="Tool resources are now discoverable and classified, but the workspace only carries a thin description and cannot write them back.",
        detector=_tool_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="callbacks",
        label="Callbacks",
        parity_status=ParityStatus.UNSUPPORTED,
        portability_when_present=PortabilityStatus.UNSUPPORTED,
        export_when_present=ExportReadinessStatus.BLOCKED,
        projection_quality_when_present=ProjectionQualityStatus.PRESERVED_ONLY,
        optimization_surface_id="callbacks",
        documentation_refs=(_GENERATOR_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "cx_studio/portability.py"),
        notes="AgentLab does not currently map CX generator processors into the shared callback contract.",
        detector=_missing_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="agent_speech_settings",
        label="Speech Settings",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        projection_quality_when_present=ProjectionQualityStatus.PRESERVED_ONLY,
        optimization_surface_id="model_selection",
        documentation_refs=(_AGENT_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Speech-to-text and text-to-speech settings are fetched from the agent resource but are not editable in the workspace contract.",
        detector=_speech_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="playbook_parameters",
        label="Playbook Parameters",
        parity_status=ParityStatus.SUPPORTED,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="instructions",
        documentation_refs=(_PLAYBOOK_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Playbook parameter definitions are now surfaced in typed CX-native records and exported with playbook updates.",
        detector=_playbook_parameters_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="playbook_handlers",
        label="Playbook Handlers",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="instructions",
        documentation_refs=(_PLAYBOOK_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Playbook handlers are now editable in the CX-native contract and export with playbook updates.",
        detector=_playbook_handlers_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="playbook_code_blocks",
        label="Playbook Code Blocks",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="instructions",
        documentation_refs=(_PLAYBOOK_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Inline playbook code blocks are fetched into the snapshot for visibility only.",
        detector=_playbook_code_blocks_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="playbook_examples",
        label="Playbook Examples",
        parity_status=ParityStatus.UNSUPPORTED,
        portability_when_present=PortabilityStatus.UNSUPPORTED,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="few_shot_examples",
        documentation_refs=(_PLAYBOOK_DOC, _OVERVIEW_DOC),
        code_refs=("cx_studio/surface_inventory.py", "cx_studio/importer.py"),
        notes="The current client does not fetch the dedicated playbook examples resource, so AgentLab cannot classify or round-trip it from a live import.",
        detector=_playbook_examples_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="page_forms",
        label="Page Forms",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="workflow_topology",
        documentation_refs=(_PAGE_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Page forms are now editable inside the CX-native page contract and exported through page updates.",
        detector=_page_forms_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="transition_route_groups",
        label="Transition Route Groups",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="routing",
        documentation_refs=(_ROUTE_GROUP_DOC, _FLOW_DOC),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Transition route groups are now fetched as first-class resources, editable in the CX-native contract, and exportable through the CX client.",
        detector=_transition_route_groups_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="generators",
        label="Generators",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.OPTIMIZABLE,
        export_when_present=ExportReadinessStatus.READY,
        projection_quality_when_present=ProjectionQualityStatus.FAITHFUL,
        optimization_surface_id="callbacks",
        documentation_refs=(_GENERATOR_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Generator resources are now surfaced as editable CX-native records and the prompt/model subset exports back through the CX client.",
        detector=_generator_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="test_cases",
        label="Imported Test Cases",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="few_shot_examples",
        documentation_refs=(_TEST_CASE_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_agent_mapper.py", "cx_studio/importer.py"),
        notes="CX test cases are turned into starter evals, but the exporter does not write them back to CX.",
        detector=_test_case_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="environments",
        label="Environments",
        parity_status=ParityStatus.READ_ONLY,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="workflow_topology",
        documentation_refs=(_ENVIRONMENT_DOC,),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="Environment records are fetched for deployment context, but they are not editable through the workspace config.",
        detector=_environment_evidence,
    ),
    CxSurfaceDefinition(
        surface_id="versions",
        label="Versions",
        parity_status=ParityStatus.PARTIAL,
        portability_when_present=PortabilityStatus.READ_ONLY,
        export_when_present=ExportReadinessStatus.BLOCKED,
        optimization_surface_id="workflow_topology",
        documentation_refs=(_ENVIRONMENT_DOC, _OVERVIEW_DOC),
        code_refs=("cx_studio/surface_inventory.py", "adapters/cx_studio_client.py"),
        notes="The importer can see version references via environment configs, but it does not fetch or mutate version resources themselves.",
        detector=_version_evidence,
    ),
)


def build_cx_portability_surfaces(snapshot: CxAgentSnapshot) -> list[PortabilitySurface]:
    """Return the docs-driven portability rows for one CX snapshot."""

    return [definition.build_surface(snapshot) for definition in _DEFINITIONS]


def build_cx_surface_matrix() -> dict[str, Any]:
    """Return the static docs-driven support matrix used by docs and tests."""

    rows = [
        CxSurfaceInventoryRow(
            surface_id=definition.surface_id,
            label=definition.label,
            support_level=definition.parity_status.value,
            import_contract=_import_contract(definition.parity_status),
            optimization_contract=_optimization_contract(definition.parity_status),
            export_contract=_export_contract(definition.export_when_present),
            documentation_refs=list(definition.documentation_refs),
            code_refs=list(definition.code_refs),
            notes=definition.notes,
        ).to_dict()
        for definition in _DEFINITIONS
    ]

    counts = Counter(row["support_level"] for row in rows)
    return {
        "summary": {
            "total_surfaces": len(rows),
            "support_level_counts": {
                "supported": counts.get("supported", 0),
                "partial": counts.get("partial", 0),
                "read_only": counts.get("read_only", 0),
                "unsupported": counts.get("unsupported", 0),
            },
        },
        "surfaces": rows,
    }


def _import_contract(parity_status: ParityStatus) -> str:
    """Describe how well the current importer classifies the surface."""

    if parity_status == ParityStatus.SUPPORTED:
        return "live_imported"
    if parity_status == ParityStatus.READ_ONLY:
        return "live_imported"
    if parity_status == ParityStatus.PARTIAL:
        return "partially_imported"
    return "not_imported"


def _optimization_contract(parity_status: ParityStatus) -> str:
    """Describe how well the current workspace can optimize the surface."""

    if parity_status == ParityStatus.SUPPORTED:
        return "editable"
    if parity_status == ParityStatus.PARTIAL:
        return "limited"
    if parity_status == ParityStatus.READ_ONLY:
        return "report_only"
    return "unavailable"


def _export_contract(status: ExportReadinessStatus) -> str:
    """Normalize export readiness for the checklist view."""

    if status == ExportReadinessStatus.READY:
        return "round_trip_ready"
    if status == ExportReadinessStatus.LOSSY:
        return "lossy"
    return "blocked"
