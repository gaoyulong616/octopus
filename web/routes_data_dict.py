"""数据字典 REST API：实例、Schema、表、字段、索引、约束、变更日志。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from server.services.data_dict import (
    list_db_types,
    list_instances,
    get_instance,
    create_instance,
    update_instance,
    delete_instance,
    list_schemas,
    create_schema,
    update_schema,
    delete_schema,
    list_tables,
    get_table,
    create_table,
    update_table,
    delete_table,
    list_columns,
    create_column,
    update_column,
    delete_column,
    list_indexes,
    create_index,
    update_index,
    delete_index,
    list_constraints,
    create_constraint,
    update_constraint,
    delete_constraint,
    list_logs,
    list_logs_by_instance,
    list_logs_by_schema,
    list_logs_by_table,
)

router = APIRouter(prefix="/api/data-dict")


def _operator(request: Request) -> str:
    user = getattr(request.state, "user", None)
    return user.username if user else "unknown"


# ── Instance ──


@router.get("/db-types")
async def api_list_db_types(request: Request):
    return list_db_types()


@router.get("/instances")
async def api_list_instances(request: Request):
    return list_instances()


@router.get("/instances/{instance_id}")
async def api_get_instance(request: Request, instance_id: int):
    inst = get_instance(instance_id)
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")
    return inst


@router.post("/instances")
async def api_create_instance(request: Request, data: dict):
    if not data.get("instance_name") or not data.get("db_type"):
        raise HTTPException(status_code=400, detail="instance_name 和 db_type 为必填")
    try:
        inst = create_instance(data, _operator(request))
        return inst
    except Exception as e:
        if "UNIQUE" in str(e) or "unique" in str(e) or "Duplicate" in str(e):
            raise HTTPException(status_code=409, detail="实例名称已存在")
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/instances/{instance_id}")
async def api_update_instance(request: Request, instance_id: int, data: dict):
    inst = update_instance(instance_id, data, _operator(request))
    if not inst:
        raise HTTPException(status_code=404, detail="实例不存在")
    return inst


@router.delete("/instances/{instance_id}")
async def api_delete_instance(request: Request, instance_id: int):
    ok = delete_instance(instance_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="实例不存在")
    return {"ok": True}


# ── Schema ──


@router.get("/instances/{instance_id}/schemas")
async def api_list_schemas(request: Request, instance_id: int):
    return list_schemas(instance_id)


@router.post("/schemas")
async def api_create_schema(request: Request, data: dict):
    if not data.get("instance_id") or not data.get("schema_name"):
        raise HTTPException(status_code=400, detail="instance_id 和 schema_name 为必填")
    try:
        schema = create_schema(data, _operator(request))
        return schema
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/schemas/{schema_id}")
async def api_update_schema(request: Request, schema_id: int, data: dict):
    schema = update_schema(schema_id, data, _operator(request))
    if not schema:
        raise HTTPException(status_code=404, detail="Schema 不存在")
    return schema


@router.delete("/schemas/{schema_id}")
async def api_delete_schema(request: Request, schema_id: int):
    ok = delete_schema(schema_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="Schema 不存在")
    return {"ok": True}


# ── Table ──


@router.get("/schemas/{schema_id}/tables")
async def api_list_tables(request: Request, schema_id: int):
    return list_tables(schema_id)


@router.get("/tables/{table_id}")
async def api_get_table(request: Request, table_id: int):
    tbl = get_table(table_id)
    if not tbl:
        raise HTTPException(status_code=404, detail="表不存在")
    return tbl


@router.post("/tables")
async def api_create_table(request: Request, data: dict):
    if not data.get("schema_id") or not data.get("table_name"):
        raise HTTPException(status_code=400, detail="schema_id 和 table_name 为必填")
    try:
        tbl = create_table(data, _operator(request))
        return tbl
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/tables/{table_id}")
async def api_update_table(request: Request, table_id: int, data: dict):
    tbl = update_table(table_id, data, _operator(request))
    if not tbl:
        raise HTTPException(status_code=404, detail="表不存在")
    return tbl


@router.delete("/tables/{table_id}")
async def api_delete_table(request: Request, table_id: int):
    ok = delete_table(table_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="表不存在")
    return {"ok": True}


# ── Column ──


@router.get("/tables/{table_id}/columns")
async def api_list_columns(request: Request, table_id: int):
    return list_columns(table_id)


@router.post("/columns")
async def api_create_column(request: Request, data: dict):
    if not data.get("table_id") or not data.get("column_name") or not data.get("data_type"):
        raise HTTPException(status_code=400, detail="table_id, column_name, data_type 为必填")
    try:
        col = create_column(data, _operator(request))
        return col
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/columns/{column_id}")
async def api_update_column(request: Request, column_id: int, data: dict):
    col = update_column(column_id, data, _operator(request))
    if not col:
        raise HTTPException(status_code=404, detail="字段不存在")
    return col


@router.delete("/columns/{column_id}")
async def api_delete_column(request: Request, column_id: int):
    ok = delete_column(column_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="字段不存在")
    return {"ok": True}


# ── Index ──


@router.get("/tables/{table_id}/indexes")
async def api_list_indexes(request: Request, table_id: int):
    return list_indexes(table_id)


@router.post("/indexes")
async def api_create_index(request: Request, data: dict):
    if not data.get("table_id") or not data.get("index_name"):
        raise HTTPException(status_code=400, detail="table_id 和 index_name 为必填")
    try:
        idx = create_index(data, _operator(request))
        return idx
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/indexes/{index_id}")
async def api_update_index(request: Request, index_id: int, data: dict):
    idx = update_index(index_id, data, _operator(request))
    if not idx:
        raise HTTPException(status_code=404, detail="索引不存在")
    return idx


@router.delete("/indexes/{index_id}")
async def api_delete_index(request: Request, index_id: int):
    ok = delete_index(index_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="索引不存在")
    return {"ok": True}


# ── Constraint ──


@router.get("/tables/{table_id}/constraints")
async def api_list_constraints(request: Request, table_id: int):
    return list_constraints(table_id)


@router.post("/constraints")
async def api_create_constraint(request: Request, data: dict):
    if not data.get("table_id") or not data.get("constraint_name") or not data.get("constraint_type"):
        raise HTTPException(status_code=400, detail="table_id, constraint_name, constraint_type 为必填")
    try:
        con = create_constraint(data, _operator(request))
        return con
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/constraints/{constraint_id}")
async def api_update_constraint(request: Request, constraint_id: int, data: dict):
    con = update_constraint(constraint_id, data, _operator(request))
    if not con:
        raise HTTPException(status_code=404, detail="约束不存在")
    return con


@router.delete("/constraints/{constraint_id}")
async def api_delete_constraint(request: Request, constraint_id: int):
    ok = delete_constraint(constraint_id, _operator(request))
    if not ok:
        raise HTTPException(status_code=404, detail="约束不存在")
    return {"ok": True}


# ── Change Log ──


@router.get("/instances/{instance_id}/logs")
async def api_list_instance_logs(
    request: Request,
    instance_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    items, total = list_logs_by_instance(instance_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/schemas/{schema_id}/logs")
async def api_list_schema_logs(
    request: Request,
    schema_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    items, total = list_logs_by_schema(schema_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/tables/{table_id}/logs")
async def api_list_table_logs(
    request: Request,
    table_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    items, total = list_logs_by_table(table_id, page=page, page_size=page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/logs")
async def api_list_logs(
    request: Request,
    object_type: str | None = Query(None),
    object_id: int | None = Query(None),
    object_ids: str | None = Query(None, description="逗号分隔的多个 object_id"),
    operator: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
):
    parsed_ids = None
    if object_ids:
        parsed_ids = [int(x.strip()) for x in object_ids.split(",") if x.strip()]
    items, total = list_logs(
        object_type=object_type,
        object_id=object_id,
        object_ids=parsed_ids,
        operator=operator,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}
