import type { Task } from '../../types';

export type TaskFilter = 'all' | 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';

export type TaskType = Task['type'];
export type TaskTypeFilter = 'all' | TaskType | string;

export type TaskStatus = Task['status'];

export interface ImageInfo {
  width: number;
  height: number;
  size?: string;
}

export interface WorkflowData {
  workflow: any;
  prompt: string;
  note?: string;
  workflowSource?: string;
  evidence?: Record<string,{state:string;error?:string|null;sha256?:string|null}>;
}

export interface TaskStats {
  all: number;
  pending: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
}
