"""
Regroupement d'un lot de fichiers en datasets.

- Avec un nom de dataset fourni, tous les fichiers sont considérés
  comme le même dataset (l'utilisateur l'affirme) : un seul groupe.
- Sans nom, les fichiers qui ont exactement les mêmes colonnes (quel
  que soit leur ordre) forment un même dataset ; un fichier au schéma
  différent forme son propre groupe.

L'ordre des groupes et des fichiers suit l'ordre d'envoi.
"""

from dataclasses import dataclass, field

from src.discovery.readers import read_dataframe


@dataclass
class FileGroup:
    files: list[str]
    dataset: str | None = None
    columns: list[str] = field(default_factory=list)


def group_files(file_paths: list[str], dataset: str | None = None) -> list[FileGroup]:
    if not file_paths:
        raise ValueError("Aucun fichier à regrouper.")

    if dataset:
        return [
            FileGroup(
                files=list(file_paths),
                dataset=dataset,
                columns=list(read_dataframe(file_paths[0]).columns),
            )
        ]

    groups: dict[frozenset, FileGroup] = {}

    for path in file_paths:
        columns = list(read_dataframe(path).columns)
        key = frozenset(columns)

        if key not in groups:
            groups[key] = FileGroup(files=[], columns=columns)

        groups[key].files.append(path)

    return list(groups.values())
