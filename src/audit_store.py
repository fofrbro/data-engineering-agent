import json
from pathlib import Path


DEFAULT_AUDIT_PATH = Path("data/audit/pipeline_runs.jsonl")


def append_audit(
    audit: dict,
    output_path: str | Path = DEFAULT_AUDIT_PATH,
) -> Path:
    """
    Ajoute un enregistrement d'audit à un fichier JSONL.

    Chaque audit occupe exactement une ligne.
    """

    path = Path(output_path)

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as file:
        json.dump(
            audit,
            file,
            ensure_ascii=False,
        )
        file.write("\n")

    return path


def read_audits(
    input_path: str | Path = DEFAULT_AUDIT_PATH,
) -> list[dict]:
    """
    Lit tous les enregistrements d'un fichier JSONL.
    """

    path = Path(input_path)

    if not path.exists():
        return []

    audits = []

    with path.open(
        "r",
        encoding="utf-8",
    ) as file:
        for line in file:
            line = line.strip()

            if not line:
                continue

            audits.append(
                json.loads(line)
            )

    return audits
