"""
Commentaire de l'analyse rédigé par un LLM.

Le LLM ne reçoit que les agrégats de l'analyse (jamais de lignes) ; les
libellés de clients et toute valeur contenant « @ » sont remplacés par
« Client 1 », « Client 2 »… Il rédige une synthèse en français.

Le code vérifie ensuite chaque nombre cité : il doit correspondre, à
l'arrondi près, à un chiffre de l'analyse (une part ou un taux peut être
cité en pourcentage ; « 20,9 M » vaut 20 900 000). Les nombres introuvables
sont listés comme non vérifiés et affichés comme tels. Années, mois et
petits entiers (« top 5 ») ne sont pas vérifiés.
"""

import copy
import json
import re
from dataclasses import asdict, dataclass, field

from src.semantic.vocabulary import CUSTOMER


MODEL = "gpt-5.6"

COMPLETED = "COMPLETED"
UNAVAILABLE = "UNAVAILABLE"

# Écart relatif toléré entre un nombre cité (arrondi) et le chiffre exact.
TOLERANCE = 0.015

COMMENTARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "points": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "points"],
    "additionalProperties": False,
}

COMMENTARY_INSTRUCTIONS = """
Tu es analyste de données. Tu reçois l'analyse chiffrée d'un jeu de données,
calculée par un programme. Rédige en français, pour un responsable métier :
- summary : une synthèse de 3 à 5 phrases ;
- points : 3 à 6 constats ou points d'attention, une phrase chacun.

Règles :
1. N'utilise que les chiffres fournis ; n'en calcule pas de nouveaux, sauf
   pour exprimer une part ou un taux fourni en pourcentage.
2. Arrondis lisiblement (1 668 735,18 -> « 1,67 M ») ; cite les mois et
   années tels quels.
3. Signale les limites (mois incomplets, lignes exclues) si elles existent.
4. Pas de recommandation qui ne découle pas directement des chiffres.
"""


@dataclass
class Commentary:
    status: str
    summary: str | None = None
    points: list[str] = field(default_factory=list)
    unverified_numbers: list[str] = field(default_factory=list)
    error: str | None = None
    model: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def anonymized_payload(analysis: dict) -> dict:
    """Agrégats envoyés au LLM, sans libellé de client ni e-mail."""

    payload = copy.deepcopy(analysis)
    payload.pop("commentary", None)

    for breakdown in payload.get("breakdowns", []):
        personal = breakdown.get("entity") == CUSTOMER or any(
            "@" in item["value"] for item in breakdown["top"]
        )

        if personal:
            for index, item in enumerate(breakdown["top"], start=1):
                item["value"] = f"Client {index}"

    return payload


def _known_numbers(value, found: list[float]) -> list[float]:
    if isinstance(value, bool):
        return found

    if isinstance(value, (int, float)):
        found.append(float(value))
        # Une part ou un taux (0,678) peut être cité en pourcentage (67,8 %).
        if -10 <= value <= 10:
            found.append(float(value) * 100)
    elif isinstance(value, dict):
        for item in value.values():
            _known_numbers(item, found)
    elif isinstance(value, list):
        for item in value:
            _known_numbers(item, found)

    return found


NUMBER = re.compile(
    r"(?<![\w.,])(\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,](\d+))?"
    r"(\s*(?:%|Md\b|M\b|k\b|milliards?|millions?|milliers?))?",
    re.IGNORECASE,
)
MULTIPLIERS = {
    "md": 1e9, "milliard": 1e9, "milliards": 1e9,
    "m": 1e6, "million": 1e6, "millions": 1e6,
    "k": 1e3, "millier": 1e3, "milliers": 1e3,
}


def cited_numbers(text: str) -> list[tuple[str, float, float]]:
    """
    (texte, valeur, précision) de chaque nombre cité, hors années et
    petits entiers. La précision est la demi-unité du dernier chiffre
    cité : « 1,67 M » vaut 1 670 000 à 5 000 près.
    """

    cited = []

    for match in NUMBER.finditer(text):
        whole, decimals, unit = match.group(1), match.group(2) or "", (match.group(3) or "").strip()
        multiplier = MULTIPLIERS.get(unit.lower(), 1.0)
        value = float(re.sub(r"[ \u00a0\u202f]", "", whole) + (f".{decimals}" if decimals else ""))

        if not decimals and not unit and (1900 <= value <= 2100 or value <= 31):
            continue

        precision = 0.5 * 10 ** -len(decimals) * multiplier
        cited.append((match.group(0).strip(), value * multiplier, precision))

    return cited


def unverified_numbers(text: str, analysis: dict) -> list[str]:
    """Nombres cités qu'aucun chiffre de l'analyse n'explique."""

    known = _known_numbers(analysis, [])

    return [
        label
        for label, value, precision in cited_numbers(text)
        if not any(
            abs(number - value) <= max(abs(number) * TOLERANCE, precision)
            for number in known
        )
    ]


def comment_analysis(client, analysis: dict, model: str = MODEL) -> Commentary:
    if client is None:
        return Commentary(status=UNAVAILABLE, error="aucun client LLM configuré")

    payload = anonymized_payload(analysis)

    try:
        response = client.responses.create(
            model=model,
            instructions=COMMENTARY_INSTRUCTIONS,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            text={
                "format": {
                    "type": "json_schema",
                    "name": "analysis_commentary",
                    "schema": COMMENTARY_SCHEMA,
                    "strict": True,
                }
            },
        )
        result = json.loads(response.output_text)
    except Exception as exc:
        error = (
            "clé API refusée (absente, invalide ou expirée)"
            if type(exc).__name__ == "AuthenticationError"
            else f"LLM indisponible : {type(exc).__name__}"
        )
        return Commentary(status=UNAVAILABLE, error=error)

    text = " ".join([result["summary"], *result["points"]])

    return Commentary(
        status=COMPLETED,
        summary=result["summary"],
        points=result["points"],
        unverified_numbers=unverified_numbers(text, payload),
        model=model,
    )
