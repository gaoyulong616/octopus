"""数据字典迁移：为 db_column、db_index、db_constraint 补充 create_time / update_time。"""
from sqlalchemy import text, inspect

from server.database import get_engine


MIGRATIONS = {
    "db_column": ["create_time", "update_time"],
    "db_index": ["create_time", "update_time"],
    "db_constraint": ["create_time", "update_time"],
}


def _dialect(engine) -> str:
    return engine.dialect.name  # "sqlite" or "mysql"


def _add_column_sql(table: str, col: str, dialect: str) -> str:
    if dialect == "sqlite":
        return f"ALTER TABLE {table} ADD COLUMN {col} DATETIME"
    now = "CURRENT_TIMESTAMP(3)"
    if col == "create_time":
        return f"ALTER TABLE {table} ADD COLUMN {col} DATETIME(3) DEFAULT {now} NOT NULL"
    return f"ALTER TABLE {table} ADD COLUMN {col} DATETIME(3) DEFAULT {now} ON UPDATE {now} NOT NULL"


def migrate():
    engine = get_engine()
    dialect = _dialect(engine)
    print(f"数据库: {dialect}")

    with engine.connect() as conn:
        for table, cols in MIGRATIONS.items():
            existing = {c["name"] for c in inspect(engine).get_columns(table)}
            needed = []
            for col in cols:
                if col in existing:
                    print(f"  ✓ {table}.{col} 已存在")
                else:
                    needed.append(col)

            if not needed:
                # 已有字段但要检查 NULL 值
                if dialect != "sqlite":
                    for col in cols:
                        r = conn.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {col} IS NULL"))
                        null_count = r.scalar()
                        if null_count:
                            conn.execute(
                                text(f"UPDATE {table} SET {col} = CURRENT_TIMESTAMP(3) WHERE {col} IS NULL")
                            )
                            print(f"    → 回填 {table}.{col} ({null_count} 行)")
                continue

            print(f"  → {table}: 添加 {needed} ...")
            for col in needed:
                sql = _add_column_sql(table, col, dialect)
                conn.execute(text(sql))
                print(f"    ✓ {col}")

            # 回填
            now_expr = "datetime('now','localtime')" if dialect == "sqlite" else "CURRENT_TIMESTAMP(3)"
            for col in needed:
                conn.execute(text(f"UPDATE {table} SET {col} = {now_expr}"))
            print(f"    ✓ 回填完成")

        conn.commit()
    print("迁移完成。")


if __name__ == "__main__":
    migrate()
