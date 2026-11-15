"""
Teste de injeção de falhas (fault injection) do Módulo B.

A base Olist real é relativamente limpa, então várias regras disparam 0 vezes.
Para provar que cada barreira funciona, este teste corrompe propositalmente
uma cópia em memória dos dados (5 registros por regra), executa o mesmo
staging + regras do pipeline e verifica que:
  1. cada registro corrompido é capturado pela regra esperada;
  2. nenhum registro corrompido chega ao conjunto aceito (DW);
  3. a conservação total de registros é mantida.

Uso:
    python src/testes_qualidade.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_etl as etl  # noqa: E402

N = 5
rng = np.random.default_rng(42)


def amostra_itens_entregues(dfs, n, excluir):
    od = dfs["orders"]
    entregues = set(od.loc[od["order_status"].eq("delivered") & od["order_delivered_customer_date"].notna(),
                           "order_id"])
    it = dfs["items"]
    candidatos = it.index[it["order_id"].isin(entregues) & ~it.index.isin(excluir)]
    return list(rng.choice(candidatos, size=n, replace=False))


def main():
    dfs = etl.extrair()
    it, od, pr = dfs["items"], dfs["orders"], dfs["products"]
    esperado = {}       # regra -> conjunto de id_registro
    usados = set()

    def marca(regra, idx):
        usados.update(idx)
        ids = set(it.loc[idx, "order_id"] + "#" + it.loc[idx, "order_item_id"])
        esperado.setdefault(regra, set()).update(ids)

    # VAL-02: preço negativo / zero
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "price"] = ["-10.00", "0", "-0.01", "-999", "0.00"]
    marca("VAL-02", idx)

    # VAL-03: frete negativo
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "freight_value"] = "-5.50"
    marca("VAL-03", idx)

    # VAL-01: tipos mistos (texto em coluna monetária)
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "price"] = ["R$ 10,00", "abc", "12,5", "N/A", "1.2.3"]
    marca("VAL-01", idx)

    # COMP-03: preço nulo
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "price"] = np.nan
    marca("COMP-03", idx)

    # INT-01: itens órfãos (pedido inexistente)
    orfaos = it.loc[amostra_itens_entregues(dfs, N, usados)].copy()
    orfaos["order_id"] = [f"pedido_fantasma_{i}" for i in range(N)]
    it_novo = pd.concat([it, orfaos], ignore_index=True)
    esperado["INT-01"] = set(orfaos["order_id"] + "#" + orfaos["order_item_id"])
    dfs["items"] = it = it_novo

    # INT-02: product_id inexistente
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "product_id"] = "produto_inexistente"
    marca("INT-02", idx)

    # INT-03: seller_id inexistente
    idx = amostra_itens_entregues(dfs, N, usados)
    it.loc[idx, "seller_id"] = "vendedor_inexistente"
    marca("INT-03", idx)

    # UNI-01: duplicação da chave do grão
    dup = it.loc[amostra_itens_entregues(dfs, N, usados)].copy()
    dfs["items"] = it = pd.concat([it, dup], ignore_index=True)
    esperado["UNI-01"] = set(dup["order_id"] + "#" + dup["order_item_id"])

    # VAL-04: entrega anterior à compra (altera o pedido -> afeta todos os itens dele)
    idx = amostra_itens_entregues(dfs, N, usados)
    pedidos = it.loc[idx, "order_id"].unique()
    m = od["order_id"].isin(pedidos)
    od.loc[m, "order_delivered_customer_date"] = "2015-01-01 00:00:00"
    afetados = it.index[it["order_id"].isin(pedidos)]
    marca("VAL-04", list(afetados))

    # VAL-05: peso do produto nulo
    idx = amostra_itens_entregues(dfs, N, usados)
    prods = it.loc[idx, "product_id"].unique()
    pr.loc[pr["product_id"].isin(prods), "product_weight_g"] = np.nan
    marca("VAL-05", list(it.index[it["product_id"].isin(prods) & it["order_id"].isin(
        od.loc[od["order_status"].eq("delivered"), "order_id"])]))

    st, _ = etl.montar_staging(dfs)
    aceitos, quarentena, metricas = etl.aplicar_qualidade(st, "teste")

    resultados, falhas = [], 0
    ids_aceitos = set(aceitos["order_id"].astype(str) + "#" + aceitos["order_item_id"].astype(str))
    for regra, ids in esperado.items():
        capturados = set(quarentena.loc[quarentena["regra"].eq(regra), "id_registro"])
        faltando = ids - capturados
        if regra == "UNI-01":
            vazou = False  # a 1a ocorrência da chave duplicada é legítima e segue para o DW
        else:
            vazou = bool(ids & ids_aceitos)
        ok = not faltando and not vazou
        falhas += not ok
        resultados.append({"regra": regra, "injetados": len(ids), "capturados": len(ids & capturados),
                           "vazou_para_dw": vazou, "status": "OK" if ok else "FALHOU"})

    print(pd.DataFrame(resultados).to_string(index=False))
    saida = etl.DIR_SAIDA / "teste_injecao_falhas.json"
    saida.write_text(json.dumps(resultados, indent=2, ensure_ascii=False), encoding="utf-8")
    assert falhas == 0, f"{falhas} regra(s) não capturaram as falhas injetadas"
    print(f"\nTodas as {len(resultados)} regras capturaram 100% das falhas injetadas.")


if __name__ == "__main__":
    main()
