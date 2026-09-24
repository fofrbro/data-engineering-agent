import csv
from dataclasses import asdict, dataclass
from pathlib import Path

from src.discovery.errors import (
    EmptyFileError,
    UnsupportedFormatError,
)
from src.discovery.file_detector import FileInfo


CSV = "csv"
TSV = "tsv"
EXCEL = "excel"
JSON = "json"
JSONL = "jsonl"
PARQUET = "parquet"

EXTENSION_FORMATS = {
    ".csv": CSV,
    ".tsv": TSV,
    ".xlsx": EXCEL,
    ".xls": EXCEL,
    ".json": JSON,
    ".jsonl": JSONL,
    ".ndjson": JSONL,
    ".parquet": PARQUET,
}

# Signatures binaires : elles priment sur l'extension,
# car elles sont concluantes.
PARQUET_MAGIC = b"PAR1"
ZIP_MAGIC = b"PK\x03\x04"
OLE2_MAGIC = b"\xd0\xcf\x11\xe0"

CANDIDATE_DELIMITERS = ",;\t|"
SAMPLE_SIZE = 64 * 1024


@dataclass(frozen=True)
class FormatInfo:
    """
    Format détecté d'un fichier.

    detected_by vaut "extension", "signature" ou "content".
    delimiter n'est renseigné que pour les formats délimités.
    """

    format: str
    detected_by: str
    delimiter: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _read_sample(path: str | Path) -> bytes:
    with open(path, "rb") as file:
        return file.read(SAMPLE_SIZE)


def _format_from_signature(sample: bytes) -> str | None:
    if sample.startswith(PARQUET_MAGIC):
        return PARQUET

    if sample.startswith(ZIP_MAGIC) or sample.startswith(OLE2_MAGIC):
        return EXCEL

    return None


def _decode(sample: bytes) -> str:
    return sample.decode("utf-8-sig", errors="replace")


def sniff_delimiter(
    text: str,
    default: str = ",",
) -> str:
    """
    Détecte le séparateur d'un texte délimité.
    """

    try:
        dialect = csv.Sniffer().sniff(
            text,
            delimiters=CANDIDATE_DELIMITERS,
        )
    except csv.Error:
        return default

    return dialect.delimiter


def _format_from_content(text: str) -> FormatInfo | None:
    stripped = text.lstrip()

    if not stripped:
        return None

    if stripped[0] in "{[":
        lines = [
            line
            for line in stripped.splitlines()
            if line.strip()
        ]

        if len(lines) > 1 and all(
            line.lstrip().startswith("{")
            for line in lines
        ):
            return FormatInfo(JSONL, "content")

        return FormatInfo(JSON, "content")

    try:
        dialect = csv.Sniffer().sniff(
            text,
            delimiters=CANDIDATE_DELIMITERS,
        )
    except csv.Error:
        return None

    detected = TSV if dialect.delimiter == "\t" else CSV

    return FormatInfo(
        detected,
        "content",
        dialect.delimiter,
    )


def detect_format(file_info: FileInfo) -> FormatInfo:
    """
    Détermine le format d'un fichier.

    Ordre de priorité :
    1. signature binaire (Parquet, Excel) ;
    2. extension connue ;
    3. analyse du contenu texte (JSON, JSONL, délimité).
    """

    if file_info.is_empty:
        raise EmptyFileError(
            f"Fichier vide : {file_info.path}"
        )

    sample = _read_sample(file_info.path)

    signature_format = _format_from_signature(sample)

    if signature_format:
        return FormatInfo(signature_format, "signature")

    extension_format = EXTENSION_FORMATS.get(
        file_info.extension
    )

    if extension_format in {PARQUET, EXCEL}:
        # Extension binaire sans signature correspondante.
        raise UnsupportedFormatError(
            f"Le contenu de {file_info.path} ne correspond "
            f"pas à l'extension {file_info.extension}."
        )

    if extension_format == CSV:
        return FormatInfo(
            CSV,
            "extension",
            sniff_delimiter(_decode(sample)),
        )

    if extension_format == TSV:
        return FormatInfo(TSV, "extension", "\t")

    if extension_format:
        return FormatInfo(extension_format, "extension")

    content_format = _format_from_content(_decode(sample))

    if content_format:
        return content_format

    raise UnsupportedFormatError(
        f"Format non pris en charge : {file_info.path}"
    )
