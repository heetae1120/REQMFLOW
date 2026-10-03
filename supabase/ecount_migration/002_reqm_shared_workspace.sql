-- REQM FLOW multi-PC shared operational workspace.
-- Run once in the target Supabase project's SQL Editor.

create table if not exists public.reqm_workspace_state (
  workspace_key text primary key,
  version bigint not null default 0,
  state jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  updated_by uuid default auth.uid()
);

alter table public.reqm_workspace_state enable row level security;

drop policy if exists "authenticated shared workspace" on public.reqm_workspace_state;
create policy "authenticated shared workspace"
on public.reqm_workspace_state
for all
to authenticated
using (true)
with check (true);

grant select, insert, update on public.reqm_workspace_state to authenticated;

create or replace function public.reqm_save_workspace_state(
  p_workspace_key text,
  p_expected_version bigint,
  p_state jsonb
)
returns table(new_version bigint, new_updated_at timestamptz)
language plpgsql
security invoker
set search_path = public
as $$
declare
  saved_version bigint;
  saved_at timestamptz;
begin
  update public.reqm_workspace_state
     set state = p_state,
         version = version + 1,
         updated_at = now(),
         updated_by = auth.uid()
   where workspace_key = p_workspace_key
     and version = p_expected_version
  returning version, updated_at into saved_version, saved_at;

  if found then
    return query select saved_version, saved_at;
    return;
  end if;

  if p_expected_version = 0 then
    begin
      insert into public.reqm_workspace_state(workspace_key, version, state, updated_by)
      values (p_workspace_key, 1, p_state, auth.uid())
      returning version, updated_at into saved_version, saved_at;
      return query select saved_version, saved_at;
      return;
    exception when unique_violation then
      null;
    end;
  end if;

  raise exception 'REQM_VERSION_CONFLICT'
    using errcode = '40001', hint = '다른 PC가 먼저 저장했습니다. 최신 데이터를 다시 불러오세요.';
end;
$$;

grant execute on function public.reqm_save_workspace_state(text, bigint, jsonb) to authenticated;

do $$
begin
  if not exists (
    select 1 from pg_publication_tables
    where pubname = 'supabase_realtime'
      and schemaname = 'public'
      and tablename = 'reqm_workspace_state'
  ) then
    alter publication supabase_realtime add table public.reqm_workspace_state;
  end if;
end $$;
