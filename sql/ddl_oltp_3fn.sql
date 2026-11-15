-- Modelo transacional de origem (OLTP, 3FN) - Olist
-- Materializado em SQLite para o benchmark de consultas com múltiplos JOINs.

CREATE TABLE customers (
    customer_id              TEXT PRIMARY KEY,
    customer_unique_id       TEXT,
    customer_zip_code_prefix TEXT,
    customer_city            TEXT,
    customer_state           TEXT
);

CREATE TABLE sellers (
    seller_id              TEXT PRIMARY KEY,
    seller_zip_code_prefix TEXT,
    seller_city            TEXT,
    seller_state           TEXT
);

CREATE TABLE product_category_name_translation (
    product_category_name         TEXT PRIMARY KEY,
    product_category_name_english TEXT
);

CREATE TABLE products (
    product_id                 TEXT PRIMARY KEY,
    product_category_name      TEXT REFERENCES product_category_name_translation(product_category_name),
    product_name_lenght        INTEGER,
    product_description_lenght INTEGER,
    product_photos_qty         INTEGER,
    product_weight_g           REAL,
    product_length_cm          REAL,
    product_height_cm          REAL,
    product_width_cm           REAL
);

CREATE TABLE orders (
    order_id                      TEXT PRIMARY KEY,
    customer_id                   TEXT REFERENCES customers(customer_id),
    order_status                  TEXT,
    order_purchase_timestamp      TEXT,
    order_approved_at             TEXT,
    order_delivered_carrier_date  TEXT,
    order_delivered_customer_date TEXT,
    order_estimated_delivery_date TEXT
);

CREATE TABLE items (
    order_id            TEXT REFERENCES orders(order_id),
    order_item_id       INTEGER,
    product_id          TEXT REFERENCES products(product_id),
    seller_id           TEXT REFERENCES sellers(seller_id),
    shipping_limit_date TEXT,
    price               REAL,
    freight_value       REAL,
    PRIMARY KEY (order_id, order_item_id)
);

CREATE TABLE payments (
    order_id             TEXT REFERENCES orders(order_id),
    payment_sequential   INTEGER,
    payment_type         TEXT,
    payment_installments INTEGER,
    payment_value        REAL,
    PRIMARY KEY (order_id, payment_sequential)
);

CREATE TABLE reviews (
    review_id               TEXT,
    order_id                TEXT REFERENCES orders(order_id),
    review_score            INTEGER,
    review_comment_title    TEXT,
    review_comment_message  TEXT,
    review_creation_date    TEXT,
    review_answer_timestamp TEXT
);

-- Índices típicos de um OLTP (FKs e filtros comuns)
CREATE INDEX ix_orders_customer   ON orders(customer_id);
CREATE INDEX ix_orders_purchase   ON orders(order_purchase_timestamp);
CREATE INDEX ix_items_product     ON items(product_id);
CREATE INDEX ix_items_seller      ON items(seller_id);
CREATE INDEX ix_reviews_order     ON reviews(order_id);
