"""Per-case probe runner: connect → prompt(s) → disconnect.

Wraps `ACPAgentAdapter` directly (no backend, no WS uplink). Captures:
- every ConsolidatedSessionUpdate (CSU) from both system and prompt phases
- every permission request + our probe response
- concatenated agent message text (the "visible" reply)
- filesystem diff of the sandboxed workdir
- stop reasons, timings, adapter state transitions
- agent subprocess stderr (best-effort)

Writes artifacts under `<out>/<agent>/<scenario>/`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("session_config_probe")

from nautex.gateway.adapters.acp_adapter import create_adapter
from nautex.gateway.config import AgentBinaryNotFoundError, validate_binary, get_registration
from nautex.gateway.models import AgentSessionConfig, PromptContent
from nautex.gateway.protocol import (
    ConsolidatedSessionUpdate,
    PermissionRequestPayload,
    PermissionResponsePayload,
)
from nautex.gateway.protocol.enums import SessionUpdateKind

from session_config_scenarios import Assertion, CaseContext, Scenario


SEED_FILES: Dict[str, str] = {
    "README.md": (
        "# Probe Sandbox\n\n"
        "This directory is a disposable workspace the probe creates per case.\n"
        "It seeds a couple of small files so read/search scenarios have targets.\n"
    ),
    "src/sample.py": (
        "def greet(name: str) -> str:\n"
        "    return f'Hello, {name}'\n"
    ),
    "notes/todo.txt": "- investigate permission flows\n- add more scenarios\n",
}


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def seed_workdir(root: Path) -> None:
    for rel, body in SEED_FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")


def snapshot_fs(root: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            try:
                data = p.read_bytes()
            except OSError:
                continue
            out[rel] = {
                "size": len(data),
                "sha8": hashlib.sha256(data).hexdigest()[:8],
            }
    return out


def diff_fs(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, List[str]]:
    before_keys = set(before)
    after_keys = set(after)
    created = sorted(after_keys - before_keys)
    deleted = sorted(before_keys - after_keys)
    modified = sorted(
        k for k in (before_keys & after_keys)
        if before[k]["sha8"] != after[k]["sha8"] or before[k]["size"] != after[k]["size"]
    )
    return {"created": created, "modified": modified, "deleted": deleted}


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if is_dataclass(model):
        return asdict(model)
    return model


class _JSONL:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")

    def write(self, obj: Any) -> None:
        self._fh.write(json.dumps(obj, default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        try:
            self._fh.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Case runner
# ---------------------------------------------------------------------------


class CaseRunner:
    def __init__(
        self,
        agent_id: str,
        scenario: Scenario,
        out_dir: Path,
        timeout_s: float,
        keep_workdir: bool,
    ):
        self.agent_id = agent_id
        self.scenario = scenario
        self.out_dir = out_dir
        self.timeout_s = timeout_s
        self.keep_workdir = keep_workdir

        self.workdir = Path(tempfile.mkdtemp(prefix=f"probe-{agent_id}-{scenario.id}-"))
        self.case_dir = out_dir / agent_id / scenario.id
        self.case_dir.mkdir(parents=True, exist_ok=True)

        self.csus: List[Dict[str, Any]] = []
        self.csu_log = _JSONL(self.case_dir / "csus.jsonl")
        self.perm_log = _JSONL(self.case_dir / "permissions.jsonl")
        self.permissions: List[Dict[str, Any]] = []
        self.stdout_parts: List[str] = []

    # --- Callbacks wired into the adapter ----------------------------------

    def _record_csu(self, csu: ConsolidatedSessionUpdate, phase: str) -> None:
        rec = _dump(csu)
        rec["_phase"] = phase
        rec["_ts"] = _now_iso()
        self.csus.append(rec)
        self.csu_log.write(rec)
        if csu.kind in (SessionUpdateKind.AGENT_MESSAGE, SessionUpdateKind.AGENT_THOUGHT):
            if csu.text:
                self.stdout_parts.append(csu.text)

    async def _on_system_event(self, csu: ConsolidatedSessionUpdate) -> None:
        self._record_csu(csu, phase="system")

    async def _on_update(self, csu: ConsolidatedSessionUpdate) -> None:
        self._record_csu(csu, phase="prompt")

    async def _on_permission(self, prp: PermissionRequestPayload) -> PermissionResponsePayload:
        resp = self.scenario.on_permission(prp)
        pair = {
            "request": _dump(prp),
            "response": _dump(resp),
            "_ts": _now_iso(),
        }
        self.permissions.append(pair)
        self.perm_log.write(pair)
        return resp

    # --- Case lifecycle ----------------------------------------------------

    async def run(self) -> Dict[str, Any]:
        started = time.monotonic()
        seed_workdir(self.workdir)
        before = snapshot_fs(self.workdir)

        config = self.scenario.build_config(self.workdir)
        (self.case_dir / "config_used.json").write_text(
            json.dumps(_dump(config), indent=2, default=str),
            encoding="utf-8",
        )

        adapter = create_adapter(self.agent_id, str(self.workdir))

        stop_reasons: List[str] = []
        errors: List[str] = []
        launch_dump: Dict[str, Any] = {}
        connect_timeout_s = max(self.timeout_s, 30.0)

        def _log_error(phase: str, exc: BaseException) -> None:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            entry = f"{phase}: {type(exc).__name__}: {exc}"
            errors.append(entry)
            logger.error("[%s/%s] %s\n%s", self.agent_id, self.scenario.id, entry, tb)
            # Persist the traceback so the LLM can read it without scrollback hunting.
            with open(self.case_dir / "errors.log", "a", encoding="utf-8") as fh:
                fh.write(f"--- {_now_iso()} {phase} ---\n{tb}\n")

        try:
            try:
                await asyncio.wait_for(
                    adapter.connect(config=config, on_system_event=self._on_system_event),
                    timeout=connect_timeout_s,
                )
            except asyncio.TimeoutError as e:
                _log_error("connect.timeout", e)
                # Bail without prompting — the adapter isn't ACTIVE.
                raise

            # Snapshot the resolved spawn arguments for reproducibility.
            launch_dump = {
                "agent_id": self.agent_id,
                "adapter_class": type(adapter).__name__,
                "registration_executable": get_registration(self.agent_id).executable,
                "registration_launch_args": list(get_registration(self.agent_id).launch_args),
                "extra_args": list(getattr(adapter._launch_adjustment, "extra_args", [])
                                    if adapter._launch_adjustment else []),
                "extra_env": dict(getattr(adapter._launch_adjustment, "extra_env", {})
                                   if adapter._launch_adjustment else {}),
                "acp_session_id": adapter._acp_session_id or "",
                "pid": adapter.pid,
            }

            session_id = adapter._acp_session_id or ""
            for idx, prompt_text in enumerate(self.scenario.prompts):
                try:
                    result = await asyncio.wait_for(
                        adapter.prompt(
                            session_id=session_id,
                            content=PromptContent(text=prompt_text),
                            on_update=self._on_update,
                            on_permission_request=self._on_permission,
                        ),
                        timeout=self.timeout_s,
                    )
                    stop_reasons.append(str(getattr(result, "stop_reason", "unknown")))
                except asyncio.TimeoutError as e:
                    stop_reasons.append("timeout")
                    _log_error(f"prompt[{idx}].timeout", e)
                    break
                except Exception as e:
                    stop_reasons.append("error")
                    _log_error(f"prompt[{idx}].exception", e)
                    break
        except Exception as e:
            # connect failures (including our re-raise above) end up here
            if not errors or errors[-1].split(":", 1)[0] != "connect.timeout":
                _log_error("connect", e)
        finally:
            try:
                await asyncio.wait_for(adapter.disconnect(), timeout=connect_timeout_s)
            except asyncio.TimeoutError as e:
                _log_error("disconnect.timeout", e)
            except Exception as e:
                _log_error("disconnect", e)
            self.csu_log.close()
            self.perm_log.close()

        after = snapshot_fs(self.workdir)
        fs_diff = diff_fs(before, after)
        stdout_text = "".join(self.stdout_parts)
        duration_ms = int((time.monotonic() - started) * 1000)

        (self.case_dir / "launch_cmd.json").write_text(
            json.dumps(launch_dump, indent=2, default=str), encoding="utf-8",
        )
        (self.case_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
        (self.case_dir / "fs_diff.json").write_text(
            json.dumps(fs_diff, indent=2), encoding="utf-8",
        )

        ctx = CaseContext(
            agent_id=self.agent_id,
            scenario_id=self.scenario.id,
            workdir=self.workdir,
            config=config,
            csus=self.csus,
            permissions=self.permissions,
            stdout_text=stdout_text,
            fs_diff=fs_diff,
            stop_reasons=stop_reasons,
            duration_ms=duration_ms,
        )

        assertions: List[Assertion] = []
        try:
            assertions = self.scenario.check(ctx)
        except Exception as e:
            assertions = [Assertion("check_function", False, f"{type(e).__name__}: {e}")]

        error_summary = " | ".join(errors) if errors else None
        passed = all(a.passed for a in assertions) and not errors
        status = "pass" if passed else "fail"
        headline = _headline(assertions, error_summary)

        result_rec = {
            "agent": self.agent_id,
            "scenario": self.scenario.id,
            "status": status,
            "stop_reasons": stop_reasons,
            "duration_ms": duration_ms,
            "assertions_passed": sum(1 for a in assertions if a.passed),
            "assertions_failed": sum(1 for a in assertions if not a.passed),
            "headline": headline,
            "errors": errors,
            "csu_count": len(self.csus),
            "permission_count": len(self.permissions),
            "fs_diff_counts": {k: len(v) for k, v in fs_diff.items()},
            "workdir": str(self.workdir),
        }
        (self.case_dir / "result.json").write_text(
            json.dumps(result_rec, indent=2, default=str), encoding="utf-8",
        )
        (self.case_dir / "assertions.json").write_text(
            json.dumps([asdict(a) for a in assertions], indent=2), encoding="utf-8",
        )

        if not self.keep_workdir:
            shutil.rmtree(self.workdir, ignore_errors=True)

        return result_rec


def _headline(assertions: List[Assertion], error: Optional[str]) -> str:
    if error:
        return f"error: {error[:120]}"
    failed = [a for a in assertions if not a.passed]
    if failed:
        return f"{len(failed)} assertion(s) failed: " + "; ".join(
            f"{a.name}: {a.detail[:60]}" for a in failed[:3]
        )
    return "all assertions passed"


# ---------------------------------------------------------------------------
# Agent availability
# ---------------------------------------------------------------------------


def binary_available(agent_id: str) -> bool:
    try:
        validate_binary(get_registration(agent_id))
        return True
    except AgentBinaryNotFoundError:
        return False
