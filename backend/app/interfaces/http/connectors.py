"""Connector manifest and health API."""

from fastapi import APIRouter, HTTPException

from app.domains.fetch.connectors import builtin_connectors

router = APIRouter()


@router.get("")  # noqa: V103
def list_connectors():  # noqa: V103
    return {
        "items": [manifest.model_dump(mode="json") for manifest in builtin_connectors.list_manifests()],
        "health": [item.model_dump(mode="json") for item in builtin_connectors.health()],
    }


@router.get("/{connector_id}")  # noqa: V103
def get_connector(connector_id: str):  # noqa: V103
    connector = builtin_connectors.get(connector_id)
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return {"manifest": connector.manifest.model_dump(mode="json")}
