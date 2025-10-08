create table if not exists assessments(id uuid default gen_random_uuid() primary key, created_at timestamptz default now(), org text, payload jsonb);
