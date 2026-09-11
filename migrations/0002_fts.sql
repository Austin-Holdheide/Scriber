-- ===== Scriber W11: full-text search =====

create index if not exists segments_text_fts_idx
  on public.segments using gin (to_tsvector('english', text));

-- auth.uid() variant (direct RPC with user JWT)
create or replace function public.search_segments(query text)
returns table (
  segment_id bigint, transcript_id uuid, video_id uuid, filename text,
  start_ms int, end_ms int, text text, headline text, rank real
)
language sql stable security definer set search_path = public, pg_temp as $$
  select s.id, s.transcript_id, v.id as video_id, v.filename,
         s.start_ms, s.end_ms, s.text,
         ts_headline('english', s.text, websearch_to_tsquery('english', query),
                     'StartSel=<b>,StopSel=</b>,MaxFragments=2,MaxWords=35,MinWords=15'),
         ts_rank(to_tsvector('english', s.text), websearch_to_tsquery('english', query))
  from public.segments s
  join public.transcripts t on t.id = s.transcript_id
  join public.videos v on v.id = t.video_id
  where v.user_id = auth.uid()
    and to_tsvector('english', s.text) @@ websearch_to_tsquery('english', query)
  order by 9 desc
  limit 200;
$$;
grant execute on function public.search_segments(text) to authenticated;

-- explicit-user variant (used by the API with the service key)
create or replace function public.search_segments_for_user(query text, "user" uuid)
returns table (
  segment_id bigint, transcript_id uuid, video_id uuid, filename text,
  start_ms int, end_ms int, text text, headline text, rank real
)
language sql stable security definer set search_path = public, pg_temp as $$
  select s.id, s.transcript_id, v.id as video_id, v.filename,
         s.start_ms, s.end_ms, s.text,
         ts_headline('english', s.text, websearch_to_tsquery('english', query),
                     'StartSel=<b>,StopSel=</b>,MaxFragments=2,MaxWords=35,MinWords=15'),
         ts_rank(to_tsvector('english', s.text), websearch_to_tsquery('english', query))
  from public.segments s
  join public.transcripts t on t.id = s.transcript_id
  join public.videos v on v.id = t.video_id
  where v.user_id = "user"
    and to_tsvector('english', s.text) @@ websearch_to_tsquery('english', query)
  order by 9 desc
  limit 200;
$$;
grant execute on function public.search_segments_for_user(text, uuid) to service_role;
