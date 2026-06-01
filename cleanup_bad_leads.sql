-- Remove leads with no sell price AND no BSR (inactive/dead listings)
DELETE FROM leads 
WHERE (
  (data->>'sell_price' IS NULL OR data->>'sell_price' = '' OR data->>'sell_price' = '—')
  AND
  (data->>'bsr' IS NULL OR data->>'bsr' = '' OR data->>'bsr' = '—')
  AND
  (data->>'sellers' IS NULL OR data->>'sellers' = '' OR data->>'sellers' = '0' OR CAST(data->>'sellers' AS INTEGER) = 0)
);

-- Show how many leads remain
SELECT COUNT(*) as remaining_leads FROM leads;
SELECT COUNT(*) as bad_leads_removed FROM leads 
WHERE (data->>'sell_price' IS NULL OR data->>'sell_price' = '' OR data->>'sell_price' = '—')
AND (data->>'bsr' IS NULL OR data->>'bsr' = '' OR data->>'bsr' = '—');
