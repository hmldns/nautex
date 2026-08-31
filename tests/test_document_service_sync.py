"""Integration tests for timestamp-gated document sync in DocumentService."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import nautex.services.document_service as document_service_module
from nautex.api.api_models import Document, ImplementationPlan, Node
from nautex.services.document_service import DocumentService
from nautex.services.docs_meta import SYNC_META_FILENAME, DocsSyncMeta

TS_OLD = "2026-07-07T10:00:00+00:00"
TS_NEW = "2026-07-07T11:00:00+00:00"


def make_document(designator: str, updated_at=TS_OLD) -> Document:
    return Document(
        designator=designator,
        title=f"{designator} title",
        updated_at=updated_at,
        node=Node(title="root", content=f"{designator} content"),
    )


@pytest.fixture
def docs_dir(tmp_path):
    return tmp_path / "docs"


@pytest.fixture
def api_service():
    api = MagicMock()
    api.get_document_tree = AsyncMock(
        side_effect=lambda project_id, designator: make_document(designator))
    api.get_implementation_plan = AsyncMock(return_value=ImplementationPlan(
        plan_id="plan-1", project_id="proj-1", name="Plan",
        dependency_documents=["PRD", "TRD"],
    ))
    return api


@pytest.fixture
def service(api_service, docs_dir):
    config_service = MagicMock()
    config_service.documents_path = str(docs_dir)
    return DocumentService(nautex_api_service=api_service, config_service=config_service)


def synced_state(service_obj, docs_dir, designators=("PRD", "TRD"), updated_at=TS_OLD):
    """Pre-populate docs dir + metafile as if a sync already happened."""
    meta = DocsSyncMeta.load(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    for designator in designators:
        (docs_dir / f"{designator}.md").write_text(f"{designator} content")
        meta.record_sync(designator, updated_at=updated_at, path=f"{designator}.md")
    meta.save()


@pytest.mark.asyncio
async def test_fresh_sync_fetches_all_and_stamps_meta(service, api_service, docs_dir):
    meta_map = {"PRD": TS_OLD, "TRD": TS_OLD}
    results = await service.ensure_documents("proj-1", ["PRD", "TRD"], documents_updated_at=meta_map)

    assert api_service.get_document_tree.await_count == 2
    assert (docs_dir / "PRD.md").exists()
    assert (docs_dir / "TRD.md").exists()
    assert results["PRD"] == str(docs_dir / "PRD.md")

    stored = DocsSyncMeta.load(docs_dir)
    assert stored.get("PRD").updated_at == TS_OLD
    assert stored.get("TRD").updated_at == TS_OLD


@pytest.mark.asyncio
async def test_document_is_written_atomically_as_utf8(service, docs_dir, monkeypatch):
    document = Document(
        designator="MDS",
        title="MDS title",
        updated_at=TS_OLD,
        node=Node(title="root", content="Flow → result; subset ⊆ set"),
    )
    output_path = docs_dir / "MDS.md"
    open_calls = []
    real_open = document_service_module.aiofiles.open

    def recording_open(*args, **kwargs):
        open_calls.append((args, kwargs))
        return real_open(*args, **kwargs)

    monkeypatch.setattr(document_service_module.aiofiles, "open", recording_open)

    success, result = await service.save_document_to_file(document, output_path)

    assert success, result
    assert "Flow → result; subset ⊆ set" in output_path.read_text(encoding="utf-8")
    assert open_calls[0][1]["encoding"] == "utf-8"
    assert open_calls[0][1]["newline"] == "\n"
    assert open_calls[0][0][0] != output_path
    assert not list(docs_dir.glob(".MDS.md.*.tmp"))


@pytest.mark.asyncio
async def test_failed_atomic_replace_preserves_existing_document(
    service, docs_dir, monkeypatch
):
    docs_dir.mkdir(parents=True)
    output_path = docs_dir / "MDS.md"
    output_path.write_text("last good version", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(document_service_module.os, "replace", fail_replace)

    success, result = await service.save_document_to_file(
        make_document("MDS"), output_path
    )

    assert not success
    assert "simulated replace failure" in result
    assert output_path.read_text(encoding="utf-8") == "last good version"
    assert not list(docs_dir.glob(".MDS.md.*.tmp"))


@pytest.mark.asyncio
async def test_unchanged_docs_skip_fetch(service, api_service, docs_dir):
    synced_state(service, docs_dir)

    results = await service.ensure_documents(
        "proj-1", ["PRD", "TRD"], documents_updated_at={"PRD": TS_OLD, "TRD": TS_OLD})

    api_service.get_document_tree.assert_not_awaited()
    assert results == {"PRD": str(docs_dir / "PRD.md"), "TRD": str(docs_dir / "TRD.md")}


@pytest.mark.asyncio
async def test_changed_doc_refetched_others_skipped(service, api_service, docs_dir):
    synced_state(service, docs_dir)

    await service.ensure_documents(
        "proj-1", ["PRD", "TRD"], documents_updated_at={"PRD": TS_NEW, "TRD": TS_OLD})

    assert api_service.get_document_tree.await_count == 1
    assert api_service.get_document_tree.await_args.args[1] == "PRD"


@pytest.mark.asyncio
async def test_missing_local_file_refetched(service, api_service, docs_dir):
    synced_state(service, docs_dir)
    (docs_dir / "PRD.md").unlink()

    await service.ensure_documents(
        "proj-1", ["PRD", "TRD"], documents_updated_at={"PRD": TS_OLD, "TRD": TS_OLD})

    assert api_service.get_document_tree.await_count == 1
    assert (docs_dir / "PRD.md").exists()


@pytest.mark.asyncio
async def test_empty_local_file_refetched(service, api_service, docs_dir):
    synced_state(service, docs_dir)
    (docs_dir / "PRD.md").write_bytes(b"")

    await service.ensure_documents(
        "proj-1", ["PRD", "TRD"],
        documents_updated_at={"PRD": TS_OLD, "TRD": TS_OLD},
    )

    assert api_service.get_document_tree.await_count == 1
    assert (docs_dir / "PRD.md").stat().st_size > 0


@pytest.mark.asyncio
async def test_malformed_metafile_triggers_full_refetch(service, api_service, docs_dir):
    synced_state(service, docs_dir)
    (docs_dir / SYNC_META_FILENAME).write_text("{corrupt")

    await service.ensure_documents(
        "proj-1", ["PRD", "TRD"], documents_updated_at={"PRD": TS_OLD, "TRD": TS_OLD})

    assert api_service.get_document_tree.await_count == 2
    # Metafile is rewritten valid.
    assert DocsSyncMeta.load(docs_dir).get("PRD").updated_at == TS_OLD


@pytest.mark.asyncio
async def test_malformed_stored_or_server_ts_refetched(service, api_service, docs_dir):
    synced_state(service, docs_dir, designators=("TRD",))
    meta = DocsSyncMeta.load(docs_dir)
    (docs_dir / "PRD.md").write_text("PRD content")
    meta.record_sync("PRD", updated_at="garbage", path="PRD.md")
    meta.save()

    # Malformed stored ts → PRD refetched; malformed server ts → TRD refetched.
    await service.ensure_documents(
        "proj-1", ["PRD", "TRD"], documents_updated_at={"PRD": TS_OLD, "TRD": "not-a-ts"})

    assert api_service.get_document_tree.await_count == 2


@pytest.mark.asyncio
async def test_null_server_ts_always_refetched(service, api_service, docs_dir):
    # New document: present in meta map with null timestamp.
    synced_state(service, docs_dir, designators=("NEW",))

    await service.ensure_documents("proj-1", ["NEW"], documents_updated_at={"NEW": None})
    assert api_service.get_document_tree.await_count == 1


@pytest.mark.asyncio
async def test_legacy_backend_without_meta_fetches_all(service, api_service, docs_dir):
    results = await service.ensure_plan_dependency_documents("proj-1", "plan-1")

    api_service.get_implementation_plan.assert_awaited_once()
    assert api_service.get_document_tree.await_count == 2
    assert set(results) == {"PRD", "TRD"}
    # Meta still stamped from Document.updated_at for a future backend upgrade.
    assert DocsSyncMeta.load(docs_dir).get("PRD").updated_at == TS_OLD


@pytest.mark.asyncio
async def test_meta_keys_used_as_dependency_list_without_plan_fetch(service, api_service, docs_dir):
    results = await service.ensure_plan_dependency_documents(
        "proj-1", "plan-1", documents_updated_at={"PRD": TS_OLD})

    api_service.get_implementation_plan.assert_not_awaited()
    assert set(results) == {"PRD"}
    assert api_service.get_document_tree.await_count == 1


@pytest.mark.asyncio
async def test_empty_meta_means_no_dependencies(service, api_service):
    results = await service.ensure_plan_dependency_documents(
        "proj-1", "plan-1", documents_updated_at={})

    assert results == {}
    api_service.get_implementation_plan.assert_not_awaited()
    api_service.get_document_tree.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_fetch_records_error_and_no_meta_entry(service, api_service, docs_dir):
    api_service.get_document_tree = AsyncMock(return_value=None)

    results = await service.ensure_documents("proj-1", ["PRD"], documents_updated_at={"PRD": TS_OLD})

    assert results["PRD"] == "Document PRD not found"
    assert DocsSyncMeta.load(docs_dir).get("PRD") is None


@pytest.mark.asyncio
async def test_updated_at_fallback_to_scope_meta(service, api_service, docs_dir):
    api_service.get_document_tree = AsyncMock(
        side_effect=lambda project_id, designator: make_document(designator, updated_at=None))

    await service.ensure_documents("proj-1", ["PRD"], documents_updated_at={"PRD": TS_NEW})
    assert DocsSyncMeta.load(docs_dir).get("PRD").updated_at == TS_NEW


@pytest.mark.asyncio
async def test_no_timestamp_anywhere_refetches_next_time(service, api_service, docs_dir):
    api_service.get_document_tree = AsyncMock(
        side_effect=lambda project_id, designator: make_document(designator, updated_at=None))

    await service.ensure_documents("proj-1", ["PRD"], documents_updated_at={"PRD": None})
    assert DocsSyncMeta.load(docs_dir).get("PRD").updated_at is None

    # Second run: stored ts is null → rule fires again → refetch.
    await service.ensure_documents("proj-1", ["PRD"], documents_updated_at={"PRD": None})
    assert api_service.get_document_tree.await_count == 2


class TestServerTimeReferenceClock:
    """server_time from the scope response shields staleness checks from a broken local clock."""

    @pytest.mark.asyncio
    async def test_stored_ts_future_relative_to_server_time_refetches(self, service, api_service, docs_dir):
        # Stored ts is in the LOCAL past, so only the server clock explains a refetch.
        synced_state(service, docs_dir, designators=("PRD",), updated_at=TS_NEW)

        await service.ensure_documents(
            "proj-1", ["PRD"], documents_updated_at={"PRD": TS_NEW}, server_time=TS_OLD)

        assert api_service.get_document_tree.await_count == 1

    @pytest.mark.asyncio
    async def test_consistent_server_time_skips(self, service, api_service, docs_dir):
        synced_state(service, docs_dir, designators=("PRD",), updated_at=TS_NEW)

        await service.ensure_documents(
            "proj-1", ["PRD"], documents_updated_at={"PRD": TS_NEW}, server_time=TS_NEW)

        api_service.get_document_tree.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_malformed_server_time_falls_back_to_local_clock(self, service, api_service, docs_dir):
        synced_state(service, docs_dir, designators=("PRD",), updated_at=TS_OLD)

        await service.ensure_documents(
            "proj-1", ["PRD"], documents_updated_at={"PRD": TS_OLD}, server_time="garbage")

        api_service.get_document_tree.assert_not_awaited()


class TestForceDocsSyncFlag:
    """next_scope(force_docs_sync=True) bypasses the timestamp skip entirely."""

    def _wire_mcp(self, api_service, docs_dir):
        from nautex.api.scope_context_model import ScopeContext, ScopeContextMode
        from nautex.models.config import NautexConfig, MCPOutputFormat
        from nautex.services.mcp_service import MCPService, mcp_server_set_service_instance
        from nautex.services.document_service import DocumentService
        from nautex.commands import set_service_instance

        scope = ScopeContext(
            tasks=[], mode=ScopeContextMode.ExecuteSubtasks, focus_tasks=[],
            documents_updated_at={"PRD": TS_OLD, "TRD": TS_OLD}, server_time=TS_OLD)
        api_service.next_scope = AsyncMock(return_value=scope)

        config_service = MagicMock()
        config_service.documents_path = str(docs_dir)
        config_service.config = NautexConfig(
            project_id="proj-1", plan_id="plan-1", response_format=MCPOutputFormat.JSON)

        doc_service = DocumentService(nautex_api_service=api_service, config_service=config_service)
        svc = MCPService(config_service=config_service, nautex_api_service=api_service,
                         integration_status_service=MagicMock(), document_service=doc_service)
        svc.is_configured = lambda: True
        mcp_server_set_service_instance(svc)
        set_service_instance(svc)

    @pytest.mark.asyncio
    async def test_default_skips_up_to_date_docs(self, service, api_service, docs_dir):
        from nautex.commands import mcp_handle_next_scope
        synced_state(service, docs_dir)
        self._wire_mcp(api_service, docs_dir)

        result = await mcp_handle_next_scope()
        assert result.success, result.error
        api_service.get_document_tree.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_flag_refetches_everything(self, service, api_service, docs_dir):
        from nautex.commands import mcp_handle_next_scope
        synced_state(service, docs_dir)
        self._wire_mcp(api_service, docs_dir)

        result = await mcp_handle_next_scope(force_docs_sync=True)
        assert result.success, result.error
        assert api_service.get_document_tree.await_count == 2
