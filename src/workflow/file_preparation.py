"""
Préparation d'un lot avant le plan : fichiers délimités sans en-tête.

Un fichier sans en-tête reçoit des noms de colonnes, puis une copie avec
en-tête est écrite à côté de lui : toute la suite du workflow (profil,
contrat, contrôles, Bronze/Silver/Gold) lit cette copie sans changement.
Les fichiers sans en-tête de même structure reçoivent les mêmes noms :
ils forment donc un seul dataset, avec un seul contrat.

Origine des noms, par ordre de priorité :
1. CONTRACT : un seul contrat VALIDATED a la même structure (nombre de
   colonnes et types compatibles, dans l'ordre) ; ses noms et son dataset
   sont repris, le contrat sera réutilisé ;
2. LLM : noms proposés par le LLM et vérifiés par le code ; ils figurent
   dans le contrat PROPOSED, que le relecteur valide ;
3. GENERIC : column_1, column_2… si ni l'un ni l'autre n'est possible.

Le texte des cellules est recopié tel quel : aucune valeur n'est
convertie par la préparation.
"""

from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from src.contract.contract_lifecycle import VALIDATED, contract_status, load_contract_file
from src.discovery.header_detection import has_header, read_raw_delimited
from src.discovery.schema_profiler import (
    BOOLEAN,
    DATETIME,
    DECIMAL,
    EMPTY,
    INTEGER,
    STRING,
    SchemaProfile,
    profile_schema,
)
from src.semantic.column_naming import propose_column_names


# Origine des noms de colonnes.
FROM_FILE = "FILE"
FROM_CONTRACT = "CONTRACT"
FROM_LLM = "LLM"
GENERIC = "GENERIC"

PREPARED_SUFFIX = "_avec_entete"

# Types comparés entre fichiers et contrats : entier et décimal se
# confondent (une colonne décimale peut n'avoir que des valeurs rondes).
_COARSE = {
    INTEGER: "number",
    DECIMAL: "number",
    DATETIME: "datetime",
    STRING: "string",
    BOOLEAN: "boolean",
    EMPTY: None,
    "integer": "number",
    "decimal": "number",
    "datetime": "datetime",
    "string": "string",
    "boolean": "boolean",
}


@dataclass
class PreparedFile:
    original: str
    path: str
    header_source: str
    dataset: str | None = None
    note: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _signature(types: list[str | None]) -> tuple:
    return tuple(_COARSE.get(t) for t in types)


def _compatible(left: tuple, right: tuple) -> bool:
    """Même nombre de colonnes ; une colonne vide est compatible avec tout."""

    return len(left) == len(right) and all(
        a is None or b is None or a == b for a, b in zip(left, right)
    )


def _typed_profile(raw: pd.DataFrame) -> SchemaProfile:
    """Profil de types d'un fichier sans en-tête (lu en texte)."""

    frame = raw.replace("", None).apply(_numeric_or_text)
    frame.columns = [f"column_{i}" for i in range(1, len(frame.columns) + 1)]

    return profile_schema(frame)


def _numeric_or_text(column: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(column, errors="coerce")

    return numbers if numbers.notna().sum() == column.notna().sum() else column


def validated_contracts(contracts_dir: str | Path) -> list[dict]:
    root = Path(contracts_dir)

    if not root.is_dir():
        return []

    contracts = []

    for path in sorted(root.glob("*.json")):
        try:
            _, contract = load_contract_file(path, root)
        except (OSError, ValueError):
            continue

        if contract.get("columns") and contract_status(contract) == VALIDATED:
            contracts.append(contract)

    return contracts


def matching_contract(signature: tuple, contracts: list[dict]) -> dict | None:
    """Le contrat validé de même structure, s'il est le seul."""

    matches = [
        contract
        for contract in contracts
        if _compatible(
            signature,
            _signature([rule.get("type") for rule in contract["columns"].values()]),
        )
    ]

    return matches[0] if len(matches) == 1 else None


def _prepared_path(path: str) -> Path:
    source = Path(path)
    return source.with_name(f"{source.stem}{PREPARED_SUFFIX}.csv")


def prepare_files(
    file_paths: list[str],
    contracts_dir: str | Path,
    llm_client=None,
) -> list[PreparedFile]:
    """Un PreparedFile par fichier, dans l'ordre reçu."""

    prepared: dict[str, PreparedFile] = {}
    # Fichiers sans en-tête regroupés par structure compatible.
    groups: list[dict] = []

    for path in file_paths:
        raw = read_raw_delimited(path)

        if raw is None or has_header(raw):
            prepared[path] = PreparedFile(original=path, path=path, header_source=FROM_FILE)
            continue

        profile = _typed_profile(raw)
        signature = _signature([c.inferred_type for c in profile.columns])
        group = next((g for g in groups if _compatible(g["signature"], signature)), None)

        if group is None:
            group = {"signature": signature, "files": [], "frames": []}
            groups.append(group)

        group["files"].append(path)
        group["frames"].append(raw)

    contracts = validated_contracts(contracts_dir)

    for group in groups:
        names, dataset, source, note = _name_group(group, contracts, llm_client)

        for path, raw in zip(group["files"], group["frames"]):
            destination = _prepared_path(path)
            raw.set_axis(names, axis=1).to_csv(destination, index=False, encoding="utf-8")
            prepared[path] = PreparedFile(
                original=path,
                path=destination.as_posix(),
                header_source=source,
                dataset=dataset,
                note=note,
            )

    return [prepared[path] for path in file_paths]


def _name_group(group: dict, contracts: list[dict], llm_client):
    contract = matching_contract(group["signature"], contracts)

    if contract:
        return (
            list(contract["columns"]),
            contract.get("dataset"),
            FROM_CONTRACT,
            f"noms du contrat validé {contract.get('dataset')}",
        )

    # Le LLM voit le lot entier, pour des noms communs à tous ses fichiers.
    profile = _typed_profile(pd.concat(group["frames"], ignore_index=True))
    naming, reason = propose_column_names(llm_client, profile)

    if naming:
        return naming.names, naming.dataset, FROM_LLM, "noms proposés par le LLM, à valider avec le contrat"

    count = len(group["signature"])

    return (
        [f"column_{i}" for i in range(1, count + 1)],
        None,
        GENERIC,
        f"noms génériques ({reason})",
    )
