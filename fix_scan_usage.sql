-- Add last_scan column to scan_usage
ALTER TABLE scan_usage ADD COLUMN IF NOT EXISTS last_scan timestamp;
