-- Add missing columns to leads table
ALTER TABLE leads ADD COLUMN IF NOT EXISTS verification_status text default 'unverified';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS verified boolean default false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS confidence text default '—';
ALTER TABLE leads ADD COLUMN IF NOT EXISTS approved boolean default false;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS approved_at timestamp;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS source text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS asin text;
