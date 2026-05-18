-- Support tickets table
create table support_tickets (
  id uuid default gen_random_uuid() primary key,
  user_id uuid references profiles(id) on delete cascade,
  email text,
  category text default 'general',
  subject text,
  message text not null,
  status text default 'open',
  ai_response text,
  ai_responded_at timestamp,
  escalated boolean default false,
  escalated_at timestamp,
  created_at timestamp default now(),
  updated_at timestamp default now()
);

alter table support_tickets enable row level security;
create policy "Users can manage own tickets"
  on support_tickets for all
  using (auth.uid() = user_id);

-- Platform health logs
create table health_logs (
  id uuid default gen_random_uuid() primary key,
  check_type text,
  status text,
  message text,
  response_time_ms integer,
  checked_at timestamp default now()
);
