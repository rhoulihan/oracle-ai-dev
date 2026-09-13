import sys
from pathlib import Path

# The same logical schema in four dialects.
ORACLE = """
CREATE TABLE customer ( customer_id NUMBER PRIMARY KEY, name VARCHAR2(100) );
CREATE TABLE orders (
  order_id NUMBER PRIMARY KEY,
  customer_id NUMBER,
  total NUMBER(10,2),
  CONSTRAINT fk_c FOREIGN KEY (customer_id) REFERENCES customer (customer_id)
);
"""
POSTGRES = """
CREATE TABLE "customer" ( "customer_id" INTEGER PRIMARY KEY, "name" VARCHAR(100) );
CREATE TABLE "orders" (
  "order_id" SERIAL PRIMARY KEY,
  "customer_id" INTEGER REFERENCES "customer" ("customer_id"),
  "total" NUMERIC(10,2)
);
"""
MYSQL = """
CREATE TABLE `customer` ( `customer_id` INT PRIMARY KEY, `name` VARCHAR(100) );
CREATE TABLE `orders` (
  `order_id` INT AUTO_INCREMENT PRIMARY KEY,
  `customer_id` INT,
  `total` DECIMAL(10,2),
  FOREIGN KEY (`customer_id`) REFERENCES `customer` (`customer_id`)
);
"""
SQLSERVER = """
CREATE TABLE [customer] ( [customer_id] INT PRIMARY KEY, [name] NVARCHAR(100) );
CREATE TABLE [orders] (
  [order_id] INT IDENTITY(1,1) PRIMARY KEY,
  [customer_id] INT FOREIGN KEY REFERENCES [customer]([customer_id]),
  [total] DECIMAL(10,2)
);
"""


def _ddl(repo_root, sql):
    sys.path.insert(0, str(repo_root))
    import tooling.generate.ingest as ing
    return ing.model_from_ddl(sql)


def _check_model(model):
    ents = model["entities"]
    assert "customer" in ents and "orders" in ents
    assert ents["customer"]["pk"] == "customer_id"
    assert ents["orders"]["pk"] == "order_id"
    assert "total" in ents["orders"]["columns"]
    rels = model["relationships"]
    assert any(r["from"] == "orders" and r["to"] == "customer" for r in rels) or \
           any(r["to"] == "orders" and r["from"] == "customer" for r in rels)


def test_oracle_ddl(repo_root: Path):
    model, _ = _ddl(repo_root, ORACLE)
    _check_model(model)


def test_postgres_ddl(repo_root: Path):
    model, _ = _ddl(repo_root, POSTGRES)
    _check_model(model)


def test_mysql_ddl(repo_root: Path):
    model, _ = _ddl(repo_root, MYSQL)
    _check_model(model)


def test_sqlserver_ddl(repo_root: Path):
    model, _ = _ddl(repo_root, SQLSERVER)
    _check_model(model)


def test_ddl_output_validates(repo_root: Path):
    from tooling.generate.model import validate_model
    model, _ = _ddl(repo_root, ORACLE)
    assert validate_model(model) == []
