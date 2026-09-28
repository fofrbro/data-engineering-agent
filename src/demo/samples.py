"""Fichiers d'exemple proposés dans la démo publique (aucun upload libre)."""

from dataclasses import asdict, dataclass
from pathlib import Path


SAMPLES_DIR = Path("data/samples")


@dataclass(frozen=True)
class Sample:
    key: str
    file: str
    title: str
    description: str

    @property
    def path(self) -> Path:
        return SAMPLES_DIR / self.file

    def to_dict(self) -> dict:
        return asdict(self)


SAMPLES = [
    Sample(
        "ventes",
        "ventes_2025_2026.csv",
        "Ventes 2025-2026",
        "1 500 commandes fictives : contrat, commandes annulées exclues des KPI, décision INGEST.",
    ),
    Sample(
        "quarantaine",
        "ventes_quarantaine.csv",
        "Ventes à mettre en quarantaine",
        "Colonne en partie vide : l'agent isole le fichier (QUARANTINE).",
    ),
    Sample(
        "rejet",
        "ventes_rejet.csv",
        "Ventes à rejeter",
        "Quantités négatives : le fichier viole son contrat (REJECT).",
    ),
    Sample(
        "adventure_works",
        "sales.csv",
        "Adventure Works (Microsoft)",
        "32 718 lignes sans colonne de montant : chiffre d'affaires dérivé, taxe reconnue.",
    ),
    Sample(
        "orders_zip",
        "orders.zip",
        "Export découpé sans en-tête (ZIP)",
        "Trois fichiers annuels sans en-tête : noms de colonnes proposés puis validés.",
    ),
    Sample(
        "rh",
        "rh_employes.csv",
        "Employés (RH)",
        "600 employés fictifs : données hors vente, moyennes par service.",
    ),
]

SAMPLES_BY_KEY = {sample.key: sample for sample in SAMPLES}
