from dataclasses import dataclass
from pathlib import Path

from src.discovery.file_detector import FileInfo
from src.discovery.format_detector import FormatInfo
from src.discovery.readers import read_dataset
from src.discovery.schema_profiler import SchemaProfile, profile_schema


@dataclass
class DiscoveryResult:
    file: FileInfo
    format: FormatInfo
    schema: SchemaProfile

    def to_dict(self) -> dict:
        return {
            "file": self.file.to_dict(),
            "format": self.format.to_dict(),
            "schema": self.schema.to_dict(),
        }


def discover_dataset(path: str | Path) -> DiscoveryResult:
    """
    Point d'entrée de la découverte :
    fichier → format → lecture → profil de schéma.
    """

    file_info, format_info, frame = read_dataset(path)

    return DiscoveryResult(
        file=file_info,
        format=format_info,
        schema=profile_schema(frame),
    )
