import { useState, useRef, useEffect } from 'react';
import {
  Volume2,
  Upload,
  X,
  Loader2,
  Music,
  User,
  Ban,
} from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';
import { shotsApi } from '../api/shots';
import { toast } from '../stores/toastStore';

type AudioSourceType = 'none' | 'merged' | 'uploaded' | 'character';

interface AudioReferenceSelectorProps {
  novelId: string;
  chapterId: string;
  shotIndex: number;
  shotCharacters: string[];
  referenceAudioUrl?: string;
  referenceAudioType?: AudioSourceType;
  onReferenceAudioUpdate: (audioUrl: string | null) => void;
}

interface Character {
  id: string;
  name: string;
  referenceAudioUrl?: string;
}

export default function AudioReferenceSelector({
  novelId,
  chapterId,
  shotIndex,
  shotCharacters,
  referenceAudioUrl,
  referenceAudioType,
  onReferenceAudioUpdate,
}: AudioReferenceSelectorProps) {
  const { t } = useTranslation();
  const [sourceType, setSourceType] = useState<AudioSourceType>('none');
  const [isMerging, setIsMerging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selectedCharacter, setSelectedCharacter] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Initialize source type from referenceAudioType prop
  useEffect(() => {
    if (!referenceAudioUrl) {
      setSourceType('none');
      setAudioUrl(null);
      setSelectedCharacter(null);
      return;
    }

    setAudioUrl(referenceAudioUrl);

    // Use the persisted type from backend
    if (referenceAudioType && referenceAudioType !== 'none') {
      setSourceType(referenceAudioType);
    } else if (referenceAudioUrl.includes('merged_audio')) {
      setSourceType('merged');
    } else if (referenceAudioUrl.includes('reference_audio')) {
      setSourceType('uploaded');
    } else {
      setSourceType('character');
    }
  }, [referenceAudioUrl, referenceAudioType]);

  // Fetch character data to check their reference audio URLs
  useEffect(() => {
    const fetchCharacters = async () => {
      try {
        const response = await fetch(`/api/characters/?novel_id=${novelId}`);
        const result = await response.json();
        if (result.success && result.data) {
          // Filter to only characters in the shot
          const shotChars = result.data.filter((c: Character) =>
            shotCharacters.includes(c.name)
          );
          setCharacters(shotChars);

          // If type is character, find the matching character
          if (referenceAudioUrl && referenceAudioType === 'character') {
            const matchingChar = shotChars.find(
              (c: Character) => c.referenceAudioUrl === referenceAudioUrl
            );
            if (matchingChar) {
              setSelectedCharacter(matchingChar.name);
            }
          }
        }
      } catch (error) {
        console.error('Error fetching characters:', error);
      }
    };

    if (shotCharacters.length > 0) {
      fetchCharacters();
    }
  }, [novelId, shotCharacters, referenceAudioUrl, referenceAudioType]);

  // Handle source type change
  const handleSourceTypeChange = async (type: AudioSourceType) => {
    if (type === sourceType) return;

    if (type === 'none') {
      // Clear reference audio
      const result = await shotsApi.setReferenceAudio(novelId, chapterId, shotIndex, 'none');
      if (result.success) {
        setSourceType('none');
        setAudioUrl(null);
        onReferenceAudioUpdate(null);
      } else {
        toast.error(result.message || t('chapterGenerate.setAudioRefFailed') || 'Failed to set audio reference');
      }
    } else if (type === 'merged') {
      // Will trigger merge when button is clicked
      setSourceType('merged');
    } else if (type === 'uploaded') {
      // Will trigger upload when file is selected
      setSourceType('uploaded');
    } else if (type === 'character') {
      setSourceType('character');
    }
  };

  // Merge dialogue audios
  const handleMergeAudio = async () => {
    setIsMerging(true);
    try {
      const result = await shotsApi.mergeDialogueAudio(novelId, chapterId, shotIndex);
      if (result.success && result.audio_url) {
        setAudioUrl(result.audio_url);
        onReferenceAudioUpdate(result.audio_url);
        toast.success(t('chapterGenerate.mergeAudioSuccess') || 'Audio merged successfully');
      } else {
        toast.error(result.message || t('chapterGenerate.mergeAudioFailed') || 'Failed to merge audio');
      }
    } catch (error) {
      console.error('Error merging audio:', error);
      toast.error(t('chapterGenerate.mergeAudioFailed') || 'Failed to merge audio');
    } finally {
      setIsMerging(false);
    }
  };

  // Upload reference audio
  const handleUploadAudio = async (file: File) => {
    setIsUploading(true);
    try {
      const result = await shotsApi.uploadReferenceAudio(novelId, chapterId, shotIndex, file);
      if (result.success && result.audio_url) {
        setAudioUrl(result.audio_url);
        onReferenceAudioUpdate(result.audio_url);
        toast.success(t('chapterGenerate.uploadAudioSuccess') || 'Audio uploaded successfully');
      } else {
        toast.error(result.message || t('chapterGenerate.uploadAudioFailed') || 'Failed to upload audio');
      }
    } catch (error) {
      console.error('Error uploading audio:', error);
      toast.error(t('chapterGenerate.uploadAudioFailed') || 'Failed to upload audio');
    } finally {
      setIsUploading(false);
    }
  };

  // Select character voice
  const handleSelectCharacter = async (characterName: string) => {
    setSelectedCharacter(characterName);
    try {
      const result = await shotsApi.setReferenceAudio(
        novelId,
        chapterId,
        shotIndex,
        'character',
        characterName
      );
      if (result.success && result.audio_url) {
        setAudioUrl(result.audio_url);
        onReferenceAudioUpdate(result.audio_url);
      } else {
        toast.error(result.message || t('chapterGenerate.setCharacterVoiceFailed') || 'Failed to set character voice');
      }
    } catch (error) {
      console.error('Error setting character voice:', error);
      toast.error(t('chapterGenerate.setCharacterVoiceFailed') || 'Failed to set character voice');
    }
  };

  // Get characters with reference audio
  const charactersWithAudio = characters.filter((c) => c.referenceAudioUrl);

  return (
    <div className="bg-gray-800 rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-white flex items-center gap-2">
          <Volume2 className="h-5 w-5" />
          {t('chapterGenerate.audioReference') || 'Audio Reference'}
        </h3>
      </div>

      {/* Source type selector */}
      <div className="grid grid-cols-2 gap-2 mb-4">
        <button
          onClick={() => handleSourceTypeChange('none')}
          className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
            sourceType === 'none'
              ? 'bg-gray-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          <Ban className="h-4 w-4" />
          {t('chapterGenerate.audioRefNone') || 'None'}
        </button>
        <button
          onClick={() => handleSourceTypeChange('merged')}
          className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
            sourceType === 'merged'
              ? 'bg-primary-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          <Music className="h-4 w-4" />
          {t('chapterGenerate.audioRefMerged') || 'Merged Dialogue'}
        </button>
        <button
          onClick={() => handleSourceTypeChange('uploaded')}
          className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
            sourceType === 'uploaded'
              ? 'bg-primary-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          <Upload className="h-4 w-4" />
          {t('chapterGenerate.audioRefUploaded') || 'Upload File'}
        </button>
        <button
          onClick={() => handleSourceTypeChange('character')}
          disabled={charactersWithAudio.length === 0}
          className={`flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
            sourceType === 'character'
              ? 'bg-primary-600 text-white'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50 disabled:cursor-not-allowed'
          }`}
        >
          <User className="h-4 w-4" />
          {t('chapterGenerate.audioRefCharacter') || 'Character Voice'}
        </button>
      </div>

      {/* Source-specific content */}
      {sourceType === 'merged' && (
        <div className="space-y-3">
          {!audioUrl ? (
            <button
              onClick={handleMergeAudio}
              disabled={isMerging}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              {isMerging ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('chapterGenerate.mergingAudio') || 'Merging...'}
                </>
              ) : (
                <>
                  <Music className="h-4 w-4" />
                  {t('chapterGenerate.mergeDialogueAudio') || 'Merge Dialogue Audio'}
                </>
              )}
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <audio
                src={audioUrl}
                controls
                className="flex-1 h-8"
              />
              <button
                onClick={handleMergeAudio}
                disabled={isMerging}
                className="p-2 text-gray-400 hover:text-white hover:bg-gray-600 rounded transition-colors"
                title={t('chapterGenerate.regenerate') || 'Regenerate'}
              >
                {isMerging ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Music className="h-4 w-4" />
                )}
              </button>
            </div>
          )}
        </div>
      )}

      {sourceType === 'uploaded' && (
        <div className="space-y-3">
          <input
            ref={fileInputRef}
            type="file"
            accept="audio/mp3,audio/wav,audio/flac,audio/ogg,audio/mpeg"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) {
                handleUploadAudio(file);
              }
              e.target.value = '';
            }}
          />
          {!audioUrl ? (
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2 bg-primary-600 hover:bg-primary-700 text-white rounded-lg transition-colors disabled:opacity-50"
            >
              {isUploading ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {t('chapterGenerate.uploading') || 'Uploading...'}
                </>
              ) : (
                <>
                  <Upload className="h-4 w-4" />
                  {t('chapterGenerate.uploadAudio') || 'Upload Audio'}
                </>
              )}
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <audio
                src={audioUrl}
                controls
                className="flex-1 h-8"
              />
              <button
                onClick={() => fileInputRef.current?.click()}
                disabled={isUploading}
                className="p-2 text-gray-400 hover:text-white hover:bg-gray-600 rounded transition-colors"
                title={t('chapterGenerate.uploadReplaceAudio') || 'Upload Replace'}
              >
                {isUploading ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Upload className="h-4 w-4" />
                )}
              </button>
            </div>
          )}
          <p className="text-xs text-gray-500">
            {t('chapterGenerate.supportedAudioFormats') || 'Supported: MP3, WAV, FLAC, OGG (max 10MB)'}
          </p>
        </div>
      )}

      {sourceType === 'character' && (
        <div className="space-y-3">
          {charactersWithAudio.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-2">
              {t('chapterGenerate.noCharacterWithAudio') || 'No characters with voice configured in this shot'}
            </p>
          ) : (
            <div className="space-y-2">
              {charactersWithAudio.map((char) => (
                <button
                  key={char.id}
                  onClick={() => handleSelectCharacter(char.name)}
                  className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors ${
                    selectedCharacter === char.name
                      ? 'bg-primary-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  <User className="h-4 w-4" />
                  {char.name}
                </button>
              ))}
            </div>
          )}
          {selectedCharacter && audioUrl && (
            <div className="flex items-center gap-2 mt-2">
              <audio
                src={audioUrl}
                controls
                className="flex-1 h-8"
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}