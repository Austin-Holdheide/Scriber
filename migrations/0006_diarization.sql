-- W10: diarization support
alter table public.transcripts add column if not exists speakers jsonb;
alter table public.transcripts add column if not exists speaker_order jsonb;
