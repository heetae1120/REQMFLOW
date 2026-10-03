-- 위킵_이카운트_양식.xlsx 기준정보용 스키마
-- 기존 REQM의 items/item_aliases/product_components 테이블은 변경하지 않는다.
-- Supabase SQL Editor에서 먼저 실행한 후 import_ecount_reference.py를 실행한다.

create table if not exists public.ecount_item_reference (
  item_code text primary key,
  representative_name text not null,
  alias_count integer not null default 0 check (alias_count >= 0),
  first_source_row integer,
  review_status text not null default 'confirmed'
    check (review_status in ('confirmed', 'review')),
  is_active boolean not null default true,
  imported_at timestamptz not null default now()
);

create table if not exists public.ecount_item_aliases (
  alias_key text primary key,
  alias_name text not null,
  normalized_alias text not null,
  item_code text not null references public.ecount_item_reference(item_code),
  occurrence_count integer not null default 1 check (occurrence_count > 0),
  first_source_row integer,
  review_status text not null default 'confirmed'
    check (review_status in ('confirmed', 'conflict', 'review')),
  is_active boolean not null default true,
  imported_at timestamptz not null default now(),
  unique (normalized_alias, item_code)
);
create index if not exists ecount_item_aliases_normalized_idx
  on public.ecount_item_aliases(normalized_alias);

create table if not exists public.ecount_sales_channels (
  source_name text primary key,
  normalized_name text not null,
  ecount_customer_code text not null,
  ecount_customer_name text,
  channel_group text,
  source_row integer,
  is_active boolean not null default true,
  imported_at timestamptz not null default now()
);
create index if not exists ecount_sales_channels_normalized_idx
  on public.ecount_sales_channels(normalized_name);

create table if not exists public.ecount_product_mappings (
  mapping_key text primary key,
  source_channel text not null,
  source_product_text text not null,
  normalized_source text not null,
  mapping_type text not null check (mapping_type in ('single', 'set')),
  component_count integer not null check (component_count between 1 and 5),
  source_row integer,
  review_status text not null default 'confirmed'
    check (review_status in ('confirmed', 'conflict', 'review')),
  is_active boolean not null default true,
  imported_at timestamptz not null default now(),
  unique (source_channel, normalized_source, mapping_key)
);
create index if not exists ecount_product_mappings_lookup_idx
  on public.ecount_product_mappings(source_channel, normalized_source)
  where is_active;

create table if not exists public.ecount_product_mapping_components (
  mapping_key text not null references public.ecount_product_mappings(mapping_key) on delete cascade,
  sequence integer not null check (sequence between 1 and 5),
  item_code text not null references public.ecount_item_reference(item_code),
  quantity numeric(12, 3) not null default 1 check (quantity > 0),
  source_row integer,
  primary key (mapping_key, sequence)
);
create index if not exists ecount_product_mapping_components_item_idx
  on public.ecount_product_mapping_components(item_code);

create table if not exists public.ecount_price_rules (
  price_rule_key text primary key,
  source_channel text not null,
  source_product_name text not null,
  source_options text not null default '',
  normalized_source text not null,
  total_unit_price numeric(18, 2) not null check (total_unit_price >= 0),
  item_type text not null check (item_type in ('단품', '세트')),
  main_product text,
  set_name text,
  component_count integer not null check (component_count > 0),
  allocated_total numeric(18, 2) not null,
  allocation_variance numeric(18, 2) not null,
  source_row integer,
  review_status text not null default 'confirmed'
    check (review_status in ('confirmed', 'amount_mismatch', 'missing_item', 'zero_price_review', 'review')),
  is_active boolean not null default true,
  imported_at timestamptz not null default now()
);
create index if not exists ecount_price_rules_lookup_idx
  on public.ecount_price_rules(source_channel, normalized_source, total_unit_price)
  where is_active;

create table if not exists public.ecount_price_rule_components (
  price_rule_key text not null references public.ecount_price_rules(price_rule_key) on delete cascade,
  sequence integer not null check (sequence > 0),
  component_alias text not null,
  normalized_component_alias text not null,
  item_code text references public.ecount_item_reference(item_code),
  quantity numeric(12, 3) not null default 1 check (quantity > 0),
  allocated_unit_price numeric(18, 2) not null,
  source_row integer,
  review_status text not null default 'confirmed'
    check (review_status in ('confirmed', 'missing_item', 'zero_price_review', 'review')),
  primary key (price_rule_key, sequence)
);
create index if not exists ecount_price_rule_components_item_idx
  on public.ecount_price_rule_components(item_code);

create table if not exists public.ecount_migration_issues (
  issue_key text primary key,
  issue_type text not null,
  source_sheet text not null,
  source_row integer,
  reference_value text,
  details jsonb not null default '{}'::jsonb,
  resolved boolean not null default false,
  imported_at timestamptz not null default now()
);
create index if not exists ecount_migration_issues_open_idx
  on public.ecount_migration_issues(issue_type, resolved);

create or replace view public.ecount_confirmed_item_aliases as
select alias_name, normalized_alias, item_code
from public.ecount_item_aliases
where is_active and review_status = 'confirmed';

create or replace view public.ecount_confirmed_price_rules as
select r.*, jsonb_agg(
  jsonb_build_object(
    'sequence', c.sequence,
    'item_code', c.item_code,
    'component_alias', c.component_alias,
    'quantity', c.quantity,
    'allocated_unit_price', c.allocated_unit_price
  ) order by c.sequence
) as components
from public.ecount_price_rules r
join public.ecount_price_rule_components c using (price_rule_key)
where r.is_active and r.review_status = 'confirmed'
group by r.price_rule_key;

do $$
declare table_name text;
begin
  foreach table_name in array array[
    'ecount_item_reference',
    'ecount_item_aliases',
    'ecount_sales_channels',
    'ecount_product_mappings',
    'ecount_product_mapping_components',
    'ecount_price_rules',
    'ecount_price_rule_components',
    'ecount_migration_issues'
  ] loop
    execute format('alter table public.%I enable row level security', table_name);
    if not exists (
      select 1 from pg_policies
      where schemaname = 'public'
        and tablename = table_name
        and policyname = 'authenticated full access'
    ) then
      execute format(
        'create policy "authenticated full access" on public.%I for all to authenticated using (true) with check (true)',
        table_name
      );
    end if;
    execute format('grant select, insert, update, delete on public.%I to authenticated', table_name);
  end loop;
end $$;

grant select on public.ecount_confirmed_item_aliases to authenticated;
grant select on public.ecount_confirmed_price_rules to authenticated;
