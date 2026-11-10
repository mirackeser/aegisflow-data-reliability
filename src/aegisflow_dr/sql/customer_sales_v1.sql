SELECT customer_id, COUNT(*) AS order_count, SUM(total_cents) AS total_cents
FROM staging_orders
GROUP BY customer_id
ORDER BY customer_id
