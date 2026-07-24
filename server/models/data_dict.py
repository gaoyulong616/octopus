"""数据字典模型：实例、Schema、表、字段、索引、约束、变更日志。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, JSON
from sqlalchemy import ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.user import Base


def _bj_now() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


class DbInstance(Base):
    __tablename__ = "db_instance"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, comment="实例名称(唯一标识)")
    db_type: Mapped[str] = mapped_column(String(50), nullable=False, comment="数据库类型 postgresql/mysql")
    datasource_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="数据源ID")
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注说明")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    schemas: Mapped[list["DbSchema"]] = relationship(
        "DbSchema", back_populates="instance", cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self, depth: int = 0) -> dict:
        d = {
            "id": self.id,
            "instance_name": self.instance_name,
            "db_type": self.db_type,
            "datasource_id": self.datasource_id,
            "remark": self.remark,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }
        if depth > 0:
            d["schemas"] = [s.to_dict(depth - 1) for s in self.schemas]
        return d


class DbSchema(Base):
    __tablename__ = "db_schema_info"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("db_instance.id", ondelete="CASCADE"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="schema名称")
    remark: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="备注")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    instance: Mapped["DbInstance"] = relationship("DbInstance", back_populates="schemas")
    tables: Mapped[list["DbTable"]] = relationship(
        "DbTable", back_populates="schema", cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self, depth: int = 0) -> dict:
        d = {
            "id": self.id,
            "instance_id": self.instance_id,
            "schema_name": self.schema_name,
            "remark": self.remark,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }
        if depth > 0:
            d["tables"] = [t.to_dict(depth - 1) for t in self.tables]
        return d


class DbTable(Base):
    __tablename__ = "db_table"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    schema_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("db_schema_info.id", ondelete="CASCADE"), nullable=False
    )
    table_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="表名")
    table_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="BASE TABLE", comment="类型 BASE TABLE / VIEW"
    )
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="表注释")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    schema: Mapped["DbSchema"] = relationship("DbSchema", back_populates="tables")
    columns: Mapped[list["DbColumn"]] = relationship(
        "DbColumn", back_populates="table", cascade="all, delete-orphan",
        passive_deletes=True,
    )
    indexes: Mapped[list["DbIndex"]] = relationship(
        "DbIndex", back_populates="table", cascade="all, delete-orphan",
        passive_deletes=True,
    )
    constraints: Mapped[list["DbConstraint"]] = relationship(
        "DbConstraint", back_populates="table", cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self, depth: int = 0) -> dict:
        d = {
            "id": self.id,
            "schema_id": self.schema_id,
            "table_name": self.table_name,
            "table_type": self.table_type,
            "comment": self.comment,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }
        if depth > 0:
            d["columns"] = [c.to_dict() for c in self.columns]
            d["indexes"] = [i.to_dict() for i in self.indexes]
            d["constraints"] = [c.to_dict() for c in self.constraints]
        return d


class DbColumn(Base):
    __tablename__ = "db_column"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("db_table.id", ondelete="CASCADE"), nullable=False
    )
    column_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="字段名称")
    data_type: Mapped[str] = mapped_column(String(100), nullable=False, comment="基础数据类型")
    full_data_type: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True, comment="完整类型(含长度、精度)"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, comment="字段排序序号")
    nullable: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否允许为空")
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="字段注释")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    table: Mapped["DbTable"] = relationship("DbTable", back_populates="columns")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "column_name": self.column_name,
            "data_type": self.data_type,
            "full_data_type": self.full_data_type,
            "position": self.position,
            "nullable": self.nullable,
            "comment": self.comment,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }


class DbIndex(Base):
    __tablename__ = "db_index"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("db_table.id", ondelete="CASCADE"), nullable=False
    )
    index_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="索引名称")
    index_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="btree", comment="索引类型 btree/gin/hash"
    )
    is_unique: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否唯一索引")
    column_ids: Mapped[list] = mapped_column(JSON, nullable=False, comment="包含字段ID数组")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    table: Mapped["DbTable"] = relationship("DbTable", back_populates="indexes")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "index_name": self.index_name,
            "index_type": self.index_type,
            "is_unique": self.is_unique,
            "column_ids": self.column_ids,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }


class DbConstraint(Base):
    __tablename__ = "db_constraint"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    table_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("db_table.id", ondelete="CASCADE"), nullable=False
    )
    constraint_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="约束类型 primary / foreign / unique"
    )
    constraint_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="约束名称")
    column_ids: Mapped[list] = mapped_column(JSON, nullable=False, comment="当前表字段ID数组")
    target_table_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True, comment="外键目标表ID"
    )
    target_column_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True, comment="外键目标字段ID数组")
    on_delete: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="外键on_delete行为")
    on_update: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="外键on_update行为")
    create_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, onupdate=_bj_now, comment="更新时间"
    )

    table: Mapped["DbTable"] = relationship("DbTable", back_populates="constraints")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "table_id": self.table_id,
            "constraint_type": self.constraint_type,
            "constraint_name": self.constraint_name,
            "column_ids": self.column_ids,
            "target_table_id": self.target_table_id,
            "target_column_ids": self.target_column_ids,
            "on_delete": self.on_delete,
            "on_update": self.on_update,
            "create_time": _dt_str(self.create_time),
            "update_time": _dt_str(self.update_time),
        }


class DbMetaChangeLog(Base):
    __tablename__ = "db_meta_change_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    object_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="对象类型 instance/schema/table/column/index/constraint"
    )
    object_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="对象主键ID")
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="变更字段名")
    old_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="变更前值")
    new_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="变更后值")
    operator: Mapped[str] = mapped_column(String(100), nullable=False, comment="操作人账号")
    op_type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="操作类型 insert/update/delete"
    )
    create_at: Mapped[datetime] = mapped_column(
        DateTime(3), default=_bj_now, comment="变更时间"
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "object_type": self.object_type,
            "object_id": self.object_id,
            "field_name": self.field_name,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "operator": self.operator,
            "op_type": self.op_type,
            "create_at": _dt_str(self.create_at),
        }


def _dt_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
