-- Schema carregado automaticamente pelo MySQL (docker-entrypoint-initdb.d).

-- Auditoria: toda entrega bruta, inclusive repetidas, invalidas e ignoradas.
CREATE TABLE IF NOT EXISTS raw_requests (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    correlation_id CHAR(36)     NOT NULL,
    received_at    TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    headers        JSON         NOT NULL,
    body           MEDIUMTEXT   NOT NULL,
    result         VARCHAR(32)  NULL, -- accepted|duplicate|ignored|decrypt_failed|schema_failed|unavailable
    transaction_id VARCHAR(255) NULL,
    event          VARCHAR(100) NULL,
    error_summary  VARCHAR(500) NULL,
    processed_at   TIMESTAMP(3) NULL,
    KEY idx_raw_correlation (correlation_id),
    KEY idx_raw_result (result)
) ENGINE=InnoDB;

-- Controle de idempotencia da API. A UNIQUE KEY e o lock entre processos.
-- Uma linha so existe (commitada) depois que a publicacao foi confirmada pelo broker.
CREATE TABLE IF NOT EXISTS webhook_events (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    transaction_id VARCHAR(255) NOT NULL,
    event          VARCHAR(100) NOT NULL,
    correlation_id CHAR(36)     NOT NULL,
    status         ENUM('pending', 'published') NOT NULL DEFAULT 'pending',
    created_at     TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    published_at   TIMESTAMP(3) NULL,
    UNIQUE KEY uq_webhook_event (transaction_id, event)
) ENGINE=InnoDB;

-- Dominio (gravado pelo worker).
CREATE TABLE IF NOT EXISTS customers (
    id         BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    email      VARCHAR(320) NOT NULL,
    first_name VARCHAR(255) NOT NULL,
    phone      VARCHAR(20)  NOT NULL,
    country    CHAR(2)      NOT NULL,
    created_at TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_customer_email (email)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS orders (
    id               BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    transaction_id   VARCHAR(255) NOT NULL,
    customer_id      BIGINT UNSIGNED NOT NULL,
    product_id       VARCHAR(100) NOT NULL,
    product_name     VARCHAR(255) NOT NULL,
    country          CHAR(2)      NOT NULL,
    amount_usd       DECIMAL(12, 2) NOT NULL,
    transaction_time DATETIME(3)  NOT NULL, -- UTC
    created_at       TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_order_transaction (transaction_id),
    CONSTRAINT fk_order_customer FOREIGN KEY (customer_id) REFERENCES customers (id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_events (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    order_id       BIGINT UNSIGNED NOT NULL,
    event          VARCHAR(100) NOT NULL,
    payment_status VARCHAR(50)  NOT NULL,
    correlation_id CHAR(36)     NOT NULL,
    created_at     TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    UNIQUE KEY uq_order_event (order_id, event),
    CONSTRAINT fk_event_order FOREIGN KEY (order_id) REFERENCES orders (id)
) ENGINE=InnoDB;
