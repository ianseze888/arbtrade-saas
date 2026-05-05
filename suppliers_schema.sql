-- Supplier CRM table
create table suppliers (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references profiles(id) on delete cascade,
  name text not null,
  contact_name text,
  email text,
  phone text,
  website text,
  platform text,
  status text default 'prospect',
  moq text,
  payment_terms text,
  lead_time_days integer default 0,
  notes text,
  categories text,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

-- Enable RLS
alter table suppliers enable row level security;

-- Policies
create policy "Users can manage own suppliers"
  on suppliers for all
  using (auth.uid() = user_id);

-- Orders table for PO tracking
create table orders (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references profiles(id) on delete cascade,
  supplier_id uuid references suppliers(id) on delete set null,
  po_number text,
  product_name text,
  asin text,
  quantity integer,
  unit_cost text,
  total_cost text,
  status text default 'draft',
  notes text,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

alter table orders enable row level security;
create policy "Users can manage own orders"
  on orders for all
  using (auth.uid() = user_id);
