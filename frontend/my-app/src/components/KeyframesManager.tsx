import { useState, useRef, useEffect } from 'react';
import {
  Plus,
  Sparkles,
  Upload,
  Image as ImageIcon,
  Trash2,
  Edit2,
  Check,
  X,
  Loader2,
  ChevronDown,
  ChevronUp,
  RefreshCw,
  Eye,
} from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';
import { KeyframeData } from '../types';
import { shotsApi } from '../api/shots';
import { ImagePreviewModal } from './ImagePreviewModal';

interface KeyframesManagerProps {
  novelId: string;
  chapterId: string;
  shotId: string;
  shotImageUrl?: string;
  keyframes: KeyframeData[];
  onKeyframesUpdate: (keyframes: KeyframeData[]) => void;
  workflowId?: string;
}

type ReferenceMode = 'auto_select' | 'custom' | 'none';

export default function KeyframesManager({
  novelId,
  chapterId,
  shotId,
  shotImageUrl,
  keyframes,
  onKeyframesUpdate,
  workflowId,
}: KeyframesManagerProps) {
  const { t } = useTranslation();
  const [isGeneratingDescriptions, setIsGeneratingDescriptions] = useState(false);
  const [generatingImages, setGeneratingImages] = useState<Set<number>>(new Set());
  const [uploadingImages, setUploadingImages] = useState<Set<number>>(new Set());
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editDescription, setEditDescription] = useState('');
  const [expandedKeyframes, setExpandedKeyframes] = useState<Set<number>>(new Set());
  const [newKeyframeDescription, setNewKeyframeDescription] = useState('');
  const [isAddingKeyframe, setIsAddingKeyframe] = useState(false);
  const [referenceModes, setReferenceModes] = useState<Record<number, ReferenceMode>>({});
  const [previewImage, setPreviewImage] = useState<string | null>(null);

  const fileInputRefs = useRef<Record<number, HTMLInputElement | null>>({});
  const referenceInputRefs = useRef<Record<number, HTMLInputElement | null>>({});

  // Initialize reference modes from keyframes data
  useEffect(() => {
    const modes: Record<number, ReferenceMode> = {};
    keyframes.forEach((kf) => {
      // 优先使用保存的 reference_mode，否则根据 reference_image_url 推断
      if (kf.reference_mode) {
        modes[kf.frame_index] = kf.reference_mode as ReferenceMode;
      } else if (kf.reference_image_url === null || kf.reference_image_url === undefined) {
        modes[kf.frame_index] = 'none';
      } else {
        modes[kf.frame_index] = 'auto_select';
      }
    });
    setReferenceModes(modes);
  }, [keyframes]);

  // Poll for image generation status
  useEffect(() => {
    // 使用 generatingImages 状态来判断是否需要轮询
    if (generatingImages.size === 0) return;

    console.log('[KeyframesManager] Starting poll, generating frames:', [...generatingImages]);

    const pollInterval = setInterval(async () => {
      try {
        // 查询关键帧图片任务状态
        const response = await fetch(
          `/api/tasks/?chapter_id=${chapterId}&type=keyframe_image`
        );
        const result = await response.json();

        if (result.success && result.data) {
          let hasUpdates = false;
          const updatedKeyframes = keyframes.map((kf) => {
            if (kf.image_task_id && generatingImages.has(kf.frame_index)) {
              const task = result.data.find((t: any) => t.id === kf.image_task_id);
              if (task) {
                console.log(`[KeyframesManager] Task ${kf.image_task_id} status: ${task.status}`);
                if (task.status === 'completed' && task.resultUrl) {
                  hasUpdates = true;
                  // 清除生成中状态
                  setGeneratingImages((prev) => {
                    const next = new Set(prev);
                    next.delete(kf.frame_index);
                    return next;
                  });
                  return { ...kf, image_url: task.resultUrl };
                } else if (task.status === 'failed') {
                  // 任务失败，清除生成中状态
                  setGeneratingImages((prev) => {
                    const next = new Set(prev);
                    next.delete(kf.frame_index);
                    return next;
                  });
                  console.error(`[KeyframesManager] Task ${kf.image_task_id} failed:`, task.errorMessage);
                }
              }
            }
            return kf;
          });

          if (hasUpdates) {
            onKeyframesUpdate(updatedKeyframes);
          }
        }
      } catch (error) {
        console.error('Error polling keyframe task status:', error);
      }
    }, 3000);

    return () => clearInterval(pollInterval);
  }, [generatingImages, keyframes, chapterId, onKeyframesUpdate]);

  // Generate keyframe descriptions using AI
  const handleGenerateDescriptions = async () => {
    setIsGeneratingDescriptions(true);
    try {
      const result = await shotsApi.generateKeyframeDescriptions(
        novelId,
        chapterId,
        shotId,
        3
      );
      if (result.success && result.data?.keyframes) {
        onKeyframesUpdate(result.data.keyframes);
      } else {
        console.error('Failed to generate keyframe descriptions:', result.message);
      }
    } catch (error) {
      console.error('Error generating keyframe descriptions:', error);
    } finally {
      setIsGeneratingDescriptions(false);
    }
  };

  // Generate keyframe image
  const handleGenerateImage = async (frameIndex: number) => {
    setGeneratingImages((prev) => new Set([...prev, frameIndex]));
    try {
      const result = await shotsApi.generateKeyframeImage(
        novelId,
        chapterId,
        shotId,
        frameIndex,
        workflowId
      );
      console.log('[KeyframesManager] API result:', result);
      if (result.success && result.data?.task_id) {
        console.log('[KeyframesManager] Got task_id:', result.data.task_id);
        // Update keyframe with task_id
        const updatedKeyframes = keyframes.map((kf) =>
          kf.frame_index === frameIndex
            ? { ...kf, image_task_id: result.data!.task_id }
            : kf
        );
        onKeyframesUpdate(updatedKeyframes);
        // 不清除 generatingImages，等待轮询更新
      } else {
        console.error('[KeyframesManager] Failed to generate keyframe image:', result.message);
        // 提交失败时清除状态
        setGeneratingImages((prev) => {
          const next = new Set(prev);
          next.delete(frameIndex);
          return next;
        });
      }
    } catch (error) {
      console.error('[KeyframesManager] Error generating keyframe image:', error);
      // 出错时清除状态
      setGeneratingImages((prev) => {
        const next = new Set(prev);
        next.delete(frameIndex);
        return next;
      });
    }
  };

  // Upload keyframe image
  const handleUploadImage = async (frameIndex: number, file: File) => {
    setUploadingImages((prev) => new Set([...prev, frameIndex]));
    try {
      const result = await shotsApi.uploadKeyframeImage(
        novelId,
        chapterId,
        shotId,
        frameIndex,
        file
      );
      if (result.success && result.data?.image_url) {
        // Update keyframe with image_url
        const updatedKeyframes = keyframes.map((kf) =>
          kf.frame_index === frameIndex
            ? { ...kf, image_url: result.data!.image_url }
            : kf
        );
        onKeyframesUpdate(updatedKeyframes);
      } else {
        console.error('Failed to upload keyframe image:', result.message);
      }
    } catch (error) {
      console.error('Error uploading keyframe image:', error);
    } finally {
      setUploadingImages((prev) => {
        const next = new Set(prev);
        next.delete(frameIndex);
        return next;
      });
    }
  };

  // Upload reference image
  const handleUploadReferenceImage = async (frameIndex: number, file: File) => {
    try {
      const result = await shotsApi.uploadKeyframeReferenceImage(
        novelId,
        chapterId,
        shotId,
        frameIndex,
        file
      );
      if (result.success) {
        // 后端返回 reference_image_url
        const referenceUrl = result.data?.reference_image_url || result.data?.reference_url;
        if (referenceUrl) {
          // 更新本地模式为 custom
          setReferenceModes((prev) => ({ ...prev, [frameIndex]: 'custom' }));

          // Update keyframe with reference_url and reference_mode
          const updatedKeyframes: KeyframeData[] = keyframes.map((kf) =>
            kf.frame_index === frameIndex
              ? { ...kf, reference_image_url: referenceUrl, reference_mode: 'custom' }
              : kf
          );
          onKeyframesUpdate(updatedKeyframes);
        }
      } else {
        console.error('Failed to upload reference image:', result.message);
      }
    } catch (error) {
      console.error('Error uploading reference image:', error);
    }
  };

  // Set reference image mode
  const handleSetReferenceMode = async (frameIndex: number, mode: ReferenceMode) => {
    // 先立即更新本地状态
    setReferenceModes((prev) => ({ ...prev, [frameIndex]: mode }));

    // 同时更新 keyframes 数据中的 reference_mode
    const updatedKeyframes = keyframes.map((kf) =>
      kf.frame_index === frameIndex
        ? { ...kf, reference_mode: mode }
        : kf
    );
    onKeyframesUpdate(updatedKeyframes);

    // custom 模式下如果已有 reference_image_url，则传递给后端
    // 否则传递 null，后端只保存模式
    const currentKf = keyframes.find(kf => kf.frame_index === frameIndex);
    const customReferenceUrl = mode === 'custom' ? (currentKf?.reference_image_url || null) : undefined;

    try {
      const result = await shotsApi.setKeyframeReferenceImage(
        novelId,
        chapterId,
        shotId,
        frameIndex,
        mode,
        customReferenceUrl || undefined
      );
      if (result.success) {
        // Update keyframe with new reference_url
        const referenceUrl = result.data?.reference_image_url || result.data?.reference_url || null;
        const finalKeyframes = updatedKeyframes.map((kf) =>
          kf.frame_index === frameIndex
            ? { ...kf, reference_image_url: referenceUrl }
            : kf
        );
        onKeyframesUpdate(finalKeyframes);
      } else {
        console.error('Failed to set reference mode:', result.message);
      }
    } catch (error) {
      console.error('Error setting reference mode:', error);
    }
  };

  // Add new keyframe
  const handleAddKeyframe = async () => {
    if (!newKeyframeDescription.trim()) return;

    setIsAddingKeyframe(true);
    try {
      const newKeyframe: KeyframeData = {
        frame_index: keyframes.length,
        description: newKeyframeDescription.trim(),
        image_url: undefined,
        image_task_id: undefined,
        reference_image_url: null,
        reference_mode: 'auto_select',
      };
      const updatedKeyframes = [...keyframes, newKeyframe];
      onKeyframesUpdate(updatedKeyframes);

      // 保存到后端
      await shotsApi.updateKeyframes(novelId, chapterId, shotId, updatedKeyframes);

      setNewKeyframeDescription('');
    } catch (error) {
      console.error('Error adding keyframe:', error);
    } finally {
      setIsAddingKeyframe(false);
    }
  };

  // Update keyframe description
  const handleUpdateDescription = async (frameIndex: number) => {
    if (!editDescription.trim()) return;

    const updatedKeyframes = keyframes.map((kf) =>
      kf.frame_index === frameIndex
        ? { ...kf, description: editDescription.trim() }
        : kf
    );
    onKeyframesUpdate(updatedKeyframes);
    setEditingIndex(null);
    setEditDescription('');

    // 保存到后端
    try {
      await shotsApi.updateKeyframes(novelId, chapterId, shotId, updatedKeyframes);
    } catch (error) {
      console.error('Error updating keyframe:', error);
    }
  };

  // Delete keyframe
  const handleDeleteKeyframe = async (frameIndex: number) => {
    const updatedKeyframes = keyframes
      .filter((kf) => kf.frame_index !== frameIndex)
      .map((kf, index) => ({ ...kf, frame_index: index }));
    onKeyframesUpdate(updatedKeyframes);

    // 保存到后端
    try {
      await shotsApi.updateKeyframes(novelId, chapterId, shotId, updatedKeyframes);
    } catch (error) {
      console.error('Error deleting keyframe:', error);
    }
  };

  // Toggle keyframe expansion
  const toggleExpanded = (frameIndex: number) => {
    setExpandedKeyframes((prev) => {
      const next = new Set(prev);
      if (next.has(frameIndex)) {
        next.delete(frameIndex);
      } else {
        next.add(frameIndex);
      }
      return next;
    });
  };

  // Get the reference image URL for display
  const getReferenceImageUrl = (kf: KeyframeData): string | null => {
    const mode = referenceModes[kf.frame_index] || 'auto_select';

    if (mode === 'none') return null;
    if (mode === 'custom' && kf.reference_image_url) return kf.reference_image_url;

    // Auto select: use previous keyframe image or shot image
    if (mode === 'auto_select') {
      if (kf.frame_index > 0) {
        const prevKf = keyframes.find((k) => k.frame_index === kf.frame_index - 1);
        if (prevKf?.image_url) return prevKf.image_url;
      }
      return shotImageUrl || null;
    }

    return kf.reference_image_url || null;
  };

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <ImageIcon className="h-5 w-5" />
          {t('chapterGenerate.keyframes')}
        </h3>
        <div className="flex items-center gap-2">
          <button
            onClick={handleGenerateDescriptions}
            disabled={isGeneratingDescriptions}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-primary-600 hover:bg-primary-700 text-white text-sm rounded-lg transition-colors disabled:opacity-50"
          >
            {isGeneratingDescriptions ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Sparkles className="h-4 w-4" />
            )}
            {isGeneratingDescriptions
              ? t('chapterGenerate.generatingKeyframeDescriptions')
              : t('chapterGenerate.generateKeyframeDescriptions')}
          </button>
        </div>
      </div>

      {/* Keyframe list */}
      <div className="space-y-3">
        {keyframes.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <ImageIcon className="h-12 w-12 mx-auto mb-2 opacity-50" />
            <p>{t('chapterGenerate.noKeyframes')}</p>
          </div>
        ) : (
          keyframes.map((kf) => {
            const isExpanded = expandedKeyframes.has(kf.frame_index);
            const isGenerating = generatingImages.has(kf.frame_index);
            const isUploading = uploadingImages.has(kf.frame_index);
            const isEditing = editingIndex === kf.frame_index;
            const referenceUrl = getReferenceImageUrl(kf);

            return (
              <div
                  key={kf.frame_index}
                  className="bg-gray-700 rounded-lg overflow-hidden group"
                >
                {/* Keyframe header */}
                <div
                  className="flex items-center gap-3 p-3 cursor-pointer hover:bg-gray-600/50 transition-colors"
                  onClick={() => toggleExpanded(kf.frame_index)}
                >
                  {/* Thumbnail */}
                  <div className="relative w-16 h-16 bg-gray-600 rounded flex items-center justify-center overflow-hidden flex-shrink-0">
                    {kf.image_url ? (
                      <>
                        <img
                          src={kf.image_url}
                          alt={t('chapterGenerate.keyframeImage')}
                          className="w-full h-full object-cover"
                        />
                        {/* 查看大图按钮 */}
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            setPreviewImage(kf.image_url!);
                          }}
                          className="absolute top-0.5 right-0.5 p-1 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all opacity-0 group-hover:opacity-100"
                          title={t('chapterGenerate.viewLargeImage') || '查看大图'}
                        >
                          <Eye className="h-3 w-3" />
                        </button>
                      </>
                    ) : (
                      <ImageIcon className="h-6 w-6 text-gray-400" />
                    )}
                  </div>

                  {/* Info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400">
                        {t('chapterGenerate.keyframeNumber', {
                          index: kf.frame_index + 1,
                        })}
                      </span>
                      {isGenerating && (
                        <span className="flex items-center gap-1 text-xs text-yellow-400">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          {t('chapterGenerate.generating')}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-white truncate">{kf.description}</p>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleGenerateImage(kf.frame_index);
                      }}
                      disabled={isGenerating || isUploading}
                      className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                      title={t('chapterGenerate.generateKeyframeImage')}
                    >
                      {isGenerating ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        fileInputRefs.current[kf.frame_index]?.click();
                      }}
                      disabled={isGenerating || isUploading}
                      className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-500 rounded transition-colors disabled:opacity-50"
                      title={t('chapterGenerate.uploadKeyframeImage')}
                    >
                      {isUploading ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Upload className="h-4 w-4" />
                      )}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDeleteKeyframe(kf.frame_index);
                      }}
                      className="p-1.5 text-gray-400 hover:text-red-400 hover:bg-gray-500 rounded transition-colors"
                      title={t('chapterGenerate.deleteKeyframe')}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    {isExpanded ? (
                      <ChevronUp className="h-4 w-4 text-gray-400" />
                    ) : (
                      <ChevronDown className="h-4 w-4 text-gray-400" />
                    )}
                  </div>
                </div>

                {/* Hidden file input */}
                <input
                  ref={(el) => {
                    fileInputRefs.current[kf.frame_index] = el;
                  }}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) {
                      handleUploadImage(kf.frame_index, file);
                    }
                    e.target.value = '';
                  }}
                />

                {/* Expanded content */}
                {isExpanded && (
                  <div className="border-t border-gray-600 p-3 space-y-3">
                    {/* Description editor */}
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">
                        {t('chapterGenerate.keyframeDescription')}
                      </label>
                      {isEditing ? (
                        <div className="flex gap-2">
                          <textarea
                            value={editDescription}
                            onChange={(e) => setEditDescription(e.target.value)}
                            className="flex-1 bg-gray-600 text-white text-sm rounded px-2 py-1 resize-none"
                            rows={2}
                            placeholder={t('chapterGenerate.keyframeDescriptionPlaceholder')}
                          />
                          <button
                            onClick={() => handleUpdateDescription(kf.frame_index)}
                            className="p-1.5 text-green-400 hover:bg-gray-500 rounded"
                          >
                            <Check className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => {
                              setEditingIndex(null);
                              setEditDescription('');
                            }}
                            className="p-1.5 text-gray-400 hover:bg-gray-500 rounded"
                          >
                            <X className="h-4 w-4" />
                          </button>
                        </div>
                      ) : (
                        <div
                          className="text-sm text-gray-300 cursor-pointer hover:bg-gray-600 rounded px-2 py-1"
                          onClick={() => {
                            setEditingIndex(kf.frame_index);
                            setEditDescription(kf.description);
                          }}
                        >
                          {kf.description || t('chapterGenerate.keyframeDescriptionPlaceholder')}
                          <Edit2 className="h-3 w-3 inline ml-2 text-gray-500" />
                        </div>
                      )}
                    </div>

                    {/* Reference image settings */}
                    <div>
                      <label className="block text-xs text-gray-400 mb-1">
                        {t('chapterGenerate.referenceImage')}
                      </label>
                      <div className="space-y-2">
                        {/* Mode selector */}
                        <div className="flex gap-2">
                          {(['auto_select', 'custom', 'none'] as ReferenceMode[]).map(
                            (mode) => (
                              <button
                                key={mode}
                                onClick={() => handleSetReferenceMode(kf.frame_index, mode)}
                                className={`flex-1 px-2 py-1 text-xs rounded transition-colors ${
                                  referenceModes[kf.frame_index] === mode
                                    ? 'bg-primary-600 text-white'
                                    : 'bg-gray-600 text-gray-300 hover:bg-gray-500'
                                }`}
                              >
                                {mode === 'auto_select' &&
                                  t('chapterGenerate.referenceImageAutoSelect')}
                                {mode === 'custom' &&
                                  t('chapterGenerate.referenceImageCustom')}
                                {mode === 'none' &&
                                  t('chapterGenerate.referenceImageNone')}
                              </button>
                            )
                          )}
                        </div>

                        {/* Reference image preview or upload */}
                        {referenceModes[kf.frame_index] === 'custom' && (
                          <div className="flex gap-2">
                            <button
                              onClick={() => referenceInputRefs.current[kf.frame_index]?.click()}
                              className="flex items-center gap-1 px-2 py-1 bg-gray-600 hover:bg-gray-500 text-gray-300 text-xs rounded transition-colors"
                            >
                              <Upload className="h-3 w-3" />
                              {t('chapterGenerate.referenceImageUpload')}
                            </button>
                            <input
                              ref={(el) => {
                                referenceInputRefs.current[kf.frame_index] = el;
                              }}
                              type="file"
                              accept="image/png,image/jpeg,image/webp"
                              className="hidden"
                              onChange={(e) => {
                                const file = e.target.files?.[0];
                                if (file) {
                                  handleUploadReferenceImage(kf.frame_index, file);
                                }
                                e.target.value = '';
                              }}
                            />
                          </div>
                        )}

                        {/* Reference image preview */}
                        {referenceUrl && referenceModes[kf.frame_index] !== 'none' && (
                          <div className="mt-2">
                            <p className="text-xs text-gray-500 mb-1">
                              {t('chapterGenerate.referenceImagePreview')}
                            </p>
                            <div className="relative inline-block group/ref">
                              <img
                                src={referenceUrl}
                                alt={t('chapterGenerate.referenceImage')}
                                className="w-24 h-24 object-cover rounded border border-gray-600"
                              />
                              {/* 查看大图按钮 */}
                              <button
                                onClick={() => setPreviewImage(referenceUrl)}
                                className="absolute top-1 right-1 p-1 bg-black/60 hover:bg-black/80 rounded-full text-white hover:text-blue-400 transition-all opacity-0 group-hover/ref:opacity-100"
                                title={t('chapterGenerate.viewLargeImage') || '查看大图'}
                              >
                                <Eye className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Add new keyframe */}
      <div className="mt-4 pt-4 border-t border-gray-700">
        {isAddingKeyframe ? (
          <div className="flex gap-2">
            <textarea
              value={newKeyframeDescription}
              onChange={(e) => setNewKeyframeDescription(e.target.value)}
              className="flex-1 bg-gray-700 text-white text-sm rounded px-3 py-2 resize-none"
              rows={2}
              placeholder={t('chapterGenerate.keyframeDescriptionPlaceholder')}
              autoFocus
            />
            <button
              onClick={handleAddKeyframe}
              disabled={!newKeyframeDescription.trim()}
              className="px-3 py-1 bg-green-600 hover:bg-green-700 text-white text-sm rounded transition-colors disabled:opacity-50"
            >
              <Check className="h-4 w-4" />
            </button>
            <button
              onClick={() => {
                setIsAddingKeyframe(false);
                setNewKeyframeDescription('');
              }}
              className="px-3 py-1 bg-gray-600 hover:bg-gray-500 text-white text-sm rounded transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        ) : (
          <button
            onClick={() => setIsAddingKeyframe(true)}
            className="flex items-center gap-1.5 px-3 py-2 w-full bg-gray-700 hover:bg-gray-600 text-gray-300 text-sm rounded-lg transition-colors"
          >
            <Plus className="h-4 w-4" />
            {t('chapterGenerate.addKeyframe')}
          </button>
        )}
      </div>

      {/* Image Preview Modal */}
      <ImagePreviewModal
        isOpen={!!previewImage}
        url={previewImage}
        onClose={() => setPreviewImage(null)}
        showDownload={true}
      />
    </div>
  );
}