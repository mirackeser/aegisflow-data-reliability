-- SPDX-License-Identifier: Apache-2.0
SELECT customer_id, COUNT(*) AS order_count, SUM(total_cents) AS total_cents
FROM staging_orders
WHERE record_number > 1
GROUP BY customer_id
ORDER BY customer_id
