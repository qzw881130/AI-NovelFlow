/**
 * 角色卡片组件
 */
import { Loader2, User, Trash2, Edit2, Upload, Wand2, Sparkles, Mic, Play, Square, Music, BookOpen } from 'lucide-react';
import { useState, useRef } from 'react';
import { useTranslation } from '../../../stores/i18nStore';
import type { Character } from '../../../types';
import type { CharacterPrompt } from '../types';
import { ASPECT_RATIO_CLASSES } from '../constants';

interface CharacterCardProps {
  character: Character;
  aspectRatio: string;
  highlightedId: string | null;
  generatingId: string | null;
  generatingAppearanceId: string | null;
  uploadingId: string | null;
  generatingVoiceId: string | null;
  uploadingAudioId: string | null;
  characterPrompt?: CharacterPrompt;
  onDelete: (id: string) => void;
  onEdit: (character: Character) => void;
  onGeneratePortrait: (character: Character) => void;
  onGenerateAppearance: (character: Character) => void;
  onUploadImage: (characterId: string) => void;
  onImageClick: (url: string, name: string, characterId: string) => void;
  onGenerateVoice: (character: Character) => void;
  onUploadAudio: (characterId: string) => void;
}

export function CharacterCard({
  character,
  aspectRatio,
  highlightedId,
  generatingId,
  generatingAppearanceId,
  uploadingId,
  generatingVoiceId,
  uploadingAudioId,
  characterPrompt,
  onDelete,
  onEdit,
  onGeneratePortrait,
  onGenerateAppearance,
  onUploadImage,
  onImageClick,
  onGenerateVoice,
  onUploadAudio,
}: CharacterCardProps) {
  const { t } = useTranslation();
  const aspectClass = ASPECT_RATIO_CLASSES[aspectRatio] || 'aspect-video';
  const [isPlayingAudio, setIsPlayingAudio] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const handlePlayAudio = () => {
    if (character.referenceAudioUrl) {
      if (isPlayingAudio) {
        audioRef.current?.pause();
        setIsPlayingAudio(false);
      } else {
        if (!audioRef.current) {
          audioRef.current = new Audio(character.referenceAudioUrl);
          audioRef.current.onended = () => setIsPlayingAudio(false);
        }
        audioRef.current.play();
        setIsPlayingAudio(true);
      }
    }
  };

  return (
    <div
      id={`character-${character.id}`}
      className={`bg-white rounded-lg shadow-sm border overflow-hidden hover:shadow-md transition-all group ${
        highlightedId === character.id
          ? 'ring-4 ring-blue-500 ring-opacity-50 border-blue-500 animate-pulse'
          : character.isNarrator
          ? 'border-purple-300 bg-purple-50/30'
          : 'border-gray-200'
      }`}
    >
      {/* Character Image */}
      <div className={`${aspectClass} bg-gray-100 relative w-full`}>
        {character.imageUrl ? (
          <img
            src={character.imageUrl}
            alt={character.name}
            className="w-full h-full object-cover cursor-pointer"
            onClick={() => onImageClick(character.imageUrl!, character.name, character.id)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            {character.isNarrator ? (
              <BookOpen className="h-20 w-20 text-purple-300" />
            ) : (
              <User className="h-20 w-20 text-gray-300" />
            )}
          </div>
        )}

        {/* Narrator Badge */}
        {character.isNarrator && (
          <div className="absolute top-2 left-2 px-2 py-1 bg-purple-600 text-white text-xs rounded-full flex items-center gap-1">
            <BookOpen className="h-3 w-3" />
            {t('characters.narrator')}
          </div>
        )}

        {/* Status Badge */}
        {character.generatingStatus === 'running' && !character.isNarrator && (
          <div className={`absolute top-2 left-2 px-2 py-1 bg-blue-500 text-white text-xs rounded-full flex items-center gap-1 ${character.isNarrator ? 'left-24' : ''}`}>
            <Loader2 className="h-3 w-3 animate-spin" />
            {t('characters.generating')}
          </div>
        )}
        {character.generatingStatus === 'failed' && (
          <div className={`absolute top-2 left-2 px-2 py-1 bg-red-500 text-white text-xs rounded-full ${character.isNarrator ? 'left-24' : ''}`}>
            {t('characters.generateFailed')}
          </div>
        )}

        {/* Delete Button - 右上角 (旁白角色不显示删除按钮) */}
        {!character.isNarrator && (
          <button
            onClick={() => onDelete(character.id)}
            className="absolute top-2 right-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 transition-colors opacity-0 group-hover:opacity-100"
            title={t('common.delete')}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        )}

        {/* Edit Button - 左下角 */}
        <button
          onClick={() => onEdit(character)}
          className="absolute bottom-2 left-2 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors opacity-0 group-hover:opacity-100"
          title={t('common.edit')}
        >
          <Edit2 className="h-4 w-4" />
        </button>

        {/* 上传按钮 - 左下角（编辑按钮右边） */}
        <button
          onClick={() => onUploadImage(character.id)}
          disabled={uploadingId === character.id}
          className="absolute bottom-2 left-12 p-2 bg-white/90 rounded-lg text-gray-400 hover:text-green-600 hover:bg-green-50 transition-colors disabled:opacity-70 opacity-0 group-hover:opacity-100"
          title={t('characters.uploadImage')}
        >
          {uploadingId === character.id ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
        </button>

        {/* 按钮组 - 右下角 */}
        <div className="absolute bottom-2 right-2 flex gap-1 opacity-0 group-hover:opacity-100">
          {/* 生成音色按钮 */}
          <button
            onClick={() => onGenerateVoice(character)}
            disabled={generatingVoiceId === character.id || !character.voicePrompt}
            className="flex items-center gap-1 px-2 py-1.5 bg-pink-600/90 hover:bg-pink-700 text-white rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-xs"
            title={!character.voicePrompt ? t('characters.needVoicePrompt') : (character.referenceAudioUrl ? t('characters.regenerateVoice') : t('characters.generateVoice'))}
          >
            {generatingVoiceId === character.id ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Mic className="h-3 w-3" />
            )}
          </button>

          {/* AI生成形象 Button */}
          <button
            onClick={() => onGeneratePortrait(character)}
            disabled={generatingId === character.id || character.generatingStatus === 'running'}
            className="flex items-center gap-1 px-2 py-1.5 bg-purple-600/90 hover:bg-purple-700 text-white rounded-lg transition-colors disabled:opacity-70 text-xs"
            title={character.generatingStatus === 'running' ? t('characters.generatingStatus') : (character.imageUrl ? t('characters.regenerate') : t('characters.generatePortrait'))}
          >
            {character.generatingStatus === 'running' || generatingId === character.id ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <Wand2 className="h-3 w-3" />
            )}
          </button>
        </div>

        {/* Loading Overlay */}
        {generatingId === character.id && (
          <div className="absolute inset-0 bg-black bg-opacity-50 flex items-center justify-center">
            <div className="text-center">
              <Loader2 className="h-8 w-8 animate-spin text-white mx-auto" />
              <p className="text-white text-sm mt-2">{t('characters.generating')}</p>
            </div>
          </div>
        )}
      </div>

      {/* Character Info */}
      <div className="p-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900 truncate">
            {character.name}
          </h3>
          <span className="text-xs px-2 py-0.5 bg-gray-100 text-gray-500 rounded">
            {aspectRatio}
          </span>
        </div>

        {/* 角色描述 */}
        {character.description && (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('characters.descriptionLabel')}</p>
            <div className="text-sm text-gray-600 max-h-20 overflow-y-auto pr-1 scrollbar-thin">
              {character.description}
            </div>
          </div>
        )}

        {/* 外貌特征 */}
        {character.appearance ? (
          <div className="mt-3">
            <p className="text-xs text-gray-400 mb-1">{t('characters.appearance')}</p>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-24 overflow-y-auto scrollbar-thin">
              {character.appearance}
            </div>
          </div>
        ) : (
          <div className="mt-3">
            <button
              onClick={() => onGenerateAppearance(character)}
              disabled={generatingAppearanceId === character.id || !character.description}
              className="text-xs inline-flex items-center text-primary-600 hover:text-primary-700 disabled:opacity-50"
            >
              {generatingAppearanceId === character.id ? (
                <>
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                  {t('characters.generatingStatus')}
                </>
              ) : (
                <>
                  <Sparkles className="h-3 w-3 mr-1" />
                  {t('characters.generateAppearance')}
                </>
              )}
            </button>
          </div>
        )}

        {/* 生成提示词 */}
        {characterPrompt && (
          <div className="mt-3 pt-3 border-t border-gray-100">
            <div className="flex items-center justify-between mb-1">
              <p className="text-xs text-gray-400">{t('characters.promptLabel')}</p>
              <span className="text-xs text-gray-400">
                {characterPrompt.isSystem
                  ? t(`promptConfig.templateNames.${characterPrompt.templateName}`, { defaultValue: characterPrompt.templateName })
                  : characterPrompt.templateName
                }
              </span>
            </div>
            <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
              {characterPrompt.prompt}
            </div>
          </div>
        )}

        {/* 音色提示词 */}
        <div className="mt-3 pt-3 border-t border-gray-100">
          <div className="flex items-center justify-between mb-1">
            <p className="text-xs text-gray-400">{t('characters.voicePromptLabel')}</p>
            <button
              onClick={() => onEdit(character)}
              className="text-xs text-gray-400 hover:text-gray-600"
            >
              {t('common.edit')}
            </button>
          </div>
          <div className="text-xs text-gray-500 bg-gray-50 rounded p-2 max-h-20 overflow-y-auto scrollbar-thin font-mono">
            {character.voicePrompt || t('characters.noVoicePrompt')}
          </div>

          {/* 参考音频状态指示 */}
          <div className="mt-2 flex items-center gap-2">
            {character.referenceAudioUrl ? (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-green-100 text-green-700 rounded-full text-xs">
                <Mic className="h-3 w-3" />
                {t('characters.voiceReady')}
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-gray-100 text-gray-500 rounded-full text-xs">
                <Mic className="h-3 w-3" />
                {t('characters.voiceNotGenerated')}
              </span>
            )}

            {/* 上传音频按钮 */}
            <button
              onClick={() => onUploadAudio(character.id)}
              disabled={uploadingAudioId === character.id}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-100 hover:bg-blue-200 text-blue-700 rounded-full text-xs transition-colors disabled:opacity-50"
              title={t('characters.uploadAudio')}
            >
              {uploadingAudioId === character.id ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Music className="h-3 w-3" />
              )}
              <span>{t('characters.uploadAudio')}</span>
            </button>
          </div>
        </div>

        {/* 参考音频播放 */}
        {character.referenceAudioUrl && (
          <div className="mt-3">
            <button
              onClick={handlePlayAudio}
              className="flex items-center gap-1 px-3 py-1.5 bg-green-100 hover:bg-green-200 text-green-700 rounded-lg transition-colors text-xs"
            >
              {isPlayingAudio ? (
                <>
                  <Square className="h-3 w-3" />
                  <span>{t('characters.stopAudio')}</span>
                </>
              ) : (
                <>
                  <Play className="h-3 w-3" />
                  <span>{t('characters.playAudio')}</span>
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}