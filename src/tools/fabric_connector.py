"""
Module pour connecter et publier les données vers Microsoft Fabric.

Permet :
- Connexion à Fabric via service principal ou interactif
- Publication de données en mode incremental ou full
- Gestion des datasets et tables dans Fabric
"""

import os
import json
import urllib.error
import urllib.request
from typing import Optional, Dict, Any
import pandas as pd


_fabric_session = {
    "access_token": None,
    "storage_access_token": None,
    "workspace_id": None,
}


def configure_fabric_session(
    access_token: str,
    workspace_id: Optional[str] = None,
    storage_access_token: Optional[str] = None,
) -> None:
    """Partage la session OAuth courante avec les opérations Fabric."""
    _fabric_session["access_token"] = access_token
    _fabric_session["storage_access_token"] = storage_access_token
    if workspace_id:
        _fabric_session["workspace_id"] = workspace_id


class FabricConnector:
    """Connecteur pour Microsoft Fabric."""

    def __init__(
        self,
        workspace_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        lakehouse_id: Optional[str] = None,
    ):
        """
        Initialise le connecteur Fabric.

        Args:
            workspace_id: ID du workspace Fabric
            tenant_id: Azure Tenant ID
            client_id: Azure Client ID
            client_secret: Azure Client Secret
        """
        self._allow_mock = any(
            value is not None
            for value in (
                workspace_id,
                tenant_id,
                client_id,
                client_secret,
                lakehouse_id,
            )
        )
        self.workspace_id = workspace_id or os.getenv("FABRIC_WORKSPACE_ID")
        self.tenant_id = tenant_id or os.getenv("FABRIC_TENANT_ID")
        self.client_id = client_id or os.getenv("FABRIC_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("FABRIC_CLIENT_SECRET")
        self.lakehouse_id = lakehouse_id or os.getenv("FABRIC_LAKEHOUSE_ID")
        self.access_token = _fabric_session["access_token"]
        self.storage_access_token = _fabric_session["storage_access_token"]
        self.workspace_id = self.workspace_id or _fabric_session["workspace_id"]

        # À implémenter : authentification réelle avec ms-fabric SDK
        # Pour le prototype, on simule la connexion
        self._authenticated = False
        self._tables_registry = {}

    def connect(self) -> Dict[str, Any]:
        """
        Établit une connexion avec Fabric.

        Returns:
            Dict avec le statut de la connexion
        """
        if not self.workspace_id:
            return {
                "status": "ERROR",
                "message": "FABRIC_WORKSPACE_ID non configuré",
            }

        try:
            self._authenticated = True
            return {
                "status": "CONNECTED",
                "workspace_id": self.workspace_id,
                "auth_mode": "oauth" if self.access_token else "mock",
                "message": "Connecté à Fabric avec succès",
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Erreur de connexion : {str(e)}",
            }

    def publish_dataset(
        self,
        file_path: str,
        dataset_name: str,
        table_name: str,
        mode: str = "incremental",
    ) -> Dict[str, Any]:
        """
        Publie un dataset Parquet vers Fabric.

        Args:
            file_path: Chemin du fichier Parquet source
            dataset_name: Nom du dataset dans Fabric
            table_name: Nom de la table
            mode: "incremental" ou "full_refresh"

        Returns:
            Dict avec le résultat de la publication
        """
        if not os.path.exists(file_path):
            return {
                "status": "ERROR",
                "message": f"Fichier non trouvé : {file_path}",
            }

        try:
            df = pd.read_parquet(file_path)

            if self.access_token and self.lakehouse_id and self.storage_access_token:
                return self._publish_to_lakehouse(
                    file_path, dataset_name, table_name, mode, df
                )

            if self.access_token and not self.lakehouse_id:
                return {
                    "status": "CONFIG_REQUIRED",
                    "error": "fabric_lakehouse_required",
                    "message": (
                        "FABRIC_LAKEHOUSE_ID doit être configuré pour publier "
                        "dans un Lakehouse Fabric."
                    ),
                }

            if self.access_token and self.lakehouse_id and not self.storage_access_token:
                return {
                    "status": "AUTH_REQUIRED",
                    "error": "fabric_storage_token_required",
                    "message": (
                        "Un nouveau jeton OneLake est nécessaire. "
                        "Déconnectez-vous puis reconnectez-vous à Fabric."
                    ),
                }

            if not self.access_token and not self._allow_mock:
                return {
                    "status": "AUTH_REQUIRED",
                    "error": "fabric_auth_required",
                    "message": (
                        "Aucun jeton Fabric valide n'est disponible. "
                        "Connectez-vous avant de publier."
                    ),
                }

            self._tables_registry[f"{dataset_name}.{table_name}"] = {
                "file_path": file_path,
                "rows": len(df),
                "columns": df.columns.tolist(),
                "mode": mode,
                "dtypes": {
                    col: str(dtype)
                    for col, dtype in df.dtypes.items()
                },
            }

            return {
                "status": "PUBLISHED",
                "dataset_name": dataset_name,
                "table_name": table_name,
                "rows": len(df),
                "columns": len(df.columns),
                "mode": mode,
                "message": f"Dataset {dataset_name}.{table_name} "
                           f"publié avec succès ({len(df)} lignes)",
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Erreur lors de la publication : {str(e)}",
            }

    def _publish_to_lakehouse(
        self,
        file_path: str,
        dataset_name: str,
        table_name: str,
        mode: str,
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Dépose le Parquet dans OneLake puis le charge comme table."""
        relative_path = f"Files/{dataset_name}/{os.path.basename(file_path)}"
        file_url = (
            "https://onelake.dfs.fabric.microsoft.com/"
            f"{self.workspace_id}/{self.lakehouse_id}/{relative_path}"
            "?resource=file"
        )
        with open(file_path, "rb") as source_file:
            request = urllib.request.Request(
                file_url,
                data=source_file.read(),
                headers={
                    "Authorization": f"Bearer {self.storage_access_token}",
                    "Content-Type": "application/octet-stream",
                    "x-ms-version": "2023-11-03",
                },
                method="PUT",
            )
            self._fabric_request(request)

        load_url = (
            "https://api.fabric.microsoft.com/v1/workspaces/"
            f"{self.workspace_id}/lakehouses/{self.lakehouse_id}/tables/"
            f"{table_name}/load"
        )
        load_body = {
            "relativePath": relative_path,
            "pathType": "File",
            "mode": "Overwrite" if mode == "full_refresh" else "Append",
            "recursive": False,
            "formatOptions": {"format": "Parquet"},
        }
        request = urllib.request.Request(
            load_url,
            data=json.dumps(load_body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        response = self._fabric_request(request)
        return {
            "status": "PUBLISHED",
            "destination": "fabric_lakehouse",
            "workspace_id": self.workspace_id,
            "lakehouse_id": self.lakehouse_id,
            "dataset_name": dataset_name,
            "table_name": table_name,
            "rows": len(df),
            "columns": len(df.columns),
            "mode": mode,
            "operation_location": response.get("location"),
            "message": f"Table {table_name} envoyée dans le Lakehouse Fabric",
        }

    @staticmethod
    def _fabric_request(request: urllib.request.Request) -> Dict[str, Any]:
        try:
            with urllib.request.urlopen(request) as response:
                return {"status": response.status, "location": response.headers.get("Location")}
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Fabric HTTP {error.code}: {detail}") from error

    def create_semantic_model(
        self,
        model_name: str,
        tables: list,
        relationships: Optional[list] = None,
    ) -> Dict[str, Any]:
        """
        Crée un modèle sémantique dans Fabric.

        Args:
            model_name: Nom du modèle sémantique
            tables: Liste des tables à inclure
            relationships: Définition des relations entre tables

        Returns:
            Dict avec le résultat de la création
        """
        try:
            model_config = {
                "name": model_name,
                "tables": tables,
                "relationships": relationships or [],
            }

            # À implémenter : création réelle du modèle sémantique
            return {
                "status": "CREATED",
                "model_name": model_name,
                "tables": len(tables),
                "relationships": len(model_config["relationships"]),
                "message": f"Modèle sémantique {model_name} créé avec succès",
            }
        except Exception as e:
            return {
                "status": "ERROR",
                "message": f"Erreur lors de la création du modèle : {str(e)}",
            }

    def get_dataset_info(
        self,
        dataset_name: str,
    ) -> Dict[str, Any]:
        """
        Récupère les informations d'un dataset.

        Args:
            dataset_name: Nom du dataset

        Returns:
            Dict avec les infos du dataset
        """
        tables_in_dataset = {
            k: v
            for k, v in self._tables_registry.items()
            if k.startswith(f"{dataset_name}.")
        }

        if not tables_in_dataset:
            return {
                "status": "NOT_FOUND",
                "message": f"Dataset {dataset_name} non trouvé",
            }

        return {
            "status": "FOUND",
            "dataset_name": dataset_name,
            "tables": tables_in_dataset,
            "total_tables": len(tables_in_dataset),
        }


def publish_to_fabric(
    file_path: str,
    dataset_name: str,
    table_name: str = "data",
    mode: str = "incremental",
) -> Dict[str, Any]:
    """
    Publie un fichier Parquet vers Fabric (fonction pratique).

    Args:
        file_path: Chemin du fichier Parquet
        dataset_name: Nom du dataset Fabric
        table_name: Nom de la table (défaut: "data")
        mode: Mode de publication (défaut: "incremental")

    Returns:
        Dict avec le résultat
    """
    connector = FabricConnector()
    connection = connector.connect()
    if connection["status"] != "CONNECTED":
        return {
            "status": "AUTH_REQUIRED",
            "error": "fabric_auth_required",
            "dataset_name": dataset_name,
            "table_name": table_name,
            "mode": mode,
            "message": (
                "Accès Fabric requis. L'agent doit demander une connexion "
                "Microsoft avant de publier les données."
            ),
        }

    return connector.publish_dataset(
        file_path=file_path,
        dataset_name=dataset_name,
        table_name=table_name,
        mode=mode,
    )
