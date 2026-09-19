-- W12 fix: global search misses words that are substrings/derivatives
-- (e.g. "search" did not surface "research", "unsearchable"). Hybrid query:
-- ranked FTS matches first, then prefix matches, then substring matches, deduped.
create or replace function public.search_segments_for_user(query text, "user" uuid)
returns table(segment_id bigint, transcript_id uuid, video_id uuid, filename text,
              start_ms integer, end_ms integer, text text, headline text, rank real)
language sql stable security definer
set search_path to 'public', 'pg_temp'
as $function$
  with fts as (
    select s.id, s.transcript_id, v.id as video_id, v.filename,
           s.start_ms, s.end_ms, s.text,
           ts_headline('english', s.text, websearch_to_tsquery('english', query),
                       'StartSel=<b>,StopSel=</b>,MaxFragments=2,MaxWords=35,MinWords=15') as headline,
           ts_rank(to_tsvector('english', s.text), websearch_to_tsquery('english', query)) as rank
    from public.segments s
    join public.transcripts t on t.id = s.transcript_id
    join public.videos v on v.id = t.video_id
    where v.user_id = "user"
      and to_tsvector('english', s.text) @@ websearch_to_tsquery('english', query)
  ),
  prefix as (
    select s.id, s.transcript_id, v.id as video_id, v.filename,
           s.start_ms, s.end_ms, s.text,
           ts_headline('english', s.text, to_tsquery('english', replace(query, ' ', ':* | ') || ':*'),
                       'StartSel=<b>,StopSel=</b>,MaxFragments=2,MaxWords=35,MinWords=15') as headline,
           0.5::real as rank
    from public.segments s
    join public.transcripts t on t.id = s.transcript_id
    join public.videos v on v.id = t.video_id
    where v.user_id = "user"
      and query <> ''
      and to_tsvector('english', s.text) @@ to_tsquery('english', replace(query, ' ', ':* | ') || ':*')
  ),
  substr as (
    select s.id, s.transcript_id, v.id as video_id, v.filename,
           s.start_ms, s.end_ms, s.text,
           ('<b>' || query || '</b>') as headline,
           0.1::real as rank
    from public.segments s
    join public.transcripts t on t.id = s.transcript_id
    join public.videos v on v.id = t.video_id
    where v.user_id = "user"
      and length(query) >= 3
      and s.text ilike '%' || query || '%'
  )
  select * from fts
  union
  select * from prefix
  union
  select * from substr
  order by rank desc, start_ms asc
  limit 200;
$function$;
