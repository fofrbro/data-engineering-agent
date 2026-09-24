from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileInfo:
    """
    Informations physiques sur un fichier source.
    """

    path: str
    name: str
    extension: str
    size_bytes: int

    @property
    def is_empty(self) -> bool:
        return self.size_bytes == 0

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "is_empty": self.is_empty,
        }


def detect_file(path: str | Path) -> FileInfo:
    """
    Vérifie qu'un chemin désigne un fichier et
    retourne ses informations physiques.
    """

    source = Path(path)

    if not source.exists():
        raise FileNotFoundError(
            f"Fichier introuvable : {source}"
        )

    if not source.is_file():
        raise IsADirectoryError(
            f"Le chemin n'est pas un fichier : {source}"
        )

    return FileInfo(
        path=str(source),
        name=source.name,
        extension=source.suffix.lower(),
        size_bytes=source.stat().st_size,
    )
