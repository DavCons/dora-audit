
create table if not exists public.allowed_emails (
  email text primary key,
  created_at timestamptz default now(),
  source text default 'checkout'
);
alter table public.allowed_emails enable row level security;
drop policy if exists "read own email" on public.allowed_emails;
create policy "read own email" on public.allowed_emails
for select to authenticated using ( email = auth.jwt() ->> 'email' );
