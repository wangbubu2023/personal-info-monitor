"""Operator-facing site-rule validation and lifecycle endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.domains.fetch.site_rules import RuleValidationError, SiteRuleStatus, builtin_registry, validate_rule

router = APIRouter()


class RuleLifecycleRequest(BaseModel):
    status: SiteRuleStatus


@router.get("")  # noqa: V103
def list_site_rules():  # noqa: V103
    return {
        "items": [rule.model_dump(mode="json", exclude_none=True) for rule in builtin_registry.list()],
        "count": len(builtin_registry.list()),
    }


@router.get("/{rule_id}")  # noqa: V103
def get_site_rule(rule_id: str):  # noqa: V103
    rules = builtin_registry.list(rule_id=rule_id)
    if not rules:
        raise HTTPException(status_code=404, detail="Site rule not found")
    return {"items": [rule.model_dump(mode="json", exclude_none=True) for rule in rules]}


@router.post("/validate")  # noqa: V103
def validate_site_rule(payload: dict):  # noqa: V103
    try:
        rule = validate_rule(payload)
    except RuleValidationError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return {"valid": True, "rule": rule.model_dump(mode="json", exclude_none=True)}


@router.post("/{rule_id}/{revision}/lifecycle")  # noqa: V103
def update_site_rule_lifecycle(rule_id: str, revision: int, req: RuleLifecycleRequest):  # noqa: V103
    try:
        rule = builtin_registry.promote(rule_id, revision, req.status)
    except RuleValidationError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {"status": "updated", "rule": rule.model_dump(mode="json", exclude_none=True)}
