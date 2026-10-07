-- Vendas aprovadas e persistidas por pais e produto.
-- Colunas compativeis com data/expected_summary.csv.
SELECT
    'grummer'      AS gateway,
    o.country      AS country,
    o.product_name AS product_name,
    COUNT(DISTINCT o.id) AS accepted_count
FROM orders o
JOIN order_events e ON e.order_id = o.id
WHERE e.event = 'order.approved'
  AND e.payment_status = 'approved'
GROUP BY o.country, o.product_name
ORDER BY o.country, o.product_name;
