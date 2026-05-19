-- Clear fake ASINs from existing leads
-- Real ASINs are exactly 10 chars starting with B followed by alphanumeric
UPDATE leads 
SET asin = ''
WHERE asin IS NOT NULL 
AND (
    length(asin) != 10 
    OR asin NOT LIKE 'B%'
    OR asin IN ('B00XXXXX', 'B0EXAMPLE', 'B0XXXXXXXX', 'B00EXAMPLE')
);

-- Show how many were fixed
SELECT COUNT(*) as leads_with_empty_asin FROM leads WHERE asin = '' OR asin IS NULL;
SELECT COUNT(*) as leads_with_real_asin FROM leads WHERE length(asin) = 10 AND asin LIKE 'B%';
