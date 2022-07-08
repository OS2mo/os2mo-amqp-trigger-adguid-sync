# SPDX-FileCopyrightText: 2019-2020 Magenta ApS
#
# SPDX-License-Identifier: MPL-2.0
"""Event handling."""
from asyncio import gather
from functools import partial
from typing import Any
from typing import Callable
from typing import cast
from uuid import UUID
from operator import itemgetter

from gql import gql
from fastapi import FastAPI
from fastapi import Request
from fastapi import Query
from fastapi import APIRouter
from fastramqpi.main import FastRAMQPI
from fastramqpi.context import Context

from .calculate import ensure_adguid_itsystem
from .dataloaders import seed_dataloaders


fastapi_router = APIRouter()


def gen_ensure_adguid_itsystem(context: Context) -> Callable[[UUID], bool]:
    """Seed ensure_adguid_itsystem with arguments from context.

    Args:
        context: dictionary to extract arguments from.

    Returns:
        ensure_adguid_itsystem that only takes an UUID.
    """
    return partial(
        ensure_adguid_itsystem,
        dataloaders=context["user_context"]["dataloaders"],
        model_client=context["model_client"],
    )


@fastapi_router.post(
    "/trigger/all",
)
async def update_all_employees(request: Request) -> dict[str, str]:
    """Call update_line_management on all org units."""
    context: dict[str, Any] = request.app.state.context
    gql_session = context["graphql_session"]
    query = gql("query EmployeeUUIDQuery { employees { uuid } }")
    result = await gql_session.execute(query)
    employee_uuids = map(UUID, map(itemgetter("uuid"), result["employees"]))
    employee_tasks = map(gen_ensure_adguid_itsystem(context), employee_uuids)
    all_ok = all(await gather(*employee_tasks))
    return {"status": "OK" if all_ok else "FAILURE"}


@fastapi_router.post(
    "/trigger/{uuid}",
)
async def update_employee(
    request: Request,
    uuid: UUID = Query(..., description="UUID of the employee to recalculate"),
) -> dict[str, str]:
    """Call ensure_adguid_itsystem on the provided employee."""
    context: dict[str, Any] = request.app.state.context
    ok = await gen_ensure_adguid_itsystem(context)(uuid)
    return {"status": "OK" if ok else "FAILURE"}


def create_app(**kwargs: Any) -> FastAPI:
    """FastAPI application factory.

    Returns:
        None
    """
    fastramqpi = FastRAMQPI(application_name="adguidsync", **kwargs)
    fastramqpi.add_lifespan_manager(
        partial(seed_dataloaders, fastramqpi)(), 2000
    )

    app = fastramqpi.get_app()
    app.include_router(fastapi_router)

    return cast(FastAPI, fastramqpi.get_app())
