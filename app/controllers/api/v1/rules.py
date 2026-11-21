"""Dosing rules with their label chunks (pharmacist and admin)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.controllers.deps import CurrentUser, get_container, require_roles
from app.models.container import Container
from app.models.rules_service import list_rules
from app.views.schemas.rules import RuleList

router = APIRouter(tags=["rules"])


@router.get("/rules", response_model=RuleList, summary="Per-drug rules, label chunks and verification status")
def get_rules(
    container: Annotated[Container, Depends(get_container)],
    _user: Annotated[CurrentUser, Depends(require_roles("pharmacist", "admin"))],
) -> RuleList:
    return RuleList(items=list_rules(container.catalog))
