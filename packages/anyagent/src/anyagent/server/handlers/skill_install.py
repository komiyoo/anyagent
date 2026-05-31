from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from anyagent.agent_packs import ANYAGENT_CONFIG_DIR, ANYAGENT_SKILLS_SUBDIR, AgentPack
from anyagent.protocol.agent_api_internal import (
    AdminSkillImportRequest,
    AdminSkillRegistryInstallRequest,
    AdminSkillUpdateCheckResponse,
)
from anyagent.skills.loader import SkillLoadError, load_skill_package
from anyagent.server.handlers.agent_views import _text_preview


_SKILL_DIRECTORY_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")
_SKILL_INSTALL_PACKAGE_RE = re.compile(r"^[A-Za-z0-9_.:/@-]{1,256}$")
_SKILL_INSTALL_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_GITHUB_REPO_RE = re.compile(r"^(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
_GITHUB_REF_RE = re.compile(r"^[A-Za-z0-9_./@+-]{1,128}$")
_GITHUB_PATH_RE = re.compile(r"^[A-Za-z0-9_./@+-]{1,256}$")


def _resolve_agent_skill_dir(pack: AgentPack, directory_name: str) -> Path:
    directory_name = directory_name.strip()
    if not _SKILL_DIRECTORY_RE.fullmatch(directory_name):
        raise HTTPException(status_code=400, detail="invalid skill directory_name")
    skill_dir = (pack.skills_dir / directory_name).resolve()
    root = pack.skills_dir.resolve()
    if root != skill_dir and root not in skill_dir.parents:
        raise HTTPException(status_code=400, detail="skill directory escapes agent skills root")
    return skill_dir


def _copy_skill_dir_into_agent(
    *,
    pack: AgentPack,
    source_dir: Path,
    directory_name: str,
    overwrite: bool,
    source_metadata: dict[str, Any] | None = None,
):
    skill_dir = _resolve_agent_skill_dir(pack, directory_name)
    skill_md_path = skill_dir / "SKILL.md"
    if skill_dir.exists() and not overwrite:
        raise HTTPException(status_code=409, detail="skill already exists; set overwrite=true to replace")
    previous_dir = None
    if skill_dir.exists():
        previous_dir = Path(tempfile.mkdtemp(prefix="anyagent-skill-backup-")) / skill_dir.name
        shutil.copytree(skill_dir, previous_dir)
        shutil.rmtree(skill_dir)
    skill_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_dir, skill_dir)
    try:
        skill = load_skill_package(skill_dir, scope="agent")
        if source_metadata is not None:
            metadata = {
                **source_metadata,
                "installed_at": datetime.now(timezone.utc).isoformat(),
                "source_hash": hashlib.sha256((skill_dir / "SKILL.md").read_bytes()).hexdigest(),
            }
            (skill_dir / ".anyagent-skill-source.json").write_text(
                json.dumps(metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return skill
    except SkillLoadError as e:
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        if previous_dir is not None:
            shutil.copytree(previous_dir, skill_dir)
        raise HTTPException(status_code=400, detail=f"invalid skill: {e}") from e


def _import_agent_local_skill(*, pack: AgentPack, request: AdminSkillImportRequest):
    raw = request.skill_md.encode("utf-8")
    if len(raw) > 256 * 1024:
        raise HTTPException(status_code=413, detail=f"skill too large: bytes={len(raw)} max={256 * 1024}")
    directory_name = request.directory_name.strip()
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-import-") as tmp:
        source_dir = Path(tmp) / directory_name
        source_dir.mkdir(parents=True)
        (source_dir / "SKILL.md").write_text(request.skill_md, encoding="utf-8")
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=source_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": "local_upload",
                "source_ref": directory_name,
                "skill": directory_name,
            },
        )


def _read_skill_source_metadata(skill_dir: Path) -> dict[str, Any]:
    metadata_path = skill_dir / ".anyagent-skill-source.json"
    if not metadata_path.is_file():
        return {}
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _install_request_from_skill_source_metadata(metadata: dict[str, Any], *, overwrite: bool) -> AdminSkillRegistryInstallRequest | None:
    channel = metadata.get("channel")
    if channel not in {"skills.sh", "registry", "github"}:
        return None
    skill = metadata.get("skill")
    if not isinstance(skill, str) or not skill.strip():
        return None
    package = metadata.get("package")
    if not isinstance(package, str) or not package.strip():
        package = metadata.get("github_repo") if channel == "github" else None
    if not isinstance(package, str) or not package.strip():
        return None
    return AdminSkillRegistryInstallRequest(
        channel=channel,
        package=package,
        skill=skill,
        directory_name=None,
        github_repo=metadata.get("github_repo") if isinstance(metadata.get("github_repo"), str) else None,
        github_ref=metadata.get("github_ref") if isinstance(metadata.get("github_ref"), str) else None,
        github_path=metadata.get("github_path") if isinstance(metadata.get("github_path"), str) else None,
        overwrite=overwrite,
    )


def _check_agent_local_skill_update(*, pack: AgentPack, directory_name: str) -> AdminSkillUpdateCheckResponse:
    skill_dir = _resolve_agent_skill_dir(pack, directory_name)
    if not (skill_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="skill not found")
    metadata = _read_skill_source_metadata(skill_dir)
    current_hash = hashlib.sha256((skill_dir / "SKILL.md").read_bytes()).hexdigest()
    install_req = _install_request_from_skill_source_metadata(metadata, overwrite=True)
    if install_req is None:
        return AdminSkillUpdateCheckResponse(
            agent_id=pack.agent_id,
            directory_name=directory_name,
            channel=str(metadata.get("channel")) if isinstance(metadata.get("channel"), str) else None,
            source_ref=str(metadata.get("source_ref")) if isinstance(metadata.get("source_ref"), str) else None,
            current_hash=current_hash,
            updatable=False,
            reason="skill has no updatable channel source metadata",
        )
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-check-") as tmp:
        temp_pack = AgentPack(
            agent_id=pack.agent_id,
            root_dir=Path(tmp),
            spec=pack.spec,
            agents_md_path=pack.agents_md_path,
            agents_md_text=pack.agents_md_text,
            agents_md_sha256=pack.agents_md_sha256,
            workspace_agents_md_path=pack.workspace_agents_md_path,
            workspace_agents_md_text=pack.workspace_agents_md_text,
            workspace_agents_md_sha256=pack.workspace_agents_md_sha256,
            mcp_config=pack.mcp_config,
        )
        latest = _install_agent_local_skill_from_registry(pack=temp_pack, request=install_req)
        latest_hash = hashlib.sha256(latest.skill_md_path.read_bytes()).hexdigest()
    return AdminSkillUpdateCheckResponse(
        agent_id=pack.agent_id,
        directory_name=directory_name,
        channel=install_req.channel,
        source_ref=str(metadata.get("source_ref")) if isinstance(metadata.get("source_ref"), str) else None,
        current_hash=current_hash,
        latest_hash=latest_hash,
        update_available=current_hash != latest_hash,
        updatable=True,
    )


def _github_repo_url(repo: str) -> tuple[str, str]:
    match = _GITHUB_REPO_RE.fullmatch(repo.strip())
    if not match:
        raise HTTPException(status_code=400, detail="invalid github_repo")
    owner, name = match.groups()
    return f"https://github.com/{owner}/{name}.git", f"{owner}/{name}"


def _resolve_github_skill_source(repo_root: Path, github_path: str | None, skill_name: str) -> Path:
    raw_path = (github_path or skill_name).strip()
    if not _GITHUB_PATH_RE.fullmatch(raw_path) or raw_path.startswith("/") or ".." in Path(raw_path).parts:
        raise HTTPException(status_code=400, detail="invalid github_path")
    candidate = (repo_root / raw_path).resolve()
    root = repo_root.resolve()
    if root != candidate and root not in candidate.parents:
        raise HTTPException(status_code=400, detail="github_path escapes repository")
    if candidate.is_file() and candidate.name == "SKILL.md":
        candidate = candidate.parent
    if not (candidate / "SKILL.md").is_file():
        raise HTTPException(status_code=400, detail="github_path must point to a skill directory or SKILL.md")
    return candidate


def _install_agent_local_skill_from_github(*, pack: AgentPack, request: AdminSkillRegistryInstallRequest):
    repo = request.github_repo or request.package
    repo_url, repo_ref = _github_repo_url(repo)
    skill_name = request.skill.strip()
    directory_name = (request.directory_name or skill_name).strip()
    ref = (request.github_ref or "main").strip()
    if not _SKILL_INSTALL_NAME_RE.fullmatch(skill_name):
        raise HTTPException(status_code=400, detail="invalid skill")
    if not _GITHUB_REF_RE.fullmatch(ref):
        raise HTTPException(status_code=400, detail="invalid github_ref")
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skill-github-") as tmp:
        repo_dir = Path(tmp) / "repo"
        result = subprocess.run(
            ["git", "clone", "--depth", "1", "--branch", ref, repo_url, str(repo_dir)],
            cwd=tmp,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"github skill clone failed: {_text_preview(result.stdout, limit=800)}")
        source_dir = _resolve_github_skill_source(repo_dir, request.github_path, skill_name)
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=source_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": "github",
                "package": repo_ref,
                "skill": skill_name,
                "source_ref": f"github:{repo_ref}:{ref}:{request.github_path or skill_name}",
                "github_repo": repo_ref,
                "github_ref": ref,
                "github_path": request.github_path or skill_name,
            },
        )


def _install_agent_local_skill_from_registry(*, pack: AgentPack, request: AdminSkillRegistryInstallRequest):
    if request.channel == "github":
        return _install_agent_local_skill_from_github(pack=pack, request=request)
    package = request.package.strip()
    skill_name = request.skill.strip()
    directory_name = (request.directory_name or skill_name).strip()
    if not _SKILL_INSTALL_PACKAGE_RE.fullmatch(package):
        raise HTTPException(status_code=400, detail="invalid package")
    if not _SKILL_INSTALL_NAME_RE.fullmatch(skill_name):
        raise HTTPException(status_code=400, detail="invalid skill")
    _resolve_agent_skill_dir(pack, directory_name)
    with tempfile.TemporaryDirectory(prefix="anyagent-skills-install-") as tmp:
        result = subprocess.run(
            [
                "npx",
                "--yes",
                "skills",
                "add",
                package,
                "--channel",
                request.channel,
                "--skill",
                skill_name,
                "--agent",
                "universal",
                "--copy",
                "-y",
            ],
            cwd=tmp,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"skills install failed: {_text_preview(result.stdout, limit=800)}")
        installed_dir = Path(tmp) / ANYAGENT_CONFIG_DIR / ANYAGENT_SKILLS_SUBDIR / skill_name
        if not installed_dir.is_dir():
            raise HTTPException(status_code=400, detail="skills install did not produce expected skill directory")
        return _copy_skill_dir_into_agent(
            pack=pack,
            source_dir=installed_dir,
            directory_name=directory_name,
            overwrite=request.overwrite,
            source_metadata={
                "channel": request.channel,
                "package": package,
                "skill": skill_name,
                "source_ref": f"{request.channel}:{package}:{skill_name}",
            },
        )
