import { api } from './index';

export type ReviewVerdict = 'PASS' | 'WARNING' | 'FAIL';
export interface ImageReviewIssue {
  type: string;
  severity: 'WARNING' | 'FAIL';
  expected: string;
  observed: string;
  location: string;
  evidence: string;
  suggestion: string;
  visibility: string;
}
export interface ImageReview {
  id: string;
  taskId: string;
  trigger: 'manual' | 'automatic';
  status: 'pending' | 'running' | 'success' | 'error';
  overall: ReviewVerdict | null;
  summary: string | null;
  dimensions: Record<string, { status: ReviewVerdict; summary: string }>;
  issues: ImageReviewIssue[];
  input: { original_prompt?: string; generated_image?: string; references?: Array<{ picture: number; sources: string[]; purpose?: string }> };
  templateVersion: string | null;
  templateName: string | null;
  llmLogId: string | null;
  model: string | null;
  error: string | null;
  createdAt: string | null;
}

export type ImageQualityStatus = 'NOT_REVIEWED' | 'PENDING' | 'RUNNING' | 'PASS' | 'REVIEW' | 'FAIL' | 'ERROR';
export interface CurrentReviewImage { taskId: string | null; imageUrl: string }
export interface CurrentImageQuality extends CurrentReviewImage {
  qualityStatus: ImageQualityStatus;
  reviewId: string | null;
  summary: string | null;
}

export const imageReviewApi = {
  list: (taskId: string) => api.get<ImageReview[]>(`/tasks/${taskId}/image-reviews`),
  create: (taskId: string) => api.post<ImageReview>(`/tasks/${taskId}/image-reviews`),
  statuses: (images: CurrentReviewImage[]) => api.post<CurrentImageQuality[]>('/tasks/image-review-statuses', { images }),
};
