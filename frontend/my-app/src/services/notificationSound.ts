const buffers = new Map<string, AudioBuffer>();
let context: AudioContext | null = null;

function getContext(): AudioContext {
  if (!context) context = new window.AudioContext();
  return context;
}

export async function unlockNotificationAudio(): Promise<void> {
  const audio = getContext();
  if (audio.state === 'suspended') await audio.resume();
}

export async function playNotificationSound(soundId: string, volume: number): Promise<void> {
  const audio = getContext();
  if (audio.state === 'suspended') await audio.resume();
  if (audio.state !== 'running') throw new Error('浏览器限制了自动播放');
  let buffer = buffers.get(soundId);
  if (!buffer) {
    const response = await fetch(`/sounds/${encodeURIComponent(soundId)}.wav`);
    if (!response.ok) throw new Error('提示音文件无法加载');
    buffer = await audio.decodeAudioData(await response.arrayBuffer());
    buffers.set(soundId, buffer);
  }
  const source = audio.createBufferSource();
  const gain = audio.createGain();
  source.buffer = buffer;
  gain.gain.value = Math.max(0, Math.min(1, volume));
  source.connect(gain).connect(audio.destination);
  source.start();
}
