"""数据字典服务层：CRUD 操作 + 自动变更日志记录。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import desc, or_, and_
from sqlalchemy.orm import joinedload

from server.database import get_session
from server.models.data_dict import (
    DbInstance,
    DbSchema,
    DbTable,
    DbColumn,
    DbIndex,
    DbConstraint,
    DbMetaChangeLog,
)

_OBJECT_TYPE_MAP = {
    "instance": "instance",
    "schema": "schema",
    "table": "table",
    "column": "column",
    "index": "index",
    "constraint": "constraint",
}

# 各模型对应的名称字段
_OBJECT_NAME_FIELD = {
    "dbinstance": "instance_name",
    "dbschema": "schema_name",
    "dbtable": "table_name",
    "dbcolumn": "column_name",
    "dbindex": "index_name",
    "dbconstraint": "constraint_name",
}


# ── 内部工具 ──


def _log(
    object_type: str,
    object_id: int,
    field_name: str,
    old_value: str | None,
    new_value: str | None,
    operator: str,
    op_type: str,
    session,
):
    log = DbMetaChangeLog(
        object_type=object_type,
        object_id=object_id,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        operator=operator,
        op_type=op_type,
    )
    session.add(log)


def _get_obj_name(obj: Any) -> str:
    """获取对象可读名称，用于日志记录。"""
    key = type(obj).__name__.lower()
    field = _OBJECT_NAME_FIELD.get(key)
    if field:
        val = getattr(obj, field, None)
        if val is not None:
            return str(val)
    return str(obj.id)


def _log_insert(obj: Any, operator: str, session):
    _log(
        object_type=_OBJECT_TYPE_MAP.get(type(obj).__name__.lower().replace("db", ""), "unknown"),
        object_id=obj.id,
        field_name="*",
        old_value=None,
        new_value=_get_obj_name(obj),
        operator=operator,
        op_type="insert",
        session=session,
    )


def _log_delete(obj: Any, operator: str, session):
    name = _get_obj_name(obj)
    _log(
        object_type=_OBJECT_TYPE_MAP.get(type(obj).__name__.lower().replace("db", ""), "unknown"),
        object_id=obj.id,
        field_name="*",
        old_value=name,
        new_value=None,
        operator=operator,
        op_type="delete",
        session=session,
    )


def _log_update(obj: Any, before: dict, after: dict, operator: str, session):
    obj_type = _OBJECT_TYPE_MAP.get(type(obj).__name__.lower().replace("db", ""), "unknown")
    oid = obj.id
    for key in before:
        if key in ("create_time", "update_time", "id"):
            continue
        old = before[key]
        new = after.get(key)
        if str(old) != str(new):
            _log(
                object_type=obj_type,
                object_id=oid,
                field_name=key,
                old_value=str(old) if old is not None else None,
                new_value=str(new) if new is not None else None,
                operator=operator,
                op_type="update",
                session=session,
            )


def _dict_exclude(d: dict, *keys: str) -> dict:
    return {k: v for k, v in d.items() if k not in keys}


def _now() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")


# ── Instance ──


def list_db_types() -> list[str]:
    """常用类型 + 数据库中已有的类型（去重合集）。"""
    defaults = {"mysql", "postgresql", "oracle", "mariadb"}
    with get_session() as session:
        rows = session.query(DbInstance.db_type).distinct().order_by(DbInstance.db_type).all()
        for r in rows:
            defaults.add(r[0])
    return sorted(defaults)


def list_instances(page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = session.query(DbInstance).order_by(DbInstance.instance_name)
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        instances = q.all()
        items = [inst.to_dict(depth=1) for inst in instances]
        return (items, total) if page is not None else items


def get_instance(instance_id: int) -> dict | None:
    with get_session() as session:
        inst = (
            session.query(DbInstance)
            .options(joinedload(DbInstance.schemas))
            .filter(DbInstance.id == instance_id)
            .first()
        )
        if not inst:
            return None
        return inst.to_dict(depth=2)


def create_instance(data: dict, operator: str) -> dict:
    with get_session() as session:
        inst = DbInstance(
            instance_name=data["instance_name"],
            db_type=data.get("db_type", "mysql"),
            datasource_id=data.get("datasource_id"),
            remark=data.get("remark"),
        )
        session.add(inst)
        session.flush()
        _log_insert(inst, operator, session)
        session.commit()
        return inst.to_dict()


def update_instance(instance_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        inst = session.query(DbInstance).filter(DbInstance.id == instance_id).first()
        if not inst:
            return None
        before = inst.to_dict()
        for key in ("instance_name", "db_type", "datasource_id", "remark"):
            if key in data:
                setattr(inst, key, data[key])
        session.flush()
        after = inst.to_dict()
        _log_update(inst, before, after, operator, session)
        session.commit()
        return inst.to_dict()


def delete_instance(instance_id: int, operator: str) -> bool:
    with get_session() as session:
        inst = session.query(DbInstance).filter(DbInstance.id == instance_id).first()
        if not inst:
            return False
        _log_delete(inst, operator, session)
        session.delete(inst)
        session.commit()
        return True


# ── Schema ──


def list_schemas(instance_id: int, page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = (
            session.query(DbSchema)
            .filter(DbSchema.instance_id == instance_id)
            .order_by(DbSchema.schema_name)
        )
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        items = [s.to_dict() for s in q.all()]
        return (items, total) if page is not None else items


def create_schema(data: dict, operator: str) -> dict:
    with get_session() as session:
        schema = DbSchema(
            instance_id=data["instance_id"],
            schema_name=data["schema_name"],
            remark=data.get("remark"),
        )
        session.add(schema)
        session.flush()
        _log_insert(schema, operator, session)
        session.commit()
        return schema.to_dict()


def update_schema(schema_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        schema = session.query(DbSchema).filter(DbSchema.id == schema_id).first()
        if not schema:
            return None
        before = schema.to_dict()
        for key in ("schema_name", "remark"):
            if key in data:
                setattr(schema, key, data[key])
        session.flush()
        after = schema.to_dict()
        _log_update(schema, before, after, operator, session)
        session.commit()
        return schema.to_dict()


def delete_schema(schema_id: int, operator: str) -> bool:
    with get_session() as session:
        schema = session.query(DbSchema).filter(DbSchema.id == schema_id).first()
        if not schema:
            return False
        _log_delete(schema, operator, session)
        session.delete(schema)
        session.commit()
        return True


# ── Table ──


def list_tables(schema_id: int, page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = (
            session.query(DbTable)
            .filter(DbTable.schema_id == schema_id)
            .order_by(DbTable.table_name)
        )
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        items = [t.to_dict() for t in q.all()]
        return (items, total) if page is not None else items


def get_table(table_id: int) -> dict | None:
    with get_session() as session:
        tbl = (
            session.query(DbTable)
            .options(
                joinedload(DbTable.columns),
                joinedload(DbTable.indexes),
                joinedload(DbTable.constraints),
            )
            .filter(DbTable.id == table_id)
            .first()
        )
        if not tbl:
            return None
        return tbl.to_dict(depth=1)


def create_table(data: dict, operator: str) -> dict:
    with get_session() as session:
        tbl = DbTable(
            schema_id=data["schema_id"],
            table_name=data["table_name"],
            table_type=data.get("table_type", "BASE TABLE"),
            comment=data.get("comment"),
            tags=data.get("tags"),
        )
        session.add(tbl)
        session.flush()
        _log_insert(tbl, operator, session)
        session.commit()
        return tbl.to_dict()


def update_table(table_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        tbl = session.query(DbTable).filter(DbTable.id == table_id).first()
        if not tbl:
            return None
        before = tbl.to_dict()
        for key in ("table_name", "table_type", "comment", "tags"):
            if key in data:
                setattr(tbl, key, data[key])
        session.flush()
        after = tbl.to_dict()
        _log_update(tbl, before, after, operator, session)
        session.commit()
        return tbl.to_dict()


def delete_table(table_id: int, operator: str) -> bool:
    with get_session() as session:
        tbl = session.query(DbTable).filter(DbTable.id == table_id).first()
        if not tbl:
            return False
        _log_delete(tbl, operator, session)
        session.delete(tbl)
        session.commit()
        return True


# ── Column ──


def list_columns(table_id: int, page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = (
            session.query(DbColumn)
            .filter(DbColumn.table_id == table_id)
            .order_by(DbColumn.position)
        )
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        items = [c.to_dict() for c in q.all()]
        return (items, total) if page is not None else items


def create_column(data: dict, operator: str) -> dict:
    with get_session() as session:
        col = DbColumn(
            table_id=data["table_id"],
            column_name=data["column_name"],
            data_type=data["data_type"],
            full_data_type=data.get("full_data_type"),
            nullable=data.get("nullable", False),
            comment=data.get("comment"),
            position=data.get("position", 0),
            tags=data.get("tags"),
            enum_info=data.get("enum_info"),
        )
        session.add(col)
        session.flush()
        _log_insert(col, operator, session)
        session.commit()
        return col.to_dict()


def update_column(column_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        col = session.query(DbColumn).filter(DbColumn.id == column_id).first()
        if not col:
            return None
        before = col.to_dict()
        for key in ("column_name", "data_type", "full_data_type", "nullable", "comment", "position", "tags", "enum_info"):
            if key in data:
                setattr(col, key, data[key])
        session.flush()
        after = col.to_dict()
        _log_update(col, before, after, operator, session)
        session.commit()
        return col.to_dict()


def delete_column(column_id: int, operator: str) -> bool:
    with get_session() as session:
        col = session.query(DbColumn).filter(DbColumn.id == column_id).first()
        if not col:
            return False
        _log_delete(col, operator, session)
        session.delete(col)
        session.commit()
        return True


# ── Index ──


def list_indexes(table_id: int, page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = (
            session.query(DbIndex)
            .filter(DbIndex.table_id == table_id)
            .order_by(DbIndex.index_name)
        )
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        items = [i.to_dict() for i in q.all()]
        return (items, total) if page is not None else items


def create_index(data: dict, operator: str) -> dict:
    with get_session() as session:
        idx = DbIndex(
            table_id=data["table_id"],
            index_name=data["index_name"],
            index_type=data.get("index_type", "btree"),
            is_unique=data.get("is_unique", False),
            column_ids=data.get("column_ids", []),
        )
        session.add(idx)
        session.flush()
        _log_insert(idx, operator, session)
        session.commit()
        return idx.to_dict()


def update_index(index_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        idx = session.query(DbIndex).filter(DbIndex.id == index_id).first()
        if not idx:
            return None
        before = idx.to_dict()
        for key in ("index_name", "index_type", "is_unique", "column_ids"):
            if key in data:
                setattr(idx, key, data[key])
        session.flush()
        after = idx.to_dict()
        _log_update(idx, before, after, operator, session)
        session.commit()
        return idx.to_dict()


def delete_index(index_id: int, operator: str) -> bool:
    with get_session() as session:
        idx = session.query(DbIndex).filter(DbIndex.id == index_id).first()
        if not idx:
            return False
        _log_delete(idx, operator, session)
        session.delete(idx)
        session.commit()
        return True


# ── Constraint ──


def list_constraints(table_id: int, page: int | None = None, page_size: int = 20) -> list[dict] | tuple[list[dict], int]:
    with get_session() as session:
        q = (
            session.query(DbConstraint)
            .filter(DbConstraint.table_id == table_id)
            .order_by(DbConstraint.constraint_name)
        )
        total = q.count() if page is not None else 0
        if page is not None:
            q = q.offset((page - 1) * page_size).limit(page_size)
        items = [c.to_dict() for c in q.all()]
        return (items, total) if page is not None else items


def create_constraint(data: dict, operator: str) -> dict:
    with get_session() as session:
        con = DbConstraint(
            table_id=data["table_id"],
            constraint_type=data["constraint_type"],
            constraint_name=data["constraint_name"],
            column_ids=data.get("column_ids", []),
            target_table_id=data.get("target_table_id"),
            target_column_ids=data.get("target_column_ids"),
            on_delete=data.get("on_delete"),
            on_update=data.get("on_update"),
        )
        session.add(con)
        session.flush()
        _log_insert(con, operator, session)
        session.commit()
        return con.to_dict()


def update_constraint(constraint_id: int, data: dict, operator: str) -> dict | None:
    with get_session() as session:
        con = session.query(DbConstraint).filter(DbConstraint.id == constraint_id).first()
        if not con:
            return None
        before = con.to_dict()
        for key in (
            "constraint_type", "constraint_name", "column_ids",
            "target_table_id", "target_column_ids", "on_delete", "on_update",
        ):
            if key in data:
                setattr(con, key, data[key])
        session.flush()
        after = con.to_dict()
        _log_update(con, before, after, operator, session)
        session.commit()
        return con.to_dict()


def delete_constraint(constraint_id: int, operator: str) -> bool:
    with get_session() as session:
        con = session.query(DbConstraint).filter(DbConstraint.id == constraint_id).first()
        if not con:
            return False
        _log_delete(con, operator, session)
        session.delete(con)
        session.commit()
        return True


# ── Search ──


def search_tables(
    q: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[dict], int]:
    """跨表名、表注释、字段名、字段注释模糊搜索，返回统一结果列表。"""
    pattern = f"%{q}%"
    with get_session() as session:
        table_q = (
            session.query(
                DbTable.id.label("table_id"),
                DbTable.table_name,
                DbTable.comment.label("table_comment"),
                DbTable.tags.label("table_tags"),
                DbSchema.id.label("schema_id"),
                DbSchema.schema_name,
                DbInstance.id.label("instance_id"),
                DbInstance.instance_name,
            )
            .join(DbSchema, DbTable.schema_id == DbSchema.id)
            .join(DbInstance, DbSchema.instance_id == DbInstance.id)
            .filter(
                or_(
                    DbTable.table_name.ilike(pattern),
                    DbTable.comment.ilike(pattern),
                    DbTable.tags.ilike(pattern),
                )
            )
            .distinct()
            .subquery()
        )
        table_rows = session.query(table_q).all()

        column_q = (
            session.query(
                DbColumn.id.label("column_id"),
                DbColumn.column_name,
                DbColumn.comment.label("column_comment"),
                DbColumn.tags.label("column_tags"),
                DbTable.id.label("table_id"),
                DbTable.table_name,
                DbTable.comment.label("table_comment"),
                DbTable.tags.label("table_tags"),
                DbSchema.id.label("schema_id"),
                DbSchema.schema_name,
                DbInstance.id.label("instance_id"),
                DbInstance.instance_name,
            )
            .join(DbTable, DbColumn.table_id == DbTable.id)
            .join(DbSchema, DbTable.schema_id == DbSchema.id)
            .join(DbInstance, DbSchema.instance_id == DbInstance.id)
            .filter(
                or_(
                    DbColumn.column_name.ilike(pattern),
                    DbColumn.comment.ilike(pattern),
                    DbColumn.tags.ilike(pattern),
                )
            )
            .distinct()
            .subquery()
        )
        column_rows = session.query(column_q).all()

    results: list[dict] = []
    for r in table_rows:
        results.append({
            "type": "table",
            "table_id": r.table_id,
            "table_name": r.table_name,
            "table_comment": r.table_comment or "",
            "table_tags": r.table_tags or "",
            "schema_id": r.schema_id,
            "schema_name": r.schema_name,
            "instance_id": r.instance_id,
            "instance_name": r.instance_name,
            "column_name": None,
            "column_comment": None,
            "matched_field": (
                "table_name" if r.table_name and q.lower() in r.table_name.lower()
                else "tags" if r.table_tags and q.lower() in r.table_tags.lower()
                else "table_comment"
            ),
        })
    for r in column_rows:
        results.append({
            "type": "column",
            "table_id": r.table_id,
            "table_name": r.table_name,
            "table_comment": r.table_comment or "",
            "table_tags": r.table_tags or "",
            "schema_id": r.schema_id,
            "schema_name": r.schema_name,
            "instance_id": r.instance_id,
            "instance_name": r.instance_name,
            "column_name": r.column_name,
            "column_comment": r.column_comment or "",
            "column_tags": r.column_tags or "",
            "matched_field": (
                "column_name" if r.column_name and q.lower() in r.column_name.lower()
                else "tags" if r.column_tags and q.lower() in r.column_tags.lower()
                else "column_comment"
            ),
        })

    results.sort(key=lambda x: (
        x["instance_name"] or "",
        x["schema_name"] or "",
        x["table_name"] or "",
    ))

    total = len(results)
    start = (page - 1) * page_size
    page_items = results[start:start + page_size]
    return page_items, total


# ── Change Log ──


def _enrich_logs(logs: list[dict]) -> list[dict]:
    """为日志条目补充层级上下文（_context 字段），标明所在实例 > Schema > 表。"""
    if not logs:
        return logs

    col_ids, idx_ids, con_ids, tbl_ids, sch_ids = [], [], [], [], []
    for log in logs:
        t, oid = log["object_type"], log["object_id"]
        if t == "column": col_ids.append(oid)
        elif t == "index": idx_ids.append(oid)
        elif t == "constraint": con_ids.append(oid)
        elif t == "table": tbl_ids.append(oid)
        elif t == "schema": sch_ids.append(oid)

    with get_session() as session:
        cols = {c.id: c for c in session.query(DbColumn).filter(DbColumn.id.in_(col_ids)).all()} if col_ids else {}
        idxs = {i.id: i for i in session.query(DbIndex).filter(DbIndex.id.in_(idx_ids)).all()} if idx_ids else {}
        cons = {c.id: c for c in session.query(DbConstraint).filter(DbConstraint.id.in_(con_ids)).all()} if con_ids else {}

        all_tbl_ids = set(tbl_ids)
        for c in cols.values(): all_tbl_ids.add(c.table_id)
        for i in idxs.values(): all_tbl_ids.add(i.table_id)
        for c in cons.values(): all_tbl_ids.add(c.table_id)

        tbls = {t.id: t for t in session.query(DbTable).filter(DbTable.id.in_(list(all_tbl_ids))).all()} if all_tbl_ids else {}

        all_sch_ids = set(sch_ids)
        for t in tbls.values(): all_sch_ids.add(t.schema_id)

        schs = {s.id: s for s in session.query(DbSchema).filter(DbSchema.id.in_(list(all_sch_ids))).all()} if all_sch_ids else {}

        inst_ids = {s.instance_id for s in schs.values()}
        insts = {i.id: i for i in session.query(DbInstance).filter(DbInstance.id.in_(list(inst_ids))).all()} if inst_ids else {}

    # Build context lookup tables
    schema_inst = {}  # schema_id -> instance_name
    for s in schs.values():
        inst = insts.get(s.instance_id)
        if inst:
            schema_inst[s.id] = inst.instance_name

    tbl_ctx = {}  # table_id -> "instance > schema" or "schema"
    for t in tbls.values():
        schema = schs.get(t.schema_id)
        if schema:
            parts = [schema.schema_name]
            inst_name = schema_inst.get(schema.id)
            if inst_name:
                parts.insert(0, inst_name)
            tbl_ctx[t.id] = " > ".join(parts)

    enriched = []
    for log in logs:
        log = dict(log)
        t, oid = log["object_type"], log["object_id"]
        if t in ("column", "index", "constraint"):
            obj = {"column": cols, "index": idxs, "constraint": cons}[t].get(oid)
            if obj and obj.table_id in tbl_ctx:
                log["_context"] = tbl_ctx[obj.table_id]
        elif t == "table":
            if oid in tbl_ctx:
                log["_context"] = tbl_ctx[oid]
        elif t == "schema":
            if oid in schema_inst:
                log["_context"] = schema_inst[oid]
        enriched.append(log)

    return enriched


def list_logs_by_instance(instance_id: int, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    """收集实例下所有对象的变更日志（实例 + Schema + 表 + 字段 + 索引 + 约束）。"""
    with get_session() as session:
        pairs: list[tuple[str, int]] = [("instance", instance_id)]
        schemas = session.query(DbSchema).filter(DbSchema.instance_id == instance_id).all()
        if schemas:
            schema_ids = [s.id for s in schemas]
            pairs.extend(("schema", sid) for sid in schema_ids)
            tables = session.query(DbTable).filter(DbTable.schema_id.in_(schema_ids)).all()
            if tables:
                table_ids = [t.id for t in tables]
                pairs.extend(("table", tid) for tid in table_ids)
                cols = session.query(DbColumn).filter(DbColumn.table_id.in_(table_ids)).all()
                pairs.extend(("column", c.id) for c in cols)
                idxs = session.query(DbIndex).filter(DbIndex.table_id.in_(table_ids)).all()
                pairs.extend(("index", i.id) for i in idxs)
                cons = session.query(DbConstraint).filter(DbConstraint.table_id.in_(table_ids)).all()
                pairs.extend(("constraint", c.id) for c in cons)
    logs, total = list_logs(object_pairs=pairs, offset=(page - 1) * page_size, limit=page_size)
    return _enrich_logs(logs), total


def list_logs_by_schema(schema_id: int, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    """收集 schema 下所有对象的变更日志（Schema + 表 + 字段 + 索引 + 约束）。"""
    with get_session() as session:
        pairs: list[tuple[str, int]] = [("schema", schema_id)]
        tables = session.query(DbTable).filter(DbTable.schema_id == schema_id).all()
        if tables:
            table_ids = [t.id for t in tables]
            pairs.extend(("table", tid) for tid in table_ids)
            cols = session.query(DbColumn).filter(DbColumn.table_id.in_(table_ids)).all()
            pairs.extend(("column", c.id) for c in cols)
            idxs = session.query(DbIndex).filter(DbIndex.table_id.in_(table_ids)).all()
            pairs.extend(("index", i.id) for i in idxs)
            cons = session.query(DbConstraint).filter(DbConstraint.table_id.in_(table_ids)).all()
            pairs.extend(("constraint", c.id) for c in cons)
    logs, total = list_logs(object_pairs=pairs, offset=(page - 1) * page_size, limit=page_size)
    return _enrich_logs(logs), total


def list_logs_by_table(table_id: int, page: int = 1, page_size: int = 50) -> tuple[list[dict], int]:
    """收集表下所有对象的变更日志（表 + 字段 + 索引 + 约束）。"""
    with get_session() as session:
        pairs: list[tuple[str, int]] = [("table", table_id)]
        cols = session.query(DbColumn).filter(DbColumn.table_id == table_id).all()
        pairs.extend(("column", c.id) for c in cols)
        idxs = session.query(DbIndex).filter(DbIndex.table_id == table_id).all()
        pairs.extend(("index", i.id) for i in idxs)
        cons = session.query(DbConstraint).filter(DbConstraint.table_id == table_id).all()
        pairs.extend(("constraint", c.id) for c in cons)
    logs, total = list_logs(object_pairs=pairs, offset=(page - 1) * page_size, limit=page_size)
    return _enrich_logs(logs), total


def list_logs(
    object_type: str | None = None,
    object_id: int | None = None,
    object_ids: list[int] | None = None,
    object_pairs: list[tuple[str, int]] | None = None,
    operator: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    with get_session() as session:
        q = session.query(DbMetaChangeLog)
        if object_type:
            q = q.filter(DbMetaChangeLog.object_type == object_type)
        if object_pairs:
            # Group by type to reduce OR branches: at most 6 types vs potentially hundreds of pairs
            by_type: dict[str, list[int]] = {}
            for t, i in object_pairs:
                by_type.setdefault(t, []).append(i)
            filters = [
                and_(
                    DbMetaChangeLog.object_type == t,
                    DbMetaChangeLog.object_id.in_(ids),
                )
                for t, ids in by_type.items()
            ]
            q = q.filter(or_(*filters))
        elif object_ids:
            q = q.filter(DbMetaChangeLog.object_id.in_(object_ids))
        elif object_id is not None:
            q = q.filter(DbMetaChangeLog.object_id == object_id)
        if operator:
            q = q.filter(DbMetaChangeLog.operator == operator)
        total = q.count()
        logs = q.order_by(desc(DbMetaChangeLog.id)).offset(offset).limit(limit).all()
        return [log.to_dict() for log in logs], total
