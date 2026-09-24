"""Tests pour le module Fabric Connector."""

import pytest
import os
from src.tools.fabric_connector import FabricConnector, publish_to_fabric


@pytest.fixture
def connector():
    """Crée une instance de connecteur Fabric."""
    return FabricConnector(
        workspace_id="test-workspace",
        tenant_id="test-tenant",
        client_id="test-client",
        client_secret="test-secret"
    )


def test_fabric_connector_init(connector):
    """Test l'initialisation du connecteur Fabric."""
    assert connector.workspace_id == "test-workspace"
    assert connector.tenant_id == "test-tenant"
    assert connector.client_id == "test-client"
    assert connector.client_secret == "test-secret"


def test_connect_without_workspace_id():
    """Test la connexion sans workspace_id."""
    connector = FabricConnector()
    result = connector.connect()
    assert result["status"] == "ERROR"
    assert "FABRIC_WORKSPACE_ID" in result["message"]


def test_connect_with_workspace_id(connector):
    """Test la connexion avec workspace_id."""
    result = connector.connect()
    assert result["status"] == "CONNECTED"
    assert result["workspace_id"] == "test-workspace"


def test_publish_dataset_not_found(connector):
    """Test la publication avec fichier non trouvé."""
    connector.connect()
    result = connector.publish_dataset(
        file_path="/path/nonexistent/file.parquet",
        dataset_name="test_dataset",
        table_name="test_table"
    )
    assert result["status"] == "ERROR"
    assert "non trouvé" in result["message"]


def test_publish_requires_onelake_token(monkeypatch, connector, tmp_path):
    import pandas as pd

    test_file = tmp_path / "test.parquet"
    pd.DataFrame({"value": [1]}).to_parquet(test_file)
    monkeypatch.setenv("FABRIC_LAKEHOUSE_ID", "lakehouse")
    connector = FabricConnector(lakehouse_id="lakehouse")
    connector.access_token = "fabric-token"
    connector.storage_access_token = None

    result = connector.publish_dataset(
        file_path=str(test_file),
        dataset_name="test_dataset",
        table_name="test_table",
    )

    assert result["status"] == "AUTH_REQUIRED"
    assert result["error"] == "fabric_storage_token_required"


def test_publish_dataset_success(connector, tmp_path):
    """Test la publication réussie d'un dataset."""
    import pandas as pd

    # Crée un fichier Parquet temporaire
    test_file = tmp_path / "test.parquet"
    df = pd.DataFrame({
        "id": [1, 2, 3],
        "name": ["A", "B", "C"],
        "value": [10.5, 20.3, 30.1]
    })
    df.to_parquet(test_file)

    connector.connect()
    result = connector.publish_dataset(
        file_path=str(test_file),
        dataset_name="test_dataset",
        table_name="test_table",
        mode="incremental"
    )

    assert result["status"] == "PUBLISHED"
    assert result["dataset_name"] == "test_dataset"
    assert result["table_name"] == "test_table"
    assert result["rows"] == 3
    assert result["columns"] == 3
    assert result["mode"] == "incremental"


def test_get_dataset_info_not_found(connector):
    """Test la récupération d'info dataset non existant."""
    connector.connect()
    result = connector.get_dataset_info("nonexistent_dataset")
    assert result["status"] == "NOT_FOUND"


def test_get_dataset_info_found(connector, tmp_path):
    """Test la récupération d'info dataset existant."""
    import pandas as pd

    test_file = tmp_path / "test.parquet"
    df = pd.DataFrame({"col": [1, 2, 3]})
    df.to_parquet(test_file)

    connector.connect()
    connector.publish_dataset(
        file_path=str(test_file),
        dataset_name="test_dataset",
        table_name="test_table"
    )

    result = connector.get_dataset_info("test_dataset")
    assert result["status"] == "FOUND"
    assert result["dataset_name"] == "test_dataset"
    assert result["total_tables"] == 1


def test_publish_to_fabric_function(tmp_path):
    """Test la fonction pratique publish_to_fabric."""
    import pandas as pd

    test_file = tmp_path / "test.parquet"
    df = pd.DataFrame({"value": [1, 2, 3]})
    df.to_parquet(test_file)

    result = publish_to_fabric(
        file_path=str(test_file),
        dataset_name="sales_analysis",
        table_name="sales",
        mode="full_refresh"
    )

    assert result["status"] == "AUTH_REQUIRED"
    assert result["error"] == "fabric_auth_required"
    assert result["dataset_name"] == "sales_analysis"
