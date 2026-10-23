/**
 * 道具页面类型定义
 */
import type { Prop } from '../../types';

export interface PropWithNovel extends Prop {
  novelName?: string;
}

export interface PreviewImageState {
  isOpen: boolean;
  url: string | null;
  name: string;
  propId: string | null;
}

export interface DeleteAllConfirmDialog {
  isOpen: boolean;
}
