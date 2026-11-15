"""
Módulo C.3 - Benchmark empírico de I/O

Compara, para 3 consultas analíticas de negócio:
  REL - modelo relacional normalizado 3FN (SQLite, row-store, múltiplos JOINs)
  CSV - varredura integral dos CSVs brutos (DuckDB read_csv + JOINs)
  PQT - Parquet/Snappy particionado ano=/mes= (DuckDB, partition pruning,
        predicate pushdown e projeção de colunas)

Mede: tempo (mediana de N execuções após 1 aquecimento), espaço em disco,
arquivos efetivamente lidos e memória RAM materializada (pandas vs pyarrow).

Uso:
    python src/benchmark.py            (requer ter rodado pipeline_etl.py)
"""
import json
import platform
import re
import sqlite3
import statistics
import time
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow.dataset as ds

RAIZ = Path(__file__).resolve().parents[1]
DIR_BRUTO = RAIZ / "dados_brutos"
DIR_SAIDA = RAIZ / "saida"
DIR_PART = DIR_SAIDA / "vendas_particionadas"
ARQ_SQLITE = DIR_SAIDA / "oltp_3fn.sqlite"
REPETICOES = 7

NOMES_Q = {
    "Q1": "Top 10 categorias por receita bruta (2018)",
    "Q2": "Prazo médio de entrega por UF (1º tri/2018)",
    "Q3": "Black Friday nov/2017: receita por pagamento x região",
}
FILTRO_PART = {"Q1": lambda a, m: a == 2018,
               "Q2": lambda a, m: a == 2018 and m in (1, 2, 3),
               "Q3": lambda a, m: a == 2017 and m == 11}


def carregar_consultas() -> dict[str, str]:
    texto = (RAIZ / "sql" / "consultas_benchmark.sql").read_text(encoding="utf-8")
    blocos = re.split(r"^-- @(\w+)\s*$", texto, flags=re.M)
    sql = {}
    for nome, corpo in zip(blocos[1::2], blocos[2::2]):
        corpo = re.split(r"^-- -{10,}", corpo, flags=re.M)[0].strip()
        sql[nome] = (corpo.replace("{csv_dir}", DIR_BRUTO.as_posix())
                          .replace("{pqt_glob}", (DIR_PART / "*" / "*" / "*.parquet").as_posix()))
    return sql


def mb(caminho: Path | list[Path]) -> float:
    arquivos = caminho if isinstance(caminho, list) else (
        [p for p in caminho.rglob("*") if p.is_file()] if caminho.is_dir() else [caminho])
    return round(sum(p.stat().st_size for p in arquivos) / 1024 ** 2, 2)


def cronometrar(executar) -> tuple[list[float], object]:
    resultado = executar()  # aquecimento (cache de SO equalizado entre abordagens)
    tempos = []
    for _ in range(REPETICOES):
        t0 = time.perf_counter()
        resultado = executar()
        tempos.append((time.perf_counter() - t0) * 1000)
    return tempos, resultado


def rodar_sqlite(sql):
    def f():
        con = sqlite3.connect(ARQ_SQLITE)
        r = con.execute(sql).fetchall()
        con.close()
        return r
    return f


def rodar_duckdb(sql):
    def f():
        con = duckdb.connect()  # conexão nova: sem reaproveitar estado entre execuções
        r = con.execute(sql).fetchall()
        con.close()
        return r
    return f


def arquivos_particao(q):
    todos = sorted(DIR_PART.rglob("*.parquet"))
    lidos = []
    for p in todos:
        a = int(p.parent.parent.name.split("=")[1])
        m = int(p.parent.name.split("=")[1])
        if FILTRO_PART[q](a, m):
            lidos.append(p)
    return todos, lidos


def medir_ram():
    """RAM materializada para responder Q3 em dataframe:
    (a) carregar CSVs brutos inteiros em pandas (o que um JOIN em memória exige);
    (b) ler do Parquet apenas as colunas e partições necessárias (pyarrow)."""
    arqs = ["olist_order_items_dataset.csv", "olist_orders_dataset.csv",
            "olist_customers_dataset.csv", "olist_order_payments_dataset.csv"]
    ram_csv = sum(pd.read_csv(DIR_BRUTO / a).memory_usage(deep=True).sum() for a in arqs)
    dset = ds.dataset(DIR_PART, format="parquet", partitioning="hive")
    tab = dset.to_table(columns=["tipo_pagamento", "regiao_cliente", "valor_bruto"],
                        filter=(ds.field("ano") == 2017) & (ds.field("mes") == 11))
    tab_full = dset.to_table()
    return {"csv_pandas_mb": round(ram_csv / 1024 ** 2, 2),
            "parquet_visao_completa_mb": round(tab_full.nbytes / 1024 ** 2, 2),
            "parquet_seletivo_mb": round(tab.nbytes / 1024 ** 2, 3),
            "linhas_parquet_seletivo": tab.num_rows}


def plano_pushdown(sql):
    con = duckdb.connect()
    plano = con.execute("EXPLAIN " + sql).fetchall()
    con.close()
    return "\n".join(r[1] for r in plano)


def main():
    sql = carregar_consultas()
    csvs_usados = {
        "Q1": ["olist_order_items_dataset.csv", "olist_orders_dataset.csv", "olist_products_dataset.csv",
               "product_category_name_translation.csv"],
        "Q2": ["olist_order_items_dataset.csv", "olist_orders_dataset.csv", "olist_customers_dataset.csv"],
        "Q3": ["olist_order_items_dataset.csv", "olist_orders_dataset.csv", "olist_customers_dataset.csv",
               "olist_order_payments_dataset.csv"],
    }
    resultados = []
    for q in ["Q1", "Q2", "Q3"]:
        todos, lidos = arquivos_particao(q)
        for abord, fn in [("REL", rodar_sqlite), ("CSV", rodar_duckdb), ("PQT", rodar_duckdb)]:
            tempos, res = cronometrar(fn(sql[f"{q}_{abord}"]))
            if abord == "REL":
                dados_mb = mb(ARQ_SQLITE)
                arquivos = "1 banco (8 tabelas + índices)"
            elif abord == "CSV":
                dados_mb = mb([DIR_BRUTO / a for a in csvs_usados[q]])
                arquivos = f"{len(csvs_usados[q])} CSVs integrais"
            else:
                dados_mb = mb(lidos)
                arquivos = f"{len(lidos)} de {len(todos)} arquivos Parquet"
            resultados.append({
                "consulta": q, "descricao": NOMES_Q[q], "abordagem": abord,
                "mediana_ms": round(statistics.median(tempos), 1),
                "min_ms": round(min(tempos), 1), "max_ms": round(max(tempos), 1),
                "tempos_ms": [round(t, 1) for t in tempos],
                "mb_lidos_disco": dados_mb, "arquivos": arquivos,
                "linhas_resultado": len(res), "primeira_linha": [str(x) for x in res[0]],
            })
            print(f"{q} {abord}: mediana {statistics.median(tempos):8.1f} ms | {arquivos} | 1a linha {res[0]}")

    disco = {
        "CSV brutos OLTP (8 arquivos)": mb(DIR_BRUTO),
        "SQLite 3FN (com índices)": mb(ARQ_SQLITE),
        "Visão consolidada em CSV": mb(DIR_SAIDA / "visao_consolidada.csv"),
        "Visão consolidada Parquet particionado (Snappy)": mb(DIR_PART),
        "Star Schema Parquet (fato + 5 dimensões)": mb(DIR_SAIDA / "dw"),
    }
    ram = medir_ram()
    saida = {
        "ambiente": {"python": platform.python_version(), "duckdb": duckdb.__version__,
                     "sqlite": sqlite3.sqlite_version, "pandas": pd.__version__,
                     "so": platform.platform(), "processador": platform.processor(),
                     "repeticoes": REPETICOES},
        "consultas": resultados, "disco_mb": disco, "ram": ram,
        "plano_q3_parquet": plano_pushdown(sql["Q3_PQT"]),
    }
    (DIR_SAIDA / "benchmark.json").write_text(json.dumps(saida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(disco, indent=2, ensure_ascii=False))
    print(json.dumps(ram, indent=2))


if __name__ == "__main__":
    main()
