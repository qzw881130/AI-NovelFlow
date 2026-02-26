import { CheckCircle, Users } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useTranslation } from '../../../stores/i18nStore';
import type { ParsedData } from '../types';

interface CharacterImagesProps {
  parsedData: ParsedData | null;
  currentShot: number;
  novelAspectRatio: string;
  novelId: string | undefined;
  getCharacterImage: (name: string) => string | undefined;
  onRegenerateCharacter: (name: string) => void;
  aspectStyle: React.CSSProperties;
}

/**
 * 人设图片组件
 */
export function CharacterImages({
  parsedData,
  currentShot,
  novelAspectRatio,
  novelId,
  getCharacterImage,
  onRegenerateCharacter,
  aspectStyle,
}: CharacterImagesProps) {
  const { t } = useTranslation();

  const currentShotData = parsedData?.shots?.[currentShot - 1];
  const currentShotCharacters = currentShotData?.characters || [];

  const sortedCharacters = [...(parsedData?.characters || [])].sort((a: string, b: string) => {
    const aInShot = currentShotCharacters.includes(a);
    const bInShot = currentShotCharacters.includes(b);
    if (aInShot && !bInShot) return -1;
    if (!aInShot && bInShot) return 1;
    return 0;
  });

  return (
    <div className="card">
      <div className="flex justify-between items-center mb-4">
        <h3 className="font-semibold text-gray-900">
          {t('chapterGenerate.characterImages')}
          <span className="text-xs font-normal text-gray-500 ml-2">
            ({novelAspectRatio || '16:9'})
          </span>
        </h3>
        <Link 
          to={`/characters?novel=${novelId}`}
          className="text-sm text-blue-600 hover:text-blue-700 hover:underline flex items-center gap-1"
        >
          {t('chapterGenerate.aiGenerateCharacter')}
        </Link>
      </div>
      <div className="flex gap-4 flex-wrap">
        {sortedCharacters.length > 0 ? (
          sortedCharacters.map((name: string, idx: number) => {
            const imageUrl = getCharacterImage(name);
            const isInCurrentShot = currentShotCharacters.includes(name);

            return (
              <div key={idx} className={`text-center relative ${isInCurrentShot ? 'order-first' : ''}`}>
                <div 
                  className={`rounded-xl bg-gradient-to-br from-blue-400 to-purple-500 flex items-center justify-center mb-2 overflow-hidden relative ${
                    isInCurrentShot ? 'ring-2 ring-green-500 ring-offset-2' : ''
                  }`}
                  style={aspectStyle}
                >
                  {imageUrl ? (
                    <img src={imageUrl} alt={name} className="w-full h-full object-cover" />
                  ) : (
                    <Users className="h-10 w-10 text-white" />
                  )}
                  {isInCurrentShot && (
                    <div className="absolute top-1 right-1 w-5 h-5 bg-green-500 rounded-full flex items-center justify-center shadow-sm">
                      <CheckCircle className="h-3.5 w-3.5 text-white" />
                    </div>
                  )}
                </div>
                <p className="text-sm font-medium">{name}</p>
                <button 
                  onClick={() => onRegenerateCharacter(name)}
                  className="text-xs text-blue-600 hover:underline mt-1"
                >
                  {t('chapterGenerate.regenerate')}
                </button>
              </div>
            );
          })
        ) : (
          <p className="text-gray-500 text-sm py-4">{t('chapterGenerate.noCharacterImages')}</p>
        )}
      </div>
    </div>
  );
}
