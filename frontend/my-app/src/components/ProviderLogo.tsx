import type { LLMProvider } from '../types';
import deepseek from '../assets/providers/deepseek.svg';
import openai from '../assets/providers/openai.svg';
import gemini from '../assets/providers/gemini.svg';
import anthropic from '../assets/providers/anthropic.svg';
import azure from '../assets/providers/azure.svg';
import bailian from '../assets/providers/aliyun-bailian.svg';
import ollama from '../assets/providers/ollama.svg';

// Vendored brand artwork and licenses: ../assets/providers/README.md.
const providerLogos: Record<LLMProvider, string | null> = {
  deepseek, openai, gemini, anthropic, azure,
  'aliyun-bailian': bailian,
  ollama,
  custom: null,
};

interface ProviderLogoProps {
  provider: string;
  label: string;
  className?: string;
}

export function ProviderLogo({ provider, label, className = 'h-8 w-8' }: ProviderLogoProps) {
  const src = Object.prototype.hasOwnProperty.call(providerLogos, provider)
    ? providerLogos[provider as LLMProvider]
    : null;

  return (
    <span role="img" aria-label={label} title={label} className={`inline-flex shrink-0 items-center justify-center align-middle ${className}`}>
      {src ? (
        <img src={src} alt="" aria-hidden="true" className="h-full w-full object-contain" />
      ) : (
        <span aria-hidden="true" className="flex h-full w-full items-center justify-center rounded border border-gray-300 bg-gray-100 font-mono text-xs text-gray-600">
          {provider === 'custom' ? '</>' : '?'}
        </span>
      )}
    </span>
  );
}
