create table if not exists access_codes(email text primary key, active boolean default true, created_at timestamptz default now());
