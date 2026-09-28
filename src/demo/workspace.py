"""
Espaces de travail : dossiers, lots uploadés et service du workflow.

Hors démo, un seul espace (le vôtre) utilise les dossiers du projet.
En démo publique, chaque visiteur reçoit un espace isolé et temporaire :
ses plans, contrats, données et audits ne sont visibles que de lui, et
l'espace est effacé après une période d'inactivité.
"""

import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from src.demo.quota import DailyQuota, LimitedLLMClient
from src.workflow.workflow_service import WorkflowService


VISITOR_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class DemoFull(Exception):
    """Nombre maximal de visiteurs simultanés atteint."""


@dataclass
class Workspace:
    upload_dir: Path
    archive_dir: Path
    service: WorkflowService
    llm_client: object | None
    # Lots uploadés, en mémoire.
    sessions: dict = field(default_factory=dict)
    visitor_id: str | None = None
    quota: DailyQuota | None = None
    last_seen: float = field(default_factory=time.monotonic)

    @property
    def is_empty(self) -> bool:
        """Ni fichier chargé ni plan : rien à perdre si l'espace est libéré."""

        return not self.sessions and not self.service.plan_count

    def consume(self, action: str) -> None:
        """Compte une action coûteuse ; lève QuotaExceeded au-delà de la limite."""

        if self.quota is not None:
            self.quota.consume(self.visitor_id, action)


def new_visitor_id() -> str:
    return uuid4().hex


def is_visitor_id(value: str | None) -> bool:
    """Identifiant sûr : il sert de nom de dossier, rien d'autre n'est accepté."""

    return bool(value) and bool(VISITOR_PATTERN.match(value))


class VisitorRegistry:
    """Espaces des visiteurs de la démo, effacés après ttl_seconds d'inactivité."""

    def __init__(
        self,
        root: str | Path,
        quota: DailyQuota,
        llm_client=None,
        ttl_seconds: int = 7200,
        max_visitors: int = 50,
        clock=time.monotonic,
    ):
        self.root = Path(root)
        self.quota = quota
        self.llm_client = llm_client
        self.ttl_seconds = ttl_seconds
        self.max_visitors = max_visitors
        self._clock = clock
        self._workspaces: dict[str, Workspace] = {}
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        # Espaces laissés par une exécution précédente du serveur. Seuls
        # les dossiers nommés comme un visiteur sont effacés : une racine
        # mal configurée (DEMO_ROOT=data) ne perd rien d'autre.
        for leftover in self.root.iterdir():
            if leftover.is_dir() and is_visitor_id(leftover.name):
                shutil.rmtree(leftover, ignore_errors=True)

    def get(self, visitor_id: str) -> Workspace:
        if not is_visitor_id(visitor_id):
            raise ValueError("Identifiant de visiteur invalide.")

        with self._lock:
            self._expire()
            workspace = self._workspaces.get(visitor_id)

            if workspace is None:
                if len(self._workspaces) >= self.max_visitors:
                    self._evict_oldest_empty()

                if len(self._workspaces) >= self.max_visitors:
                    raise DemoFull("La démo est très demandée : réessayez dans quelques minutes.")

                workspace = self._create(visitor_id)
                self._workspaces[visitor_id] = workspace

            workspace.last_seen = self._clock()
            return workspace

    def _create(self, visitor_id: str) -> Workspace:
        root = self.root / visitor_id

        for folder in ("uploads", "archive", "contracts"):
            (root / folder).mkdir(parents=True, exist_ok=True)

        llm = (
            LimitedLLMClient(self.llm_client, self.quota, visitor_id)
            if self.llm_client is not None
            else None
        )

        return Workspace(
            upload_dir=root / "uploads",
            archive_dir=root / "archive",
            service=WorkflowService(
                contracts_dir=root / "contracts",
                output_root=root / "lake",
                audit_path=root / "audit" / "pipeline_runs.jsonl",
                fabric_export_root=root / "fabric_export",
                results_dir=root / "results",
                llm_client=llm,
            ),
            llm_client=llm,
            visitor_id=visitor_id,
            quota=self.quota,
            last_seen=self._clock(),
        )

    def _evict_oldest_empty(self) -> None:
        """
        Libère l'espace vide le moins récemment utilisé : des requêtes sans
        cookie (robots, curl) ne peuvent pas occuper toutes les places.
        """

        empty = [w for w in self._workspaces.values() if w.is_empty]

        if empty:
            oldest = min(empty, key=lambda w: w.last_seen)
            del self._workspaces[oldest.visitor_id]
            shutil.rmtree(self.root / oldest.visitor_id, ignore_errors=True)

    def _expire(self) -> None:
        now = self._clock()

        for visitor_id, workspace in list(self._workspaces.items()):
            if now - workspace.last_seen > self.ttl_seconds:
                del self._workspaces[visitor_id]
                shutil.rmtree(self.root / visitor_id, ignore_errors=True)

    @property
    def active(self) -> int:
        return len(self._workspaces)
