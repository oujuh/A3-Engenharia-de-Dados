# A3 — Engenharia de Dados: Refatoração Dimensional, Governança de Dados e Persistência Colunar

**Autora:** Julia Cristina Ferreira Silva

Universidade Anhembi Morumbi · UC Engenharia de Dados · Prof. Roberto Jubran Junior

📄 **Relatório técnico:** [relatorio/A3_Engenharia_Dados_JuliaCristinaFerreiraSilva.pdf](relatorio/A3_Engenharia_Dados_JuliaCristinaFerreiraSilva.pdf)

Pipeline que migra o e-commerce transacional da **Olist** (3FN) para um **Star Schema** (Kimball),
aplica barreiras automatizadas de **Data Quality** com **quarentena** auditável e persiste a camada
analítica em **Apache Parquet (Snappy) particionado por ano/mês**, com benchmark empírico contra o
modelo relacional e a varredura de CSV.

## Estrutura

```
dados_brutos/                 CSVs originais da Olist (Brazilian E-Commerce Public Dataset)
sql/
  ddl_oltp_3fn.sql            DDL do modelo transacional de origem (carregado em SQLite)
  consultas_benchmark.sql     As 3 consultas de negócio nas 3 abordagens (REL / CSV / PQT)
src/
  pipeline_etl.py             Módulos A, B e C: staging, regras de DQ, Star Schema, Parquet
  testes_qualidade.py         Teste de injeção de falhas: prova que cada regra de DQ funciona
  benchmark.py                Benchmark de tempo, disco e RAM
  gerar_relatorio.py          Gera figuras e o relatório técnico em PDF
saida/                        (gerado)
  dw/                         fato_vendas.parquet + dim_tempo/cliente/produto/vendedor/pagamento.parquet
  vendas_particionadas/       ano=YYYY/mes=MM/vendas-0.parquet  (visão analítica consolidada)
  quarentena_falhas.parquet   Registros rejeitados com regra, dimensão, motivo e snapshot JSON
  oltp_3fn.sqlite             Modelo 3FN de origem (fonte relacional do benchmark)
  metricas_qualidade.json     Volumetria aceitos x quarentenados por regra
  teste_injecao_falhas.json   Resultado do teste de injeção de falhas
  benchmark.json              Tempos, espaço em disco, RAM e plano de execução
relatorio/
  A3_Engenharia_Dados_JuliaCristinaFerreiraSilva.pdf   Relatório técnico final
  figuras/                    Diagramas 3FN e Star Schema, gráficos do benchmark
```

## Como executar

Requisitos: Python 3.10+.

```bash
pip install -r requirements.txt
```

Se `dados_brutos/` estiver vazio, baixe os CSVs do Kaggle
(<https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce>) e extraia nessa pasta.

```bash
python src/pipeline_etl.py
python src/testes_qualidade.py
python src/benchmark.py
python src/gerar_relatorio.py --aluno1 "Julia Cristina Ferreira Silva"
```

Tempo total aproximado: 1 a 2 minutos.

## Decisões de modelagem (resumo)

- **Grão da fato:** 1 item de pedido faturado e entregue (`order_id`, `order_item_id`).
  Pedidos não entregues ficam fora do escopo (sem prazo real) e são contados à parte.
- **Fato `fato_vendas`:** `valor_item`, `valor_frete`, `valor_bruto`, `prazo_entrega_dias_uteis`,
  `prazo_estimado_dias_uteis`, `dias_uteis_atraso`, `qtd_entregas_atrasadas`, `qtd_itens`.
- **Surrogate keys:** inteiros autoincrementais, atribuídos em ordem da chave natural
  (determinísticos); `dim_tempo` usa a SK inteligente `AAAAMMDD`.
- **Dimensão tempo:** calendário contínuo com ano, semestre, trimestre, mês, dia da semana,
  fim de semana, feriados nacionais (biblioteca `holidays`) e dia útil.
- **Dias úteis:** `numpy.busday_count` excluindo sábados, domingos e feriados nacionais.

## Regras de qualidade (Módulo B)

| Dimensão | Regras |
|---|---|
| Completude | COMP-01 compra nula · COMP-02 entregue sem data de entrega · COMP-03 preço/frete nulo; categoria nula imputada como `sem_categoria`; medidas nulas mantidas como `Float64` nullable |
| Validade/Conformidade | VAL-01 tipos mistos · VAL-02 preço <= 0 · VAL-03 frete < 0 · VAL-04 entrega antes da compra · VAL-05 peso nulo/<= 0 · VAL-06 UF inválida |
| Consistência/Integridade | INT-01 item órfão · INT-02 produto inexistente · INT-03 vendedor inexistente · INT-04 cliente inexistente |
| Unicidade | UNI-01 chave do grão duplicada |

Registros reprovados vão para `saida/quarentena_falhas.parquet` (uma linha por violação). Um
`assert` garante a conservação: aceitos + quarentenados + fora de escopo = total de origem.
`testes_qualidade.py` injeta registros corrompidos e verifica que 100% são capturados.

## Benchmark (Módulo C)

| Abordagem | Motor | Como lê |
|---|---|---|
| Relacional 3FN | SQLite (row-store, PK/FK indexadas) | JOINs entre 3 e 4 tabelas |
| CSV | DuckDB `read_csv` | Varredura integral dos CSVs + JOINs |
| Parquet | DuckDB `read_parquet(hive_partitioning)` | Partition pruning + predicate pushdown + projeção |

Cada consulta roda 1 vez de aquecimento e 7 vezes medidas; reporto a mediana.
