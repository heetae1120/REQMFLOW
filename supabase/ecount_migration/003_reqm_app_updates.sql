-- REQM FLOW executable update repository.
-- Run once in the same Supabase project's SQL Editor.

insert into storage.buckets (id, name, public, file_size_limit)
values ('reqm-updates', 'reqm-updates', true, 314572800)
on conflict (id) do update
set public = excluded.public,
    file_size_limit = excluded.file_size_limit;

drop policy if exists "REQM update upload" on storage.objects;
create policy "REQM update upload"
on storage.objects for insert to authenticated
with check (
  bucket_id = 'reqm-updates'
  and (storage.foldername(name))[1] = 'desktop'
);

drop policy if exists "REQM update inspect" on storage.objects;
create policy "REQM update inspect"
on storage.objects for select to authenticated
using (
  bucket_id = 'reqm-updates'
  and (storage.foldername(name))[1] = 'desktop'
);

drop policy if exists "REQM update overwrite" on storage.objects;
create policy "REQM update overwrite"
on storage.objects for update to authenticated
using (
  bucket_id = 'reqm-updates'
  and (storage.foldername(name))[1] = 'desktop'
)
with check (
  bucket_id = 'reqm-updates'
  and (storage.foldername(name))[1] = 'desktop'
);

drop policy if exists "REQM update delete" on storage.objects;
create policy "REQM update delete"
on storage.objects for delete to authenticated
using (
  bucket_id = 'reqm-updates'
  and (storage.foldername(name))[1] = 'desktop'
);
