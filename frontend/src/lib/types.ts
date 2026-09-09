export type VideoRow = {
  id: string;
  filename: string;
  status: string;
  stage?: string;
  progress?: number;
  size_bytes?: number | null;
  language?: string | null;
  created_at: string;
};
