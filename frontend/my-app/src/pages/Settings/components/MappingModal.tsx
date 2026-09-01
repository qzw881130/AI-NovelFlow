import { useState, useEffect } from 'react';
import { useTranslation } from '../../../stores/i18nStore';
import { toast } from '../../../stores/toastStore';
import { workflowApi } from '../../../api/workflows';
import type { Workflow, AvailableNodes } from '../types';

interface MappingForm {
  promptNodeId: string;
  saveImageNodeId: string;
  widthNodeId: string;
  heightNodeId: string;
  videoSaveNodeId: string;
  maxSideNodeId: string;
  megapixelsNodeId: string;
  megapixelsValue: string;
  referenceImageNodeId: string;
  frameCountNodeId: string;
  firstImageNodeId: string;
  lastImageNodeId: string;
  characterReferenceImageNodeId: string;
  sceneReferenceImageNodeId: string;
  propReferenceImageNodeId: string;
  customReferenceImageNodes: string[];
  // 音色设计相关节点
  voicePromptNodeId: string;
  refTextNodeId: string;
  saveAudioNodeId: string;
  // 音频生成相关节点
  referenceAudioNodeId: string;
  textNodeId: string;
  emotionPromptNodeId: string;
  // 关键帧节点（视频生成工作流）
  keyframeNodes: string[];
  // 时长秒数节点（视频生成工作流）
  durationSecondsNodeId: string;
}

interface MappingModalProps {
  workflow: Workflow | null;
  onClose: () => void;
  onSuccess: () => void;
}

const MEGAPIXEL_OPTIONS = [
  { value: '0.2', output: '608x352' },
  { value: '0.3', output: '736x416' },
  { value: '0.4', output: '864x480' },
  { value: '0.5', output: '960x544' },
  { value: '0.6', output: '1056x608' },
  { value: '0.7', output: '1152x640' },
  { value: '0.8', output: '1216x672' },
  { value: '0.9', output: '1280x736' },
  { value: '0.98', output: '1344x768' },
  { value: '1.0', output: '1376x768' },
  { value: '1.2', output: '1504x832' },
  { value: '1.5', output: '1664x928' },
  { value: '1.8', output: '1824x1024' },
  { value: '2.0', output: '1920x1088' },
];

const isSingleFrameVideoType = (type?: string) => ['video', 'three_frame_video', 'four_frame_video'].includes(type || '');
const isFirstLastVideoType = (type?: string) => ['transition', 'first_last_video'].includes(type || '');
const isShotImageType = (type?: string) => ['shot', 'shot_scene', 'shot_character_scene', 'shot_scene_prop'].includes(type || '');
const getRequiredKeyframeCount = (type?: string) => {
  if (type === 'three_frame_video') return 2;
  if (type === 'four_frame_video') return 3;
  return 0;
};
const isMultiFrameVideoType = (type?: string) => ['three_frame_video', 'four_frame_video'].includes(type || '');

export function MappingModal({ workflow, onClose, onSuccess }: MappingModalProps) {
  const { t } = useTranslation();
  const [mappingForm, setMappingForm] = useState<MappingForm>({
    promptNodeId: '',
    saveImageNodeId: '',
    widthNodeId: '',
    heightNodeId: '',
    videoSaveNodeId: '',
    maxSideNodeId: '',
    megapixelsNodeId: '',
    megapixelsValue: '0.4',
    referenceImageNodeId: '',
    frameCountNodeId: '',
    firstImageNodeId: '',
    lastImageNodeId: '',
    characterReferenceImageNodeId: '',
    sceneReferenceImageNodeId: '',
    propReferenceImageNodeId: '',
    customReferenceImageNodes: [],
    voicePromptNodeId: '',
    refTextNodeId: '',
    saveAudioNodeId: '',
    referenceAudioNodeId: '',
    textNodeId: '',
    emotionPromptNodeId: '',
    keyframeNodes: [],
    durationSecondsNodeId: ''
  });
  const [availableNodes, setAvailableNodes] = useState<AvailableNodes>({
    clipTextEncode: [],
    saveImage: [],
    easyInt: [],
    easyFloat: [],
    crPromptText: [],
    vhsVideoCombine: [],
    saveVideo: [],
    loadImage: [],
    qwen3TtsVoiceDesign: [],
    saveAudio: [],
    loadAudio: [],
    qwen3TtsVoiceClone: [],
    previewAudio: []
  });
  const [workflowJsonData, setWorkflowJsonData] = useState<Record<string, any>>({});
  const [selectedNodeId, setSelectedNodeId] = useState<string>('');
  const [savingMapping, setSavingMapping] = useState(false);

  useEffect(() => {
    if (workflow) {
      loadWorkflowMapping(workflow);
    }
  }, [workflow]);

  const loadWorkflowMapping = async (wf: Workflow) => {
    try {
      const result = await workflowApi.fetch(wf.id);
      if (result.success && result.data) {
        const wfData = result.data as any;
        const mapping = wfData.nodeMapping || {};
        const workflowJson = wfData.workflowJson;
        
        if (workflowJson) {
          try {
            const workflowObj = typeof workflowJson === 'string' ? JSON.parse(workflowJson) : workflowJson;
            
            setWorkflowJsonData(workflowObj);
            
            const clipTextEncode: string[] = [];
            const saveImage: string[] = [];
            const easyInt: string[] = [];
            const easyFloat: string[] = [];
            const crPromptText: string[] = [];
            const vhsVideoCombine: string[] = [];
            const saveVideo: string[] = [];
            const loadImage: string[] = [];
            const qwen3TtsVoiceDesign: string[] = [];
            const saveAudio: string[] = [];
            const loadAudio: string[] = [];
            const qwen3TtsVoiceClone: string[] = [];
            const previewAudio: string[] = [];

            for (const [nodeId, node] of Object.entries(workflowObj)) {
              if (typeof node === 'object' && node !== null) {
                const classType = (node as any).class_type || '';
                const metaTitle = (node as any)._meta?.title || '';

                if (classType === 'CLIPTextEncode' || classType === 'CR Text' || isStringValueNode(classType, metaTitle, (node as any).inputs)) {
                  clipTextEncode.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'SaveImage') {
                  saveImage.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'easy int' || classType === 'JWInteger' || classType === 'INTConstant') {
                  easyInt.push(`${nodeId} (${metaTitle || classType})`);
                } else if (isFloatValueNode(classType, metaTitle, (node as any).inputs)) {
                  easyFloat.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'CR Prompt Text') {
                  crPromptText.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'VHS_VideoCombine') {
                  vhsVideoCombine.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'SaveVideo') {
                  saveVideo.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'LoadImage') {
                  loadImage.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'TDQwen3TTSVoiceDesign') {
                  qwen3TtsVoiceDesign.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'SaveAudio') {
                  saveAudio.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'PreviewAudio') {
                  previewAudio.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'LoadAudio') {
                  loadAudio.push(`${nodeId} (${metaTitle || classType})`);
                } else if (classType === 'TDQwen3TTSVoiceClone') {
                  qwen3TtsVoiceClone.push(`${nodeId} (${metaTitle || classType})`);
                }
              }
            }

            setAvailableNodes({ clipTextEncode, saveImage, easyInt, easyFloat, crPromptText, vhsVideoCombine, saveVideo, loadImage, qwen3TtsVoiceDesign, saveAudio, previewAudio, loadAudio, qwen3TtsVoiceClone });
            
            // 提取自定义参考图节点
            const customReferenceImageNodes: string[] = [];
            for (let i = 1; ; i++) {
              const nodeId = mapping[`custom_reference_image_node_${i}`];
              if (!nodeId) break;
              customReferenceImageNodes.push(nodeId);
            }

            // 提取关键帧节点（视频生成工作流）
            const keyframeNodes: string[] = [];
            for (let i = 1; ; i++) {
              const nodeId = mapping[`keyframe_node_${i}`];
              if (!nodeId) break;
              keyframeNodes.push(nodeId);
            }

            if (isSingleFrameVideoType(wf.type)) {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: mapping.video_save_node_id || '',
                maxSideNodeId: mapping.max_side_node_id || '',
                megapixelsNodeId: mapping.megapixels_node_id || '',
                megapixelsValue: mapping.megapixels_value || '0.4',
                referenceImageNodeId: mapping.reference_image_node_id || '',
                frameCountNodeId: mapping.frame_count_node_id || '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: mapping.reference_audio_node_id || '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes,
                durationSecondsNodeId: mapping.duration_seconds_node_id || ''
              });
            } else if (isFirstLastVideoType(wf.type)) {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: mapping.video_save_node_id || '',
                maxSideNodeId: '',
                megapixelsNodeId: mapping.megapixels_node_id || '',
                megapixelsValue: mapping.megapixels_value || '0.4',
                referenceImageNodeId: '',
                frameCountNodeId: mapping.frame_count_node_id || '',
                firstImageNodeId: mapping.first_image_node_id || '',
                lastImageNodeId: mapping.last_image_node_id || '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: mapping.duration_seconds_node_id || ''
              });
            } else if (isShotImageType(wf.type)) {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: mapping.width_node_id || '',
                heightNodeId: mapping.height_node_id || '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: mapping.reference_image_node_id || '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: mapping.character_reference_image_node_id || '',
                sceneReferenceImageNodeId: mapping.scene_reference_image_node_id || '',
                propReferenceImageNodeId: mapping.prop_reference_image_node_id || '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            } else if (wf.type === 'voice_design') {
              setMappingForm({
                promptNodeId: '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: mapping.voice_prompt_node_id || '',
                refTextNodeId: mapping.ref_text_node_id || '',
                saveAudioNodeId: mapping.save_audio_node_id || '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            } else if (wf.type === 'audio') {
              setMappingForm({
                promptNodeId: '',
                saveImageNodeId: '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: mapping.save_audio_node_id || '',
                referenceAudioNodeId: mapping.reference_audio_node_id || '',
                textNodeId: mapping.text_node_id || '',
                emotionPromptNodeId: mapping.emotion_prompt_node_id || '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            } else if (wf.type === 'keyframe_image') {
              // 关键帧图片生成工作流
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: mapping.reference_image_node_id || '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            } else if (wf.type === 'single_image_edit') {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: mapping.load_image_node_id || '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            } else {
              setMappingForm({
                promptNodeId: mapping.prompt_node_id || '',
                saveImageNodeId: mapping.save_image_node_id || '',
                widthNodeId: '',
                heightNodeId: '',
                videoSaveNodeId: '',
                maxSideNodeId: '',
                megapixelsNodeId: '',
                megapixelsValue: '0.4',
                referenceImageNodeId: '',
                frameCountNodeId: '',
                firstImageNodeId: '',
                lastImageNodeId: '',
                characterReferenceImageNodeId: '',
                sceneReferenceImageNodeId: '',
                propReferenceImageNodeId: '',
                customReferenceImageNodes,
                voicePromptNodeId: '',
                refTextNodeId: '',
                saveAudioNodeId: '',
                referenceAudioNodeId: '',
                textNodeId: '',
                emotionPromptNodeId: '',
                keyframeNodes: [],
                durationSecondsNodeId: ''
              });
            }
          } catch (e) {
            console.error('解析工作流 JSON 失败:', e);
          }
        }
      }
    } catch (error) {
      console.error('加载工作流映射失败:', error);
    }
  };

  const handleSaveMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!workflow) return;
    
    setSavingMapping(true);
    try {
      let nodeMapping: Record<string, string | null> = {};
      
      if (isSingleFrameVideoType(workflow.type)) {
        const hasMaxSide = Boolean(mappingForm.maxSideNodeId);
        const hasMegapixels = Boolean(mappingForm.megapixelsNodeId);
        if (hasMaxSide === hasMegapixels) {
          toast.error('最长边节点和 Megapixels 必须且只能配置其中一个');
          setSavingMapping(false);
          return;
        }
        const requiredKeyframeCount = getRequiredKeyframeCount(workflow.type);
        const hasRequiredKeyframes = Array.from({ length: requiredKeyframeCount }).every((_, index) => Boolean(mappingForm.keyframeNodes[index]));
        if (!hasRequiredKeyframes) {
          toast.error(workflow.type === 'three_frame_video' ? '三帧生视频必须配置参考图片节点 2 和 3' : '四帧生视频必须配置参考图片节点 2、3 和 4');
          setSavingMapping(false);
          return;
        }

        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          video_save_node_id: mappingForm.videoSaveNodeId || null,
          max_side_node_id: mappingForm.maxSideNodeId || null,
          megapixels_node_id: mappingForm.megapixelsNodeId || null,
          megapixels_value: mappingForm.megapixelsNodeId ? mappingForm.megapixelsValue : null,
          reference_image_node_id: mappingForm.referenceImageNodeId || null,
          frame_count_node_id: mappingForm.frameCountNodeId || null,
          reference_audio_node_id: mappingForm.referenceAudioNodeId || null,
          duration_seconds_node_id: mappingForm.durationSecondsNodeId || null
        };
        // 添加关键帧节点
        mappingForm.keyframeNodes.forEach((nodeId, index) => {
          nodeMapping[`keyframe_node_${index + 1}`] = nodeId || null;
        });
      } else if (isFirstLastVideoType(workflow.type)) {
        const hasFrameCount = Boolean(mappingForm.frameCountNodeId);
        const hasDurationSeconds = Boolean(mappingForm.durationSecondsNodeId);
        if (hasFrameCount === hasDurationSeconds) {
          toast.error('总帧数节点和时长秒数节点必须且只能配置其中一个');
          setSavingMapping(false);
          return;
        }

        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          first_image_node_id: mappingForm.firstImageNodeId || null,
          last_image_node_id: mappingForm.lastImageNodeId || null,
          frame_count_node_id: mappingForm.frameCountNodeId || null,
          duration_seconds_node_id: mappingForm.durationSecondsNodeId || null,
          megapixels_node_id: mappingForm.megapixelsNodeId || null,
          megapixels_value: mappingForm.megapixelsNodeId ? mappingForm.megapixelsValue : null,
          video_save_node_id: mappingForm.videoSaveNodeId || null
        };
      } else if (isShotImageType(workflow.type)) {
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null,
          width_node_id: mappingForm.widthNodeId || null,
          height_node_id: mappingForm.heightNodeId || null,
          scene_reference_image_node_id: mappingForm.sceneReferenceImageNodeId || null
        };
        if (workflow.type !== 'shot_scene' && workflow.type !== 'shot_scene_prop') {
          nodeMapping.character_reference_image_node_id = mappingForm.characterReferenceImageNodeId || null;
        }
        if (workflow.type === 'shot_scene_prop') {
          nodeMapping.prop_reference_image_node_id = mappingForm.propReferenceImageNodeId || null;
        }
      } else if (workflow.type === 'voice_design') {
        nodeMapping = {
          voice_prompt_node_id: mappingForm.voicePromptNodeId || null,
          ref_text_node_id: mappingForm.refTextNodeId || null,
          save_audio_node_id: mappingForm.saveAudioNodeId || null
        };
      } else if (workflow.type === 'audio') {
        nodeMapping = {
          reference_audio_node_id: mappingForm.referenceAudioNodeId || null,
          text_node_id: mappingForm.textNodeId || null,
          emotion_prompt_node_id: mappingForm.emotionPromptNodeId || null,
          save_audio_node_id: mappingForm.saveAudioNodeId || null
        };
      } else if (workflow.type === 'keyframe_image') {
        // 关键帧图片生成工作流
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null,
          reference_image_node_id: mappingForm.referenceImageNodeId || null
        };
      } else if (workflow.type === 'single_image_edit') {
        nodeMapping = {
          load_image_node_id: mappingForm.referenceImageNodeId || null,
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null
        };
      } else {
        nodeMapping = {
          prompt_node_id: mappingForm.promptNodeId || null,
          save_image_node_id: mappingForm.saveImageNodeId || null
        };
      }
      
      // 添加自定义参考图节点
      if (workflow.type === 'shot') {
        mappingForm.customReferenceImageNodes.forEach((nodeId, index) => {
          nodeMapping[`custom_reference_image_node_${index + 1}`] = nodeId || null;
        });
      }
      
      const data = await workflowApi.update(workflow.id, { nodeMapping } as any);
      
      if (data.success) {
        onClose();
        onSuccess();
        toast.success(t('systemSettings.configSaved'));
      } else {
        const errorMsg = (data as any)?.detail || t('systemSettings.configSaveFailed');
        console.error('保存映射配置失败:', data);
        toast.error(errorMsg);
      }
    } catch (error) {
      console.error('保存映射配置失败:', error);
      toast.error(t('systemSettings.configSaveFailed'));
    } finally {
      setSavingMapping(false);
    }
  };

  const handleNodeSelect = (value: string, field: keyof MappingForm) => {
    setMappingForm({ ...mappingForm, [field]: value });
    if (value) setSelectedNodeId(value);
  };

  const handleMaxSideNodeSelect = (value: string) => {
    setMappingForm({
      ...mappingForm,
      maxSideNodeId: value,
      megapixelsNodeId: value ? '' : mappingForm.megapixelsNodeId
    });
    if (value) setSelectedNodeId(value);
  };

  const handleMegapixelsNodeSelect = (value: string) => {
    setMappingForm({
      ...mappingForm,
      megapixelsNodeId: value,
      maxSideNodeId: value ? '' : mappingForm.maxSideNodeId,
      megapixelsValue: mappingForm.megapixelsValue || '0.4'
    });
    if (value) setSelectedNodeId(value);
  };

  const handleFrameCountNodeSelect = (value: string) => {
    setMappingForm({
      ...mappingForm,
      frameCountNodeId: value,
      durationSecondsNodeId: isFirstLastVideoType(workflow?.type) && value ? '' : mappingForm.durationSecondsNodeId
    });
    if (value) setSelectedNodeId(value);
  };

  const handleDurationSecondsNodeSelect = (value: string) => {
    setMappingForm({
      ...mappingForm,
      durationSecondsNodeId: value,
      frameCountNodeId: isFirstLastVideoType(workflow?.type) && value ? '' : mappingForm.frameCountNodeId
    });
    if (value) setSelectedNodeId(value);
  };

  const handleNodeFocus = (value: string) => {
    if (value) setSelectedNodeId(value);
  };

  const handleAddCustomReferenceNode = () => {
    setMappingForm({
      ...mappingForm,
      customReferenceImageNodes: [...mappingForm.customReferenceImageNodes, '']
    });
  };

  const handleRemoveCustomReferenceNode = (index: number) => {
    const newCustomNodes = [...mappingForm.customReferenceImageNodes];
    newCustomNodes.splice(index, 1);
    setMappingForm({
      ...mappingForm,
      customReferenceImageNodes: newCustomNodes
    });
  };

  const handleCustomReferenceNodeChange = (value: string, index: number) => {
    const newCustomNodes = [...mappingForm.customReferenceImageNodes];
    newCustomNodes[index] = value;
    setMappingForm({
      ...mappingForm,
      customReferenceImageNodes: newCustomNodes
    });
    if (value) setSelectedNodeId(value);
  };

  // 关键帧节点处理函数（视频生成工作流）
  const handleAddKeyframeNode = () => {
    setMappingForm({
      ...mappingForm,
      keyframeNodes: [...mappingForm.keyframeNodes, '']
    });
  };

  const handleRemoveKeyframeNode = (index: number) => {
    const newNodes = [...mappingForm.keyframeNodes];
    newNodes.splice(index, 1);
    setMappingForm({
      ...mappingForm,
      keyframeNodes: newNodes
    });
  };

  const handleKeyframeNodeChange = (value: string, index: number) => {
    const newNodes = [...mappingForm.keyframeNodes];
    newNodes[index] = value;
    setMappingForm({
      ...mappingForm,
      keyframeNodes: newNodes
    });
    if (value) setSelectedNodeId(value);
  };

  if (!workflow) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg p-6 w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <h3 className="text-lg font-medium mb-4">
          {t('systemSettings.workflow.nodeMapping')} - {workflow.name}
        </h3>
        <div className="flex gap-4 flex-1 min-h-0">
          {/* 左侧: 选中节点的 JSON 数据显示 */}
          <div className="w-1/2 border rounded-lg overflow-hidden flex flex-col">
            <div className="bg-gray-50 px-3 py-2 border-b text-sm font-medium text-gray-700">
              {selectedNodeId ? `Node: ${selectedNodeId}` : t('systemSettings.workflow.selectNodeToView')}
            </div>
            <div className="flex-1 overflow-auto p-2 bg-gray-900">
              <pre className="text-xs text-gray-300 whitespace-pre-wrap font-mono">
                {selectedNodeId && workflowJsonData[selectedNodeId]
                  ? JSON.stringify({ [selectedNodeId]: workflowJsonData[selectedNodeId] }, null, 2)
                  : selectedNodeId 
                    ? t('systemSettings.workflow.nodeNotFound')
                    : t('systemSettings.workflow.selectNodeToView')}
              </pre>
            </div>
          </div>
          
          {/* 右侧: 映射表单 */}
          <div className="w-1/2 overflow-y-auto">
            <form onSubmit={handleSaveMapping} className="space-y-4">
              {/* 根据工作流类型显示不同的映射字段 */}
              {(workflow.type === 'character' || workflow.type === 'scene' || workflow.type === 'prop') && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.promptInputNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text"
                    value={mappingForm.promptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.imageSaveNode')}
                    nodeTypeHint="SaveImage"
                    value={mappingForm.saveImageNodeId}
                    options={availableNodes.saveImage}
                    onChange={(v) => handleNodeSelect(v, 'saveImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                </>
              )}

              {isShotImageType(workflow.type) && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.promptInputNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text"
                    value={mappingForm.promptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.imageSaveNode')}
                    nodeTypeHint="SaveImage"
                    value={mappingForm.saveImageNodeId}
                    options={availableNodes.saveImage}
                    onChange={(v) => handleNodeSelect(v, 'saveImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <div className="grid grid-cols-2 gap-4">
                    <NodeSelectField
                      label={t('systemSettings.workflow.widthNode')}
                      nodeTypeHint="easy int, JWInteger, INTConstant"
                      value={mappingForm.widthNodeId}
                      options={availableNodes.easyInt}
                      onChange={(v) => handleNodeSelect(v, 'widthNodeId')}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                    <NodeSelectField
                      label={t('systemSettings.workflow.heightNode')}
                      nodeTypeHint="easy int, JWInteger, INTConstant"
                      value={mappingForm.heightNodeId}
                      options={availableNodes.easyInt}
                      onChange={(v) => handleNodeSelect(v, 'heightNodeId')}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    {(workflow.type === 'shot' || workflow.type === 'shot_character_scene') && (
                      <NodeSelectField
                        label={t('systemSettings.workflow.characterReferenceNode')}
                        nodeTypeHint="LoadImage"
                        value={mappingForm.characterReferenceImageNodeId}
                        options={availableNodes.loadImage}
                        onChange={(v) => handleNodeSelect(v, 'characterReferenceImageNodeId')}
                        onFocus={handleNodeFocus}
                        t={t}
                      />
                    )}
                    <NodeSelectField
                      label={t('systemSettings.workflow.sceneReferenceNode')}
                      nodeTypeHint="LoadImage"
                      value={mappingForm.sceneReferenceImageNodeId}
                      options={availableNodes.loadImage}
                      onChange={(v) => handleNodeSelect(v, 'sceneReferenceImageNodeId')}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                    {workflow.type === 'shot_scene_prop' && (
                      <NodeSelectField
                        label={t('systemSettings.workflow.propReferenceNode')}
                        nodeTypeHint="LoadImage"
                        value={mappingForm.propReferenceImageNodeId}
                        options={availableNodes.loadImage}
                        onChange={(v) => handleNodeSelect(v, 'propReferenceImageNodeId')}
                        onFocus={handleNodeFocus}
                        t={t}
                      />
                    )}
                  </div>
                  
                  {/* 自定义参考图节点 */}
                  {workflow.type === 'shot' && <div className="mt-4">
                    <div className="flex justify-between items-center mb-2">
                      <h4 className="text-sm font-medium text-gray-700">{t('systemSettings.workflow.customReferenceImageNodes')}</h4>
                      <button
                        type="button"
                        onClick={handleAddCustomReferenceNode}
                        className="text-sm text-blue-600 hover:text-blue-800"
                      >
                        {t('common.add')}
                      </button>
                    </div>
                    <p className="text-xs text-amber-600 mb-2">{t('systemSettings.workflow.referenceImageNodeDisconnectTip')}</p>
                    {mappingForm.customReferenceImageNodes.map((nodeId, index) => (
                      <div key={index} className="flex gap-2 mb-2">
                        <div className="flex-1">
                          <NodeSelectField
                            label={`${t('systemSettings.workflow.referenceImageNode')} ${index + 1}`}
                            nodeTypeHint="LoadImage"
                            value={nodeId}
                            options={availableNodes.loadImage}
                            onChange={(v) => handleCustomReferenceNodeChange(v, index)}
                            onFocus={handleNodeFocus}
                            t={t}
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => handleRemoveCustomReferenceNode(index)}
                          className="text-sm text-red-600 hover:text-red-800 mt-6"
                        >
                          {t('common.remove')}
                        </button>
                      </div>
                    ))}
                  </div>}
                </>
              )}

              {isSingleFrameVideoType(workflow.type) && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.promptInputNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text"
                    value={mappingForm.promptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.videoSaveNode')}
                    nodeTypeHint="VHS_VideoCombine, SaveVideo"
                    value={mappingForm.videoSaveNodeId}
                    options={[...availableNodes.vhsVideoCombine, ...availableNodes.saveVideo]}
                    onChange={(v) => handleNodeSelect(v, 'videoSaveNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.maxSideNode')}
                    nodeTypeHint="easy int, JWInteger, INTConstant"
                    value={mappingForm.maxSideNodeId}
                    options={availableNodes.easyInt}
                    onChange={handleMaxSideNodeSelect}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <div>
                    <NodeSelectField
                      label="Megapixels 节点"
                      nodeTypeHint="Float, easy float, JWFloat, FloatConstant"
                      value={mappingForm.megapixelsNodeId}
                      options={availableNodes.easyFloat}
                      onChange={handleMegapixelsNodeSelect}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                    {mappingForm.megapixelsNodeId && (
                      <div className="mt-2 grid grid-cols-[1fr_auto] gap-3 items-end">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Megapixels</label>
                          <select
                            value={mappingForm.megapixelsValue}
                            onChange={(e) => setMappingForm({ ...mappingForm, megapixelsValue: e.target.value })}
                            className="input-field"
                          >
                            {MEGAPIXEL_OPTIONS.map(option => (
                              <option key={option.value} value={option.value}>{option.value}</option>
                            ))}
                          </select>
                        </div>
                        <div className="text-sm text-gray-600 pb-2 whitespace-nowrap">
                          output: {MEGAPIXEL_OPTIONS.find(option => option.value === mappingForm.megapixelsValue)?.output || '864x480'}
                        </div>
                      </div>
                    )}
                    <p className="text-xs text-amber-600 mt-1">最长边节点和 Megapixels 只能配置其中一个，且必须配置一个。</p>
                  </div>
                  <NodeSelectField
                    label={isMultiFrameVideoType(workflow.type) ? '参考图片节点1 (LoadImage)' : t('systemSettings.workflow.referenceImageNode')}
                    nodeTypeHint="LoadImage"
                    value={mappingForm.referenceImageNodeId}
                    options={availableNodes.loadImage}
                    onChange={(v) => handleNodeSelect(v, 'referenceImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  {getRequiredKeyframeCount(workflow.type) > 0 && (
                    <div className="mt-4">
                      <p className="text-xs text-gray-500 mb-2">
                        {workflow.type === 'three_frame_video' ? '三帧生视频需要 3 个参考图片 LoadImage 节点。' : '四帧生视频需要 4 个参考图片 LoadImage 节点。'}
                      </p>
                      {Array.from({ length: getRequiredKeyframeCount(workflow.type) }).map((_, index) => (
                        <div key={index} className="mb-2">
                          <NodeSelectField
                            label={`参考图片节点${index + 2} (LoadImage)`}
                            nodeTypeHint="LoadImage"
                            value={mappingForm.keyframeNodes[index] || ''}
                            options={availableNodes.loadImage}
                            onChange={(v) => handleKeyframeNodeChange(v, index)}
                            onFocus={handleNodeFocus}
                            t={t}
                          />
                        </div>
                      ))}
                    </div>
                  )}
                  <NodeSelectField
                    label={t('systemSettings.workflow.frameCountNode')}
                    nodeTypeHint="easy int, JWInteger, INTConstant"
                    value={mappingForm.frameCountNodeId}
                    options={availableNodes.easyInt}
                    onChange={handleFrameCountNodeSelect}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.durationSecondsNode')}
                    nodeTypeHint="easy int, JWInteger, INTConstant, Float, easy float"
                    value={mappingForm.durationSecondsNodeId}
                    options={[...availableNodes.easyInt, ...availableNodes.easyFloat]}
                    onChange={handleDurationSecondsNodeSelect}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.referenceAudioNode')}
                    nodeTypeHint="LoadAudio"
                    value={mappingForm.referenceAudioNodeId}
                    options={availableNodes.loadAudio}
                    onChange={(v) => handleNodeSelect(v, 'referenceAudioNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />

                  {/* 额外关键帧节点配置 */}
                  {workflow.type === 'video' && <div className="mt-4">
                    <div className="flex justify-between items-center mb-2">
                      <h4 className="text-sm font-medium text-gray-700">{t('systemSettings.workflow.keyframeNodes')}</h4>
                      <button
                        type="button"
                        onClick={handleAddKeyframeNode}
                        className="text-sm text-blue-600 hover:text-blue-800"
                      >
                        {t('common.add')}
                      </button>
                    </div>
                    <p className="text-xs text-gray-500 mb-2">{t('systemSettings.workflow.keyframeNodesHint')}</p>
                    {mappingForm.keyframeNodes.map((nodeId, index) => (
                      <div key={index} className="flex gap-2 mb-2">
                        <div className="flex-1">
                          <NodeSelectField
                            label={`${t('systemSettings.workflow.keyframeNode')} ${index + 1}`}
                            nodeTypeHint="LoadImage"
                            value={nodeId}
                            options={availableNodes.loadImage}
                            onChange={(v) => handleKeyframeNodeChange(v, index)}
                            onFocus={handleNodeFocus}
                            t={t}
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => handleRemoveKeyframeNode(index)}
                          className="text-sm text-red-600 hover:text-red-800 mt-6"
                        >
                          {t('common.remove')}
                        </button>
                      </div>
                    ))}
                  </div>}
                </>
              )}

              {isFirstLastVideoType(workflow.type) && (
                <>
                  {workflow.type === 'first_last_video' && (
                    <NodeSelectField
                      label={t('systemSettings.workflow.promptInputNode')}
                      nodeTypeHint="CLIPTextEncode, CR Text"
                      value={mappingForm.promptNodeId}
                      options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                      onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                  )}
                  <NodeSelectField
                    label={t('systemSettings.workflow.firstImageNode')}
                    nodeTypeHint="LoadImage"
                    value={mappingForm.firstImageNodeId}
                    options={availableNodes.loadImage}
                    onChange={(v) => handleNodeSelect(v, 'firstImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.lastImageNode')}
                    nodeTypeHint="LoadImage"
                    value={mappingForm.lastImageNodeId}
                    options={availableNodes.loadImage}
                    onChange={(v) => handleNodeSelect(v, 'lastImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.videoSaveNode')}
                    nodeTypeHint="VHS_VideoCombine, SaveVideo"
                    value={mappingForm.videoSaveNodeId}
                    options={[...availableNodes.vhsVideoCombine, ...availableNodes.saveVideo]}
                    onChange={(v) => handleNodeSelect(v, 'videoSaveNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <div>
                    <NodeSelectField
                      label="Megapixels 节点"
                      nodeTypeHint="Float, easy float, JWFloat, FloatConstant"
                      value={mappingForm.megapixelsNodeId}
                      options={availableNodes.easyFloat}
                      onChange={(v) => handleNodeSelect(v, 'megapixelsNodeId')}
                      onFocus={handleNodeFocus}
                      t={t}
                    />
                    {mappingForm.megapixelsNodeId && (
                      <div className="mt-2 grid grid-cols-[1fr_auto] gap-3 items-end">
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">Megapixels</label>
                          <select
                            value={mappingForm.megapixelsValue}
                            onChange={(e) => setMappingForm({ ...mappingForm, megapixelsValue: e.target.value })}
                            className="input-field"
                          >
                            {MEGAPIXEL_OPTIONS.map(option => (
                              <option key={option.value} value={option.value}>{option.value}</option>
                            ))}
                          </select>
                        </div>
                        <div className="text-sm text-gray-600 pb-2 whitespace-nowrap">
                          output: {MEGAPIXEL_OPTIONS.find(option => option.value === mappingForm.megapixelsValue)?.output || '864x480'}
                        </div>
                      </div>
                    )}
                  </div>
                  <NodeSelectField
                    label={t('systemSettings.workflow.frameCountNode')}
                    nodeTypeHint="easy int, JWInteger, INTConstant"
                    value={mappingForm.frameCountNodeId}
                    options={availableNodes.easyInt}
                    onChange={handleFrameCountNodeSelect}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.durationSecondsNode')}
                    nodeTypeHint="easy int, JWInteger, INTConstant, Float, easy float"
                    value={mappingForm.durationSecondsNodeId}
                    options={[...availableNodes.easyInt, ...availableNodes.easyFloat]}
                    onChange={handleDurationSecondsNodeSelect}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <p className="text-xs text-amber-600">总帧数节点和时长秒数节点只能配置其中一个，且必须配置一个。</p>
                </>
              )}

              {workflow.type === 'voice_design' && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.voicePromptNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text, CR Prompt Text"
                    value={mappingForm.voicePromptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'voicePromptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.refTextNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text, CR Prompt Text"
                    value={mappingForm.refTextNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'refTextNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.saveAudioNode')}
                    nodeTypeHint="SaveAudio, PreviewAudio"
                    value={mappingForm.saveAudioNodeId}
                    options={[...availableNodes.saveAudio, ...availableNodes.previewAudio]}
                    onChange={(v) => handleNodeSelect(v, 'saveAudioNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                </>
              )}

              {workflow.type === 'audio' && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.referenceAudioNode')}
                    nodeTypeHint="LoadAudio"
                    value={mappingForm.referenceAudioNodeId}
                    options={availableNodes.loadAudio}
                    onChange={(v) => handleNodeSelect(v, 'referenceAudioNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.textNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text, CR Prompt Text"
                    value={mappingForm.textNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'textNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.emotionPromptNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text, CR Prompt Text"
                    value={mappingForm.emotionPromptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'emotionPromptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.saveAudioNode')}
                    nodeTypeHint="SaveAudio, PreviewAudio"
                    value={mappingForm.saveAudioNodeId}
                    options={[...availableNodes.saveAudio, ...availableNodes.previewAudio]}
                    onChange={(v) => handleNodeSelect(v, 'saveAudioNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                </>
              )}

              {workflow.type === 'keyframe_image' && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.promptInputNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text"
                    value={mappingForm.promptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.imageSaveNode')}
                    nodeTypeHint="SaveImage"
                    value={mappingForm.saveImageNodeId}
                    options={availableNodes.saveImage}
                    onChange={(v) => handleNodeSelect(v, 'saveImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.referenceImageNode')}
                    nodeTypeHint="LoadImage"
                    value={mappingForm.referenceImageNodeId}
                    options={availableNodes.loadImage}
                    onChange={(v) => handleNodeSelect(v, 'referenceImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                </>
              )}

              {workflow.type === 'single_image_edit' && (
                <>
                  <NodeSelectField
                    label={t('systemSettings.workflow.loadImageNode')}
                    nodeTypeHint="LoadImage"
                    value={mappingForm.referenceImageNodeId}
                    options={availableNodes.loadImage}
                    onChange={(v) => handleNodeSelect(v, 'referenceImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.promptInputNode')}
                    nodeTypeHint="CLIPTextEncode, CR Text"
                    value={mappingForm.promptNodeId}
                    options={[...availableNodes.clipTextEncode, ...availableNodes.crPromptText]}
                    onChange={(v) => handleNodeSelect(v, 'promptNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                  <NodeSelectField
                    label={t('systemSettings.workflow.imageSaveNode')}
                    nodeTypeHint="SaveImage"
                    value={mappingForm.saveImageNodeId}
                    options={availableNodes.saveImage}
                    onChange={(v) => handleNodeSelect(v, 'saveImageNodeId')}
                    onFocus={handleNodeFocus}
                    t={t}
                  />
                </>
              )}

              <div className="flex justify-end gap-3 pt-4">
                <button
                  type="button"
                  onClick={onClose}
                  className="btn-secondary"
                >
                  {t('common.cancel')}
                </button>
                <button
                  type="submit"
                  disabled={savingMapping}
                  className="btn-primary"
                >
                  {savingMapping ? t('common.loading') : t('common.save')}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

// 节点选择字段组件
interface NodeSelectFieldProps {
  label: string;
  nodeTypeHint?: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
  onFocus: (value: string) => void;
  t: (key: string, options?: any) => string;
}

function NodeSelectField({ label, nodeTypeHint, value, options, onChange, onFocus, t }: NodeSelectFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 mb-1">{label}</label>
      {nodeTypeHint && (
        <p className="text-xs text-gray-400 mb-1.5">{t('systemSettings.workflow.nodeTypeHint')}: {nodeTypeHint}</p>
      )}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onFocus={() => onFocus(value)}
        className="input-field"
      >
        <option value="">-- {t('common.select')} --</option>
        {options.map(node => (
          <option key={node} value={node.split(' ')[0]}>{node}</option>
        ))}
      </select>
    </div>
  );
}

function isFloatValueNode(classType: string, metaTitle: string, inputs: Record<string, any> = {}) {
  const classTypeLower = classType.toLowerCase();
  const titleLower = metaTitle.toLowerCase();
  const value = inputs?.value;
  const hasWritableValue = Object.prototype.hasOwnProperty.call(inputs || {}, 'value') && !Array.isArray(value);

  return (
    (hasWritableValue && classTypeLower.includes('float')) ||
    titleLower.includes('megapixels') ||
    titleLower.includes('duration')
  );
}

function isStringValueNode(classType: string, metaTitle: string, inputs: Record<string, any> = {}) {
  const classTypeLower = classType.toLowerCase();
  const titleLower = metaTitle.toLowerCase();
  const value = inputs?.value;
  const hasWritableValue = Object.prototype.hasOwnProperty.call(inputs || {}, 'value') && typeof value === 'string';

  return (
    hasWritableValue &&
    (classTypeLower.includes('string') || classTypeLower === 'string' || titleLower.includes('prompt') || titleLower.includes('input text'))
  );
}
