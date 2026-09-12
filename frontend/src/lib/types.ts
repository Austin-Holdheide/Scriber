export type VideoRow = {
  id: string;
  filename: string;
  status: string;
  stage?: string;
  progress?: number;
  error?: string | null;
  size_bytes?: number | null;
  language?: string | null;
  created_at: string;
};

export type Segment = {
  id: number;
  start_ms: number;
  end_ms: number;
  speaker?: string | null;
  text: string;
  confidence?: number | null;
};

export type TranscriptData = {
  video: { id: string; filename: string; language?: string | null };
  full_text: string | null;
  segments: Segment[];
};
