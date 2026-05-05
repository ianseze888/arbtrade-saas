-- Active SKUs for reorder monitoring
create table active_skus (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references profiles(id) on delete cascade,
  asin text not null,
  product_name text not null,
  supplier_name text,
  units_in_stock integer default 0,
  daily_sales_velocity numeric(10,2) default 0,
  reorder_point_days integer default 30,
  reorder_quantity integer default 0,
  unit_cost text,
  notes text,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

alter table active_skus enable row level security;
create policy "Users can manage own SKUs"
  on active_skus for all
  using (auth.uid() = user_id);

-- Add approved column to leads table
alter table leads add column if not exists approved boolean default false;
alter table leads add column if not exists approved_at timestamp;
