"""
Extraction des fichiers de données d'une archive ZIP uploadée.

Protections :
- seuls les fichiers aux extensions prises en charge sont extraits
  (pas d'archive imbriquée) ; dossiers, fichiers cachés et __MACOSX
  sont ignorés ;
- aucun chemin de l'archive n'est utilisé sur le disque : chaque fichier
  est renvoyé en mémoire avec un nom à plat (« 2019/ventes.csv » ->
  « 2019_ventes.csv »), ce qui écarte les chemins piégés (« ../ ») ;
- nombre de fichiers et taille décompressée limités, en comptant les
  octets réellement lus (la taille annoncée par l'archive peut mentir) ;
- archive chiffrée ou illisible refusée.
"""

import io
import zipfile
from pathlib import PurePosixPath


MAX_MEMBERS = 200
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_MEMBER_BYTES = 100 * 1024 * 1024
CHUNK = 1024 * 1024


class ArchiveError(ValueError):
    """Archive refusée."""


def _flat_name(member: str) -> str:
    parts = [part for part in PurePosixPath(member.replace("\\", "/")).parts if part not in ("", ".", "..", "/")]
    return "_".join(parts)


def _ignored(member: str) -> bool:
    parts = PurePosixPath(member.replace("\\", "/")).parts
    return any(
        (part.startswith(".") and part not in (".", "..")) or part == "__MACOSX"
        for part in parts
    )


def _read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, budget: int) -> bytes:
    """Lit un fichier sans dépasser les limites, quoi qu'annonce l'archive."""

    limit = min(MAX_MEMBER_BYTES, budget)
    data = bytearray()

    with archive.open(info) as source:
        while chunk := source.read(CHUNK):
            data += chunk

            if len(data) > limit:
                raise ArchiveError(
                    f"{info.filename} dépasse la taille autorisée une fois décompressé."
                )

    return bytes(data)


def extract_data_files(
    contents: bytes,
    supported_extensions: set[str],
) -> list[tuple[str, bytes]]:
    """(nom à plat, contenu) de chaque fichier de données de l'archive."""

    try:
        archive = zipfile.ZipFile(io.BytesIO(contents))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("Archive ZIP illisible.") from exc

    with archive:
        members = [
            info
            for info in archive.infolist()
            if not info.is_dir()
            and not _ignored(info.filename)
            and PurePosixPath(info.filename).suffix.lower() in supported_extensions
        ]

        if not members:
            raise ArchiveError("L'archive ne contient aucun fichier de données pris en charge.")

        if len(members) > MAX_MEMBERS:
            raise ArchiveError(f"L'archive contient plus de {MAX_MEMBERS} fichiers.")

        if any(info.flag_bits & 0x1 for info in members):
            raise ArchiveError("Les archives chiffrées ne sont pas prises en charge.")

        extracted, names, total = [], set(), 0

        for info in members:
            name = _flat_name(info.filename)

            if name in names:
                raise ArchiveError(f"Deux fichiers portent le même nom : {name}")

            data = _read(archive, info, MAX_TOTAL_BYTES - total)
            total += len(data)
            names.add(name)
            extracted.append((name, data))

    return extracted
