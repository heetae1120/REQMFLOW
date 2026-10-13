-- Additive migration. The legacy snapshot and all Shipping tables remain intact.
begin;
create table if not exists public.flow_sync_members(
 workspace_key text not null, user_id uuid not null references auth.users(id),
 primary key(workspace_key,user_id));
insert into public.flow_sync_members select 'default',id from auth.users on conflict do nothing;
create table if not exists public.flow_sync_meta(
 workspace_key text primary key, version bigint not null default 1,
 updated_at timestamptz not null default now());
create table if not exists public.flow_sync_records(
 workspace_key text not null references public.flow_sync_meta(workspace_key),
 row_key text not null, table_name text not null, payload jsonb,
 deleted boolean not null default false, revision bigint not null,
 updated_by uuid, primary key(workspace_key,row_key));
create index if not exists flow_sync_revision on public.flow_sync_records(workspace_key,revision,row_key);
alter table public.flow_sync_members enable row level security;
alter table public.flow_sync_meta enable row level security;
alter table public.flow_sync_records enable row level security;
create policy flow_member_read on public.flow_sync_members for select to authenticated using(user_id=auth.uid());
create policy flow_meta_read on public.flow_sync_meta for select to authenticated using(exists(select 1 from public.flow_sync_members m where m.workspace_key=flow_sync_meta.workspace_key and m.user_id=auth.uid()));
create policy flow_record_read on public.flow_sync_records for select to authenticated using(exists(select 1 from public.flow_sync_members m where m.workspace_key=flow_sync_records.workspace_key and m.user_id=auth.uid()));
grant select on public.flow_sync_members,public.flow_sync_meta,public.flow_sync_records to authenticated;
insert into public.flow_sync_meta(workspace_key) values('default') on conflict do nothing;
-- Seed only once; preserve the old shared workspace as a rollback source.
do $$
declare tab text; rows jsonb; item jsonb; cols jsonb; ids jsonb; column_name text;
begin
 if exists(select 1 from public.flow_sync_records where workspace_key='default') then return; end if;
 for tab,rows in select key,value from jsonb_each(coalesce((select state->'tables' from public.reqm_workspace_state where workspace_key='default'),'{}'::jsonb)) loop
  cols=case tab when 'mappings' then '["key"]'::jsonb when 'item_names' then '["erp_item_code"]'::jsonb when 'fees' then '["bundle"]'::jsonb when 'source_files' then '["name"]'::jsonb when 'artifact_notes' then '["artifact_id","row_key"]'::jsonb when 'tracking_sources' then '["job_id","name"]'::jsonb when 'events' then '["at","action","detail"]'::jsonb else '["id"]'::jsonb end;
  for item in select value from jsonb_array_elements(rows) loop
   ids='[]'::jsonb;
   for column_name in select jsonb_array_elements_text(cols) loop ids=ids||jsonb_build_array(item->column_name); end loop;
   insert into public.flow_sync_records values('default',tab||':'||ids::text,tab,case when tab='events' then item-'id' else item end,false,1,null) on conflict do nothing;
  end loop;
 end loop;
 insert into public.flow_sync_records values('default','settings:[]','settings',coalesce((select state->'settings' from public.reqm_workspace_state where workspace_key='default'),'{}'::jsonb)-'cloud_email',false,1,null) on conflict do nothing;
end $$;
create or replace function public.flow_sync_apply(p_workspace text,p_changes jsonb)
returns jsonb language plpgsql security definer set search_path=public,pg_temp as $$
declare new_version bigint; entry jsonb; previous public.flow_sync_records; count_changes integer;
begin
 if auth.uid() is null or not exists(select 1 from public.flow_sync_members where workspace_key=p_workspace and user_id=auth.uid()) then raise exception 'FLOW_ACCESS_DENIED'; end if;
 count_changes=jsonb_array_length(p_changes);
 if count_changes>10000 or octet_length(p_changes::text)>12582912 then raise exception 'FLOW_BATCH_TOO_LARGE'; end if;
 if count_changes=0 then return jsonb_build_object('version',(select version from public.flow_sync_meta where workspace_key=p_workspace)); end if;
 select version+1 into new_version from public.flow_sync_meta where workspace_key=p_workspace for update;
 if new_version is null then raise exception 'FLOW_WORKSPACE_MISSING'; end if;
 for entry in select value from jsonb_array_elements(p_changes) loop
  if entry->>'table_name' not in ('orders','mappings','item_names','event_rules','requests','request_lines','shipments','smartstore_erp_rows','smartstore_purchase_rows','esm_erp_rows','fees','artifacts','source_files','artifact_notes','events','tracking_jobs','tracking_rows','tracking_queries','tracking_sources','settings') then raise exception 'FLOW_UNKNOWN_TABLE'; end if;
  select * into previous from public.flow_sync_records where workspace_key=p_workspace and row_key=entry->>'row_key';
  if coalesce(previous.revision,0)<>(entry->>'expected_revision')::bigint then raise exception 'FLOW_ROW_CONFLICT'; end if;
  insert into public.flow_sync_records(workspace_key,row_key,table_name,payload,deleted,revision,updated_by)
  values(p_workspace,entry->>'row_key',entry->>'table_name',entry->'payload',coalesce((entry->>'deleted')::boolean,false),new_version,auth.uid())
  on conflict(workspace_key,row_key) do update set payload=excluded.payload,deleted=excluded.deleted,revision=excluded.revision,updated_by=excluded.updated_by;
 end loop;
 update public.flow_sync_meta set version=new_version,updated_at=now() where workspace_key=p_workspace;
 return jsonb_build_object('version',new_version);
end $$;
revoke all on function public.flow_sync_apply(text,jsonb) from public,anon;
grant execute on function public.flow_sync_apply(text,jsonb) to authenticated;
commit;
