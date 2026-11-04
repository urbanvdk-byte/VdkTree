-- VdkTree v0.3.0. Run in Supabase SQL Editor.
create extension if not exists pgcrypto;
create table if not exists public.trees (
 id uuid primary key default gen_random_uuid(),
 lat double precision not null check(lat between 42 and 44),
 lon double precision not null check(lon between 130 and 134),
 species text not null check(length(trim(species)) between 1 and 80),
 condition text not null check(condition in ('healthy','damaged','dead')),
 height numeric check(height > 0 and height <= 100),
 diameter numeric check(diameter > 0 and diameter <= 1000),
 comment text not null default '' check(length(comment) <= 1000),
 photo text,
 author_id uuid not null default auth.uid() references auth.users(id),
 status text not null default 'pending' check(status in ('pending','approved','rejected')),
 created_at timestamptz not null default now()
);
create index if not exists trees_location_idx on public.trees(lat,lon);
create index if not exists trees_status_idx on public.trees(status);
alter table public.trees enable row level security;
create policy "Anyone can view approved trees" on public.trees for select to anon,authenticated using (status='approved');
create policy "Users can view own submissions" on public.trees for select to authenticated using (author_id=(select auth.uid()));
create policy "Authenticated users can submit pending trees" on public.trees for insert to authenticated with check (author_id=(select auth.uid()) and status='pending' and photo is null);
-- Photo uploads are disabled until safe storage policies and moderation are implemented.
-- Review/approval happens in Supabase dashboard with service-role privileges, never from the browser.
