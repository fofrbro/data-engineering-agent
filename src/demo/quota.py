"""
Quotas journaliers de la démo publique.

Chaque action coûteuse (plan, exécution, appel LLM) est comptée par
visiteur et au total, par jour UTC. Au-delà, QuotaExceeded est levée :
l'API répond 429, et un appel LLM refusé rend la fonction LLM
indisponible sans bloquer le reste du workflow.
"""

from collections import Counter
from datetime import datetime, timezone
from typing import Callable


PLAN = "plan"
EXECUTION = "execution"
LLM_CALL = "llm_call"

LABELS = {
    PLAN: "préparations de plan",
    EXECUTION: "exécutions",
    LLM_CALL: "appels au LLM",
}


class QuotaExceeded(Exception):
    """Limite d'usage de la démo atteinte."""


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


class DailyQuota:
    def __init__(
        self,
        per_visitor: dict[str, int],
        overall: dict[str, int] | None = None,
        today: Callable[[], str] = _today,
    ):
        self.per_visitor = per_visitor
        self.overall = overall or {}
        self._today = today
        self._day = today()
        self._counts: Counter = Counter()

    def _roll(self) -> None:
        day = self._today()

        if day != self._day:
            self._day, self._counts = day, Counter()

    def consume(self, visitor: str, action: str) -> None:
        """Compte une action, ou lève QuotaExceeded sans la compter."""

        self._roll()
        own = self._counts[(visitor, action)]
        total = self._counts[("*", action)]
        label = LABELS.get(action, action)

        if action in self.per_visitor and own >= self.per_visitor[action]:
            raise QuotaExceeded(
                f"Limite de la démo atteinte : {self.per_visitor[action]} {label} par jour."
            )

        if action in self.overall and total >= self.overall[action]:
            raise QuotaExceeded(
                f"Limite quotidienne de la démo atteinte pour les {label} : réessayez demain."
            )

        self._counts[(visitor, action)] += 1
        self._counts[("*", action)] += 1

    def remaining(self, visitor: str) -> dict[str, int]:
        self._roll()

        return {
            action: max(0, limit - self._counts[(visitor, action)])
            for action, limit in self.per_visitor.items()
        }


class LimitedLLMClient:
    """
    Enveloppe du client OpenAI : chaque appel consomme le quota du
    visiteur. Un appel refusé lève QuotaExceeded, que les fonctions LLM
    traitent comme une indisponibilité.
    """

    def __init__(self, client, quota: DailyQuota, visitor: str):
        self._client = client
        self._quota = quota
        self._visitor = visitor
        self.responses = self

    def create(self, **kwargs):
        self._quota.consume(self._visitor, LLM_CALL)
        return self._client.responses.create(**kwargs)
