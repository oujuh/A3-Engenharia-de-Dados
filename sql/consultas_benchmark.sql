-- ============================================================================
-- Consultas analíticas de negócio usadas no benchmark (3 abordagens)
--   [REL]  Relacional normalizado 3FN (SQLite, row-store, múltiplos JOINs)
--   [CSV]  Varredura integral dos CSVs brutos (DuckDB read_csv, mesmos JOINs)
--   [PQT]  Parquet particionado ano=/mes= (DuckDB, predicate pushdown + projeção)
-- Os placeholders {csv_dir} e {pqt_glob} são substituídos por src/benchmark.py.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Q1. Top 10 categorias por receita bruta (item + frete) em 2018
-- ---------------------------------------------------------------------------
-- @Q1_REL
SELECT COALESCE(p.product_category_name, 'sem_categoria') AS categoria,
       COUNT(*)                                     AS itens,
       ROUND(SUM(i.price + i.freight_value), 2)     AS receita_bruta,
       ROUND(SUM(i.freight_value), 2)               AS frete
FROM items i
JOIN orders   o ON o.order_id   = i.order_id
JOIN products p ON p.product_id = i.product_id
LEFT JOIN product_category_name_translation t ON t.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered'
  AND strftime('%Y', o.order_purchase_timestamp) = '2018'
GROUP BY 1 ORDER BY receita_bruta DESC LIMIT 10;

-- @Q1_CSV
SELECT COALESCE(p.product_category_name, 'sem_categoria') AS categoria,
       COUNT(*) AS itens,
       ROUND(SUM(i.price + i.freight_value), 2) AS receita_bruta,
       ROUND(SUM(i.freight_value), 2) AS frete
FROM read_csv('{csv_dir}/olist_order_items_dataset.csv', header=true) i
JOIN read_csv('{csv_dir}/olist_orders_dataset.csv', header=true)      o ON o.order_id = i.order_id
JOIN read_csv('{csv_dir}/olist_products_dataset.csv', header=true)    p ON p.product_id = i.product_id
LEFT JOIN read_csv('{csv_dir}/product_category_name_translation.csv', header=true) t
       ON t.product_category_name = p.product_category_name
WHERE o.order_status = 'delivered' AND year(o.order_purchase_timestamp) = 2018
GROUP BY 1 ORDER BY receita_bruta DESC LIMIT 10;

-- @Q1_PQT
SELECT categoria, COUNT(*) AS itens,
       ROUND(SUM(valor_bruto), 2) AS receita_bruta, ROUND(SUM(valor_frete), 2) AS frete
FROM read_parquet('{pqt_glob}', hive_partitioning = true)
WHERE ano = 2018
GROUP BY 1 ORDER BY receita_bruta DESC LIMIT 10;

-- ---------------------------------------------------------------------------
-- Q2. Prazo médio de entrega por UF do cliente no 1º trimestre de 2018
--     (OLTP calcula dias corridos em tempo de consulta; DW já traz dias úteis)
-- ---------------------------------------------------------------------------
-- @Q2_REL
SELECT c.customer_state AS uf,
       COUNT(*) AS itens,
       ROUND(AVG(julianday(date(o.order_delivered_customer_date))
               - julianday(date(o.order_purchase_timestamp))), 2) AS prazo_medio
FROM items i
JOIN orders    o ON o.order_id    = i.order_id
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered'
  AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_purchase_timestamp >= '2018-01-01' AND o.order_purchase_timestamp < '2018-04-01'
GROUP BY 1 ORDER BY prazo_medio DESC;

-- @Q2_CSV
SELECT c.customer_state AS uf, COUNT(*) AS itens,
       ROUND(AVG(date_diff('day', CAST(o.order_purchase_timestamp AS DATE),
                                  CAST(o.order_delivered_customer_date AS DATE))), 2) AS prazo_medio
FROM read_csv('{csv_dir}/olist_order_items_dataset.csv', header=true) i
JOIN read_csv('{csv_dir}/olist_orders_dataset.csv', header=true)    o ON o.order_id = i.order_id
JOIN read_csv('{csv_dir}/olist_customers_dataset.csv', header=true) c ON c.customer_id = o.customer_id
WHERE o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
  AND o.order_purchase_timestamp >= '2018-01-01' AND o.order_purchase_timestamp < '2018-04-01'
GROUP BY 1 ORDER BY prazo_medio DESC;

-- @Q2_PQT
SELECT uf_cliente AS uf, COUNT(*) AS itens,
       ROUND(AVG(prazo_entrega_dias_uteis), 2) AS prazo_medio
FROM read_parquet('{pqt_glob}', hive_partitioning = true)
WHERE ano = 2018 AND mes IN (1, 2, 3)
GROUP BY 1 ORDER BY prazo_medio DESC;

-- ---------------------------------------------------------------------------
-- Q3. Black Friday (nov/2017): faturamento por tipo de pagamento principal e região
-- ---------------------------------------------------------------------------
-- @Q3_REL
WITH pag AS (
    SELECT order_id, payment_type,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC) AS rn
    FROM payments
)
SELECT pag.payment_type AS tipo_pagamento,
       CASE WHEN c.customer_state IN ('AC','AP','AM','PA','RO','RR','TO') THEN 'Norte'
            WHEN c.customer_state IN ('AL','BA','CE','MA','PB','PE','PI','RN','SE') THEN 'Nordeste'
            WHEN c.customer_state IN ('DF','GO','MT','MS') THEN 'Centro-Oeste'
            WHEN c.customer_state IN ('ES','MG','RJ','SP') THEN 'Sudeste'
            ELSE 'Sul' END AS regiao,
       COUNT(*) AS itens,
       ROUND(SUM(i.price + i.freight_value), 2) AS receita_bruta
FROM items i
JOIN orders    o   ON o.order_id    = i.order_id
JOIN customers c   ON c.customer_id = o.customer_id
JOIN pag           ON pag.order_id  = o.order_id AND pag.rn = 1
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-11-01' AND o.order_purchase_timestamp < '2017-12-01'
GROUP BY 1, 2 ORDER BY receita_bruta DESC;

-- @Q3_CSV
WITH pag AS (
    SELECT order_id, payment_type,
           ROW_NUMBER() OVER (PARTITION BY order_id ORDER BY payment_value DESC) AS rn
    FROM read_csv('{csv_dir}/olist_order_payments_dataset.csv', header=true)
)
SELECT pag.payment_type AS tipo_pagamento,
       CASE WHEN c.customer_state IN ('AC','AP','AM','PA','RO','RR','TO') THEN 'Norte'
            WHEN c.customer_state IN ('AL','BA','CE','MA','PB','PE','PI','RN','SE') THEN 'Nordeste'
            WHEN c.customer_state IN ('DF','GO','MT','MS') THEN 'Centro-Oeste'
            WHEN c.customer_state IN ('ES','MG','RJ','SP') THEN 'Sudeste'
            ELSE 'Sul' END AS regiao,
       COUNT(*) AS itens,
       ROUND(SUM(i.price + i.freight_value), 2) AS receita_bruta
FROM read_csv('{csv_dir}/olist_order_items_dataset.csv', header=true) i
JOIN read_csv('{csv_dir}/olist_orders_dataset.csv', header=true)    o ON o.order_id = i.order_id
JOIN read_csv('{csv_dir}/olist_customers_dataset.csv', header=true) c ON c.customer_id = o.customer_id
JOIN pag ON pag.order_id = o.order_id AND pag.rn = 1
WHERE o.order_status = 'delivered'
  AND o.order_purchase_timestamp >= '2017-11-01' AND o.order_purchase_timestamp < '2017-12-01'
GROUP BY 1, 2 ORDER BY receita_bruta DESC;

-- @Q3_PQT
SELECT tipo_pagamento, regiao_cliente AS regiao, COUNT(*) AS itens,
       ROUND(SUM(valor_bruto), 2) AS receita_bruta
FROM read_parquet('{pqt_glob}', hive_partitioning = true)
WHERE ano = 2017 AND mes = 11
GROUP BY 1, 2 ORDER BY receita_bruta DESC;
