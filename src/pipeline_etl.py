"""
Avaliação A3 - Engenharia de Dados
Pipeline ETL: OLTP (3FN, CSVs da Olist) -> Data Warehouse Star Schema (Kimball)
com barreiras de Data Quality, quarentena e persistência colunar em Parquet.

Módulo A - Modelagem dimensional (grão, fato, surrogate keys, dimensão tempo)
Módulo B - Qualidade de dados como código (completude, validade, integridade,
           unicidade + quarentena auditável)
Módulo C - Persistência em Parquet/Snappy com particionamento ano=/mes=

Uso:
    python src/pipeline_etl.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import holidays
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parents[1]
DIR_BRUTO = RAIZ / "dados_brutos"
DIR_SAIDA = RAIZ / "saida"
DIR_DW = DIR_SAIDA / "dw"
DIR_PART = DIR_SAIDA / "vendas_particionadas"
ARQ_QUARENTENA = DIR_SAIDA / "quarentena_falhas.parquet"
ARQ_SQLITE = DIR_SAIDA / "oltp_3fn.sqlite"
ARQ_METRICAS = DIR_SAIDA / "metricas_qualidade.json"

ARQUIVOS = {
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

UF_REGIAO = {
    "AC": "Norte", "AP": "Norte", "AM": "Norte", "PA": "Norte", "RO": "Norte", "RR": "Norte", "TO": "Norte",
    "AL": "Nordeste", "BA": "Nordeste", "CE": "Nordeste", "MA": "Nordeste", "PB": "Nordeste",
    "PE": "Nordeste", "PI": "Nordeste", "RN": "Nordeste", "SE": "Nordeste",
    "DF": "Centro-Oeste", "GO": "Centro-Oeste", "MT": "Centro-Oeste", "MS": "Centro-Oeste",
    "ES": "Sudeste", "MG": "Sudeste", "RJ": "Sudeste", "SP": "Sudeste",
    "PR": "Sul", "RS": "Sul", "SC": "Sul",
}
NOMES_MES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
             "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
NOMES_DIA = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

# Status considerados no escopo da fato: item faturado E entregue (permite medir prazo real)
STATUS_ESCOPO = {"delivered"}


# ---------------------------------------------------------------------------
# Extração
# ---------------------------------------------------------------------------
def extrair(dir_bruto: Path = DIR_BRUTO) -> dict[str, pd.DataFrame]:
    """Lê todos os CSVs como texto (dtype=str) para que tipos mistos sejam
    detectados explicitamente pela camada de qualidade, e não silenciosamente
    convertidos pelo parser."""
    dfs = {}
    for nome, arq in ARQUIVOS.items():
        df = pd.read_csv(dir_bruto / arq, dtype=str, encoding="utf-8-sig")
        df = df.loc[:, ~df.columns.str.startswith("Unnamed")]  # colunas vazias extras
        dfs[nome] = df
    return dfs


def _num(serie: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Converte para Float64 (nullable). Retorna (valores, máscara de tipo inválido):
    valor não nulo na origem que não pôde ser convertido = tipo misto."""
    convertido = pd.to_numeric(serie.str.strip(), errors="coerce").astype("Float64")
    tipo_invalido = serie.notna() & serie.str.strip().ne("") & convertido.isna()
    return convertido, tipo_invalido


def _ts(serie: pd.Series) -> tuple[pd.Series, pd.Series]:
    convertido = pd.to_datetime(serie, errors="coerce", format="%Y-%m-%d %H:%M:%S")
    tipo_invalido = serie.notna() & serie.str.strip().ne("") & convertido.isna()
    return convertido, tipo_invalido


# ---------------------------------------------------------------------------
# Staging: tipagem + junção no grão item de pedido
# ---------------------------------------------------------------------------
def montar_staging(dfs: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict]:
    tratamentos: dict[str, int] = {}

    # --- itens (grão) ---
    it = dfs["items"].copy()
    it["order_item_id_num"], it["tipo_inv_item_id"] = _num(it["order_item_id"])
    it["price"], it["tipo_inv_price"] = _num(it["price"])
    it["freight_value"], it["tipo_inv_freight"] = _num(it["freight_value"])

    # --- pedidos ---
    od = dfs["orders"].copy()
    tipo_inv_ts = pd.Series(False, index=od.index)
    for c in ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
              "order_delivered_customer_date", "order_estimated_delivery_date"]:
        od[c], inv = _ts(od[c])
        tipo_inv_ts |= inv
    od["tipo_inv_ts"] = tipo_inv_ts
    od["pedido_existe"] = True

    # --- produtos (tratamento de completude: categoria nula -> 'sem_categoria') ---
    pr = dfs["products"].copy()
    tr = dfs["category_translation"]
    tratamentos["produtos_categoria_nula_imputada"] = int(pr["product_category_name"].isna().sum())
    pr["product_category_name"] = pr["product_category_name"].fillna("sem_categoria")
    pr = pr.merge(tr, on="product_category_name", how="left")
    nao_catalogada = pr["product_category_name_english"].isna() & pr["product_category_name"].ne("sem_categoria")
    tratamentos["produtos_categoria_nao_catalogada"] = int(nao_catalogada.sum())
    pr.loc[nao_catalogada, "product_category_name_english"] = "uncataloged"
    pr.loc[pr["product_category_name"].eq("sem_categoria"), "product_category_name_english"] = "no_category"
    tipo_inv_prod = pd.Series(False, index=pr.index)
    for c in ["product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm",
              "product_photos_qty"]:
        pr[c], inv = _num(pr[c])
        tipo_inv_prod |= inv
    tratamentos["produtos_dimensoes_nulas_mantidas_float_nullable"] = int(
        pr[["product_length_cm", "product_height_cm", "product_width_cm"]].isna().any(axis=1).sum())
    pr["tipo_inv_prod"] = tipo_inv_prod
    pr["produto_existe"] = True

    # --- vendedores e clientes ---
    se = dfs["sellers"].copy()
    se["vendedor_existe"] = True
    cu = dfs["customers"].copy()
    cu["cliente_existe"] = True

    # --- pagamentos: tipo principal (maior valor) + parcelas máx. por pedido ---
    pg = dfs["payments"].copy()
    pg["payment_value"], _ = _num(pg["payment_value"])
    pg["payment_installments"], _ = _num(pg["payment_installments"])
    pg = pg.sort_values(["order_id", "payment_value"], ascending=[True, False])
    pg_agg = (pg.groupby("order_id", as_index=False)
                .agg(tipo_pagamento=("payment_type", "first"),
                     parcelas=("payment_installments", "max")))

    # --- junção no grão (LEFT a partir de itens para expor órfãos) ---
    st = (it.merge(od, on="order_id", how="left")
            .merge(cu, on="customer_id", how="left")
            .merge(pr, on="product_id", how="left")
            .merge(se, on="seller_id", how="left")
            .merge(pg_agg, on="order_id", how="left"))
    for c in ["pedido_existe", "produto_existe", "vendedor_existe", "cliente_existe",
              "tipo_inv_ts", "tipo_inv_prod"]:
        st[c] = st[c].fillna(False).astype(bool)

    tratamentos["itens_sem_pagamento_imputado_nao_informado"] = int(st["tipo_pagamento"].isna().sum())
    st["tipo_pagamento"] = st["tipo_pagamento"].fillna("nao_informado")
    st["parcelas"] = st["parcelas"].fillna(0)
    return st, tratamentos


# ---------------------------------------------------------------------------
# Módulo B - Regras de qualidade (cada regra = máscara booleana de violação)
# ---------------------------------------------------------------------------
REGRAS = [
    # (id, dimensão, descrição, função(st) -> máscara de violação)
    ("COMP-01", "Completude", "Data/hora da compra nula",
     lambda s: s["order_purchase_timestamp"].isna() & s["pedido_existe"]),
    ("COMP-02", "Completude", "Pedido entregue sem data de entrega ao cliente",
     lambda s: s["order_delivered_customer_date"].isna() & s["pedido_existe"]),
    ("COMP-03", "Completude", "Preço ou frete nulo",
     lambda s: s["price"].isna() | s["freight_value"].isna()),
    ("VAL-01", "Validade/Conformidade", "Tipo misto: valor não numérico/não-data na origem",
     lambda s: s["tipo_inv_price"] | s["tipo_inv_freight"] | s["tipo_inv_item_id"]
               | s["tipo_inv_ts"] | s["tipo_inv_prod"]),
    ("VAL-02", "Validade/Conformidade", "Preço do item <= 0",
     lambda s: (s["price"] <= 0).fillna(False)),
    ("VAL-03", "Validade/Conformidade", "Valor de frete negativo",
     lambda s: (s["freight_value"] < 0).fillna(False)),
    ("VAL-04", "Validade/Conformidade", "Data de entrega anterior à data da compra",
     lambda s: (s["order_delivered_customer_date"] < s["order_purchase_timestamp"]).fillna(False)),
    ("VAL-05", "Validade/Conformidade", "Peso do produto nulo ou <= 0",
     lambda s: s["produto_existe"] & ~(s["product_weight_g"] > 0).fillna(False)),
    ("VAL-06", "Validade/Conformidade", "UF do cliente fora do domínio das 27 UFs",
     lambda s: s["cliente_existe"] & ~s["customer_state"].isin(UF_REGIAO.keys())),
    ("INT-01", "Consistência/Integridade", "Item órfão: order_id inexistente em pedidos",
     lambda s: ~s["pedido_existe"]),
    ("INT-02", "Consistência/Integridade", "product_id inexistente em produtos",
     lambda s: ~s["produto_existe"]),
    ("INT-03", "Consistência/Integridade", "seller_id inexistente em vendedores",
     lambda s: ~s["vendedor_existe"]),
    ("INT-04", "Consistência/Integridade", "customer_id do pedido inexistente em clientes",
     lambda s: s["pedido_existe"] & ~s["cliente_existe"]),
    ("UNI-01", "Unicidade", "Chave (order_id, order_item_id) duplicada",
     lambda s: s.duplicated(["order_id", "order_item_id"], keep="first")),
]


def aplicar_qualidade(st: pd.DataFrame, momento: str):
    """Separa (1) fora de escopo, (2) quarentena, (3) aceitos.
    Retorna (aceitos, quarentena, métricas)."""
    st = st.reset_index(drop=True)
    st["id_registro"] = st["order_id"].astype(str) + "#" + st["order_item_id"].astype(str)

    # Escopo do grão: item de pedido faturado e entregue. Itens de pedidos
    # cancelados/em trânsito são válidos no OLTP, mas não pertencem a esta fato.
    fora_escopo = st["pedido_existe"] & ~st["order_status"].isin(STATUS_ESCOPO)
    em_escopo = st[~fora_escopo].copy()

    violacoes = []
    contagem_regras = []
    mascara_total = pd.Series(False, index=em_escopo.index)
    for rid, dim, desc, fn in REGRAS:
        m = fn(em_escopo).astype(bool)
        mascara_total |= m
        contagem_regras.append({"regra": rid, "dimensao": dim, "descricao": desc,
                                "violacoes": int(m.sum())})
        if m.any():
            v = em_escopo.loc[m]
            violacoes.append(pd.DataFrame({
                "id_registro": v["id_registro"],
                "tabela_origem": "olist_order_items_dataset",
                "order_id": v["order_id"],
                "order_item_id": v["order_item_id"],
                "regra": rid,
                "dimensao_qualidade": dim,
                "motivo": desc,
                "registro_original": v[["order_id", "order_item_id", "product_id", "seller_id", "price",
                                        "freight_value", "order_status", "order_purchase_timestamp",
                                        "order_delivered_customer_date", "product_weight_g",
                                        "customer_state"]]
                    .astype(str).to_dict(orient="records"),
                "timestamp_execucao": momento,
            }))
    quarentena = (pd.concat(violacoes, ignore_index=True) if violacoes else
                  pd.DataFrame(columns=["id_registro", "tabela_origem", "order_id", "order_item_id",
                                        "regra", "dimensao_qualidade", "motivo", "registro_original",
                                        "timestamp_execucao"]))
    if len(quarentena):
        quarentena["registro_original"] = quarentena["registro_original"].map(
            lambda d: json.dumps(d, ensure_ascii=False))

    aceitos = em_escopo[~mascara_total].copy()

    metricas = {
        "total_itens_origem": int(len(st)),
        "itens_fora_escopo_status": int(fora_escopo.sum()),
        "itens_em_escopo": int(len(em_escopo)),
        "itens_aceitos": int(len(aceitos)),
        "itens_quarentenados": int(mascara_total.sum()),
        "violacoes_registradas": int(len(quarentena)),
        "regras": contagem_regras,
    }
    # Asserção de conservação: nenhum registro some do pipeline sem rastro.
    assert metricas["itens_aceitos"] + metricas["itens_quarentenados"] + metricas["itens_fora_escopo_status"] \
        == metricas["total_itens_origem"], "Conservação de registros violada"
    return aceitos, quarentena, metricas


# ---------------------------------------------------------------------------
# Módulo A - Dimensões, surrogate keys e fato
# ---------------------------------------------------------------------------
def dias_uteis(inicio: pd.Series, fim: pd.Series, feriados: np.ndarray) -> np.ndarray:
    """Dias úteis entre duas datas (seg-sex, excluindo feriados nacionais)."""
    a = inicio.dt.normalize().values.astype("datetime64[D]")
    b = fim.dt.normalize().values.astype("datetime64[D]")
    return np.busday_count(a, b, holidays=feriados)


def construir_dim_tempo(data_min: pd.Timestamp, data_max: pd.Timestamp) -> tuple[pd.DataFrame, np.ndarray]:
    datas = pd.date_range(data_min.normalize(), data_max.normalize(), freq="D")
    fer = holidays.Brazil(years=range(datas.min().year, datas.max().year + 1))
    d = pd.DataFrame({"data": datas})
    d["sk_data"] = d["data"].dt.strftime("%Y%m%d").astype("int32")  # SK determinística
    d["ano"] = d["data"].dt.year.astype("int16")
    d["semestre"] = ((d["data"].dt.month - 1) // 6 + 1).astype("int8")
    d["trimestre"] = d["data"].dt.quarter.astype("int8")
    d["mes"] = d["data"].dt.month.astype("int8")
    d["nome_mes"] = d["mes"].map(lambda m: NOMES_MES[m - 1])
    d["ano_mes"] = d["data"].dt.strftime("%Y-%m")
    d["dia"] = d["data"].dt.day.astype("int8")
    d["dia_semana"] = (d["data"].dt.day_of_week + 1).astype("int8")  # 1=Seg ... 7=Dom
    d["nome_dia_semana"] = d["data"].dt.day_of_week.map(lambda x: NOMES_DIA[x])
    d["semana_ano"] = d["data"].dt.isocalendar().week.astype("int8")
    d["flag_fim_semana"] = d["dia_semana"].ge(6)
    d["flag_feriado"] = d["data"].dt.date.map(lambda x: x in fer)
    d["nome_feriado"] = d["data"].dt.date.map(lambda x: fer.get(x, None))
    d["flag_dia_util"] = ~d["flag_fim_semana"] & ~d["flag_feriado"]
    d["data"] = d["data"].dt.date
    cols = ["sk_data"] + [c for c in d.columns if c != "sk_data"]
    feriados = np.array(sorted(fer.keys()), dtype="datetime64[D]")
    return d[cols], feriados


def _sk(df: pd.DataFrame, chave: str, nome_sk: str) -> pd.DataFrame:
    """Surrogate key autoincremental, atribuída em ordem da chave natural
    (determinística entre execuções para a mesma carga)."""
    df = df.sort_values(chave).reset_index(drop=True)
    df.insert(0, nome_sk, np.arange(1, len(df) + 1, dtype="int32"))
    return df


def faixa_peso(g: pd.Series) -> pd.Series:
    return pd.cut(g.astype(float), bins=[0, 500, 2000, 10000, np.inf],
                  labels=["Leve (<=0,5kg)", "Médio (0,5-2kg)", "Pesado (2-10kg)", "Muito pesado (>10kg)"]
                  ).astype(str)


def construir_dw(aceitos: pd.DataFrame):
    a = aceitos.copy()

    dim_tempo, feriados = construir_dim_tempo(
        a["order_purchase_timestamp"].min(),
        max(a["order_delivered_customer_date"].max(), a["order_estimated_delivery_date"].max()))

    dim_cliente = _sk(
        a[["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city",
           "customer_state"]].drop_duplicates("customer_id"), "customer_id", "sk_cliente")
    dim_cliente["regiao"] = dim_cliente["customer_state"].map(UF_REGIAO)
    dim_cliente = dim_cliente.rename(columns={
        "customer_id": "nk_customer_id", "customer_unique_id": "id_cliente_unico",
        "customer_zip_code_prefix": "cep_prefixo", "customer_city": "cidade", "customer_state": "uf"})

    dim_produto = _sk(
        a[["product_id", "product_category_name", "product_category_name_english", "product_weight_g",
           "product_length_cm", "product_height_cm", "product_width_cm", "product_photos_qty"]]
        .drop_duplicates("product_id"), "product_id", "sk_produto")
    dim_produto["volume_cm3"] = (dim_produto["product_length_cm"] * dim_produto["product_height_cm"]
                                 * dim_produto["product_width_cm"])
    dim_produto["faixa_peso"] = faixa_peso(dim_produto["product_weight_g"])
    dim_produto = dim_produto.rename(columns={
        "product_id": "nk_product_id", "product_category_name": "categoria",
        "product_category_name_english": "categoria_en", "product_weight_g": "peso_g",
        "product_length_cm": "comprimento_cm", "product_height_cm": "altura_cm",
        "product_width_cm": "largura_cm", "product_photos_qty": "qtd_fotos"})

    dim_vendedor = _sk(a[["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]]
                       .drop_duplicates("seller_id"), "seller_id", "sk_vendedor")
    dim_vendedor["regiao"] = dim_vendedor["seller_state"].map(UF_REGIAO)
    dim_vendedor = dim_vendedor.rename(columns={
        "seller_id": "nk_seller_id", "seller_zip_code_prefix": "cep_prefixo",
        "seller_city": "cidade", "seller_state": "uf"})

    # Junk dimension de pagamento: combinações de baixa cardinalidade
    a["faixa_parcelas"] = pd.cut(a["parcelas"].astype(float), bins=[-1, 0, 1, 3, 6, np.inf],
                                 labels=["Não informado", "À vista (1x)", "2-3x", "4-6x", "7x ou mais"]
                                 ).astype(str)
    dim_pagamento = a[["tipo_pagamento", "faixa_parcelas"]].drop_duplicates()
    dim_pagamento = dim_pagamento.sort_values(["tipo_pagamento", "faixa_parcelas"]).reset_index(drop=True)
    dim_pagamento.insert(0, "sk_pagamento", np.arange(1, len(dim_pagamento) + 1, dtype="int32"))

    # --- Fato: substituição das chaves naturais pelas surrogate keys ---
    f = (a.merge(dim_cliente[["sk_cliente", "nk_customer_id"]], left_on="customer_id", right_on="nk_customer_id")
          .merge(dim_produto[["sk_produto", "nk_product_id"]], left_on="product_id", right_on="nk_product_id")
          .merge(dim_vendedor[["sk_vendedor", "nk_seller_id"]], left_on="seller_id", right_on="nk_seller_id")
          .merge(dim_pagamento, on=["tipo_pagamento", "faixa_parcelas"]))
    assert len(f) == len(a), "Perda de linhas na troca de NK por SK"

    fato = pd.DataFrame({
        "sk_data_compra": f["order_purchase_timestamp"].dt.strftime("%Y%m%d").astype("int32"),
        "sk_data_entrega": f["order_delivered_customer_date"].dt.strftime("%Y%m%d").astype("int32"),
        "sk_cliente": f["sk_cliente"],
        "sk_produto": f["sk_produto"],
        "sk_vendedor": f["sk_vendedor"],
        "sk_pagamento": f["sk_pagamento"],
        "dd_order_id": f["order_id"],                      # dimensão degenerada
        "dd_order_item_id": f["order_item_id_num"].astype("int16"),
        "qtd_itens": np.int16(1),
        "valor_item": f["price"].astype(float).round(2),
        "valor_frete": f["freight_value"].astype(float).round(2),
    })
    fato["valor_bruto"] = (fato["valor_item"] + fato["valor_frete"]).round(2)
    fato["prazo_entrega_dias_uteis"] = dias_uteis(f["order_purchase_timestamp"],
                                                  f["order_delivered_customer_date"], feriados).astype("int16")
    fato["prazo_estimado_dias_uteis"] = dias_uteis(f["order_purchase_timestamp"],
                                                   f["order_estimated_delivery_date"], feriados).astype("int16")
    fato["dias_uteis_atraso"] = np.maximum(fato["prazo_entrega_dias_uteis"] - fato["prazo_estimado_dias_uteis"],
                                           0).astype("int16")
    fato["qtd_entregas_atrasadas"] = (fato["dias_uteis_atraso"] > 0).astype("int16")
    fato = fato.sort_values(["sk_data_compra", "dd_order_id", "dd_order_item_id"]).reset_index(drop=True)
    fato.insert(0, "sk_venda", np.arange(1, len(fato) + 1, dtype="int32"))

    # --- Asserções pós-carga (integridade referencial do DW) ---
    assert fato["sk_data_compra"].isin(dim_tempo["sk_data"]).all()
    assert fato["sk_data_entrega"].isin(dim_tempo["sk_data"]).all()
    for col, dim, sk in [("sk_cliente", dim_cliente, "sk_cliente"), ("sk_produto", dim_produto, "sk_produto"),
                         ("sk_vendedor", dim_vendedor, "sk_vendedor"), ("sk_pagamento", dim_pagamento, "sk_pagamento")]:
        assert fato[col].isin(dim[sk]).all(), f"FK órfã em {col}"
        assert dim[sk].is_unique, f"SK duplicada em {sk}"
    assert (fato["valor_item"] > 0).all() and (fato["valor_frete"] >= 0).all()
    assert (fato["prazo_entrega_dias_uteis"] >= 0).all()
    assert not fato[["dd_order_id", "dd_order_item_id"]].duplicated().any(), "Grão violado"
    assert fato.notna().all().all(), "Fato com nulos"

    dims = {"dim_tempo": dim_tempo, "dim_cliente": dim_cliente, "dim_produto": dim_produto,
            "dim_vendedor": dim_vendedor, "dim_pagamento": dim_pagamento}
    return fato, dims


# ---------------------------------------------------------------------------
# Módulo C - Persistência colunar
# ---------------------------------------------------------------------------
def visao_consolidada(fato: pd.DataFrame, dims: dict) -> pd.DataFrame:
    """Visão analítica desnormalizada (fato + atributos das dimensões)."""
    t = dims["dim_tempo"]
    v = (fato
         .merge(t[["sk_data", "data", "ano", "trimestre", "mes", "nome_dia_semana", "flag_fim_semana",
                   "flag_feriado"]].rename(columns={"sk_data": "sk_data_compra", "data": "data_compra"}),
                on="sk_data_compra")
         .merge(dims["dim_cliente"][["sk_cliente", "cidade", "uf", "regiao"]]
                .rename(columns={"cidade": "cidade_cliente", "uf": "uf_cliente", "regiao": "regiao_cliente"}),
                on="sk_cliente")
         .merge(dims["dim_produto"][["sk_produto", "categoria", "categoria_en", "faixa_peso"]], on="sk_produto")
         .merge(dims["dim_vendedor"][["sk_vendedor", "uf", "regiao"]]
                .rename(columns={"uf": "uf_vendedor", "regiao": "regiao_vendedor"}), on="sk_vendedor")
         .merge(dims["dim_pagamento"][["sk_pagamento", "tipo_pagamento", "faixa_parcelas"]], on="sk_pagamento"))
    v["data_compra"] = pd.to_datetime(v["data_compra"])
    v["ano"] = v["ano"].astype("int16")
    v["mes"] = v["mes"].map(lambda m: f"{m:02d}")  # partição mes=MM
    return v


def persistir(fato, dims, quarentena, visao):
    if DIR_SAIDA.exists():
        for p in [DIR_DW, DIR_PART]:
            shutil.rmtree(p, ignore_errors=True)
    DIR_DW.mkdir(parents=True, exist_ok=True)

    for nome, df in {**dims, "fato_vendas": fato}.items():
        pq.write_table(pa.Table.from_pandas(df, preserve_index=False), DIR_DW / f"{nome}.parquet",
                       compression="snappy")

    pq.write_table(pa.Table.from_pandas(quarentena, preserve_index=False), ARQ_QUARENTENA,
                   compression="snappy")

    # Particionamento físico Hive: vendas_particionadas/ano=YYYY/mes=MM/*.parquet
    pq.write_to_dataset(pa.Table.from_pandas(visao, preserve_index=False), root_path=str(DIR_PART),
                        partition_cols=["ano", "mes"], compression="snappy",
                        basename_template="vendas-{i}.parquet", existing_data_behavior="delete_matching")

    # Mesma visão consolidada em CSV, para comparação justa de espaço em disco
    visao.to_csv(DIR_SAIDA / "visao_consolidada.csv", index=False)


def carregar_oltp_sqlite(dfs: dict[str, pd.DataFrame]):
    """Materializa o modelo transacional 3FN de origem em um SGBD relacional
    orientado a linhas (SQLite), com PKs/FKs indexadas, para o benchmark."""
    if ARQ_SQLITE.exists():
        ARQ_SQLITE.unlink()
    con = sqlite3.connect(ARQ_SQLITE)
    ddl = (RAIZ / "sql" / "ddl_oltp_3fn.sql").read_text(encoding="utf-8")
    con.executescript(ddl)
    for nome, df in dfs.items():
        tabela = {"category_translation": "product_category_name_translation"}.get(nome, nome)
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({tabela})")]
        df[cols].to_sql(tabela, con, if_exists="append", index=False, chunksize=20000)
    con.execute("ANALYZE")
    con.commit()
    con.close()


def main():
    t0 = time.perf_counter()
    momento = datetime.now().isoformat(timespec="seconds")
    DIR_SAIDA.mkdir(exist_ok=True)

    print("[1/6] Extraindo CSVs ...")
    dfs = extrair()
    print("[2/6] Carregando OLTP 3FN no SQLite (fonte relacional do benchmark) ...")
    carregar_oltp_sqlite(dfs)
    print("[3/6] Staging no grão item de pedido ...")
    st, tratamentos = montar_staging(dfs)
    print("[4/6] Aplicando regras de qualidade ...")
    aceitos, quarentena, metricas = aplicar_qualidade(st, momento)
    metricas["tratamentos_sem_rejeicao"] = tratamentos
    print("[5/6] Construindo Star Schema ...")
    fato, dims = construir_dw(aceitos)
    visao = visao_consolidada(fato, dims)
    print("[6/6] Persistindo Parquet (Snappy) particionado ...")
    persistir(fato, dims, quarentena, visao)

    metricas["linhas_dw"] = {k: int(len(v)) for k, v in {**dims, "fato_vendas": fato}.items()}
    metricas["valor_bruto_total_dw"] = round(float(fato["valor_bruto"].sum()), 2)
    metricas["tempo_execucao_s"] = round(time.perf_counter() - t0, 2)
    metricas["executado_em"] = momento
    ARQ_METRICAS.write_text(json.dumps(metricas, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps({k: v for k, v in metricas.items() if k != "regras"}, indent=2, ensure_ascii=False))
    for r in metricas["regras"]:
        print(f"  {r['regra']:<8} {r['dimensao']:<26} {r['violacoes']:>6}  {r['descricao']}")


if __name__ == "__main__":
    main()
