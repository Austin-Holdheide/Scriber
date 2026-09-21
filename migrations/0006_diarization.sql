-- W10: diarization support
alter table public.transcripts add column if not exists speakers jsonb;
