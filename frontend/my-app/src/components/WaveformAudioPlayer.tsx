import { useEffect, useRef, useState } from 'react';
import { Loader2, Pause, Play, Volume2, VolumeX } from 'lucide-react';
import WaveSurfer from 'wavesurfer.js';

let activePlayer: WaveSurfer | null = null;

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const value = Math.floor(seconds);
  const minutes = Math.floor(value / 60);
  const remainder = String(value % 60).padStart(2, '0');
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}:${remainder}`
    : `${minutes}:${remainder}`;
}

interface WaveformAudioPlayerProps {
  src: string;
  label: string;
  compact?: boolean;
  className?: string;
}

export function WaveformAudioPlayer({ src, label, compact = false, className = '' }: WaveformAudioPlayerProps) {
  const observerRef = useRef<HTMLDivElement>(null);
  const waveformRef = useRef<HTMLDivElement>(null);
  const playerRef = useRef<WaveSurfer | null>(null);
  const [visible, setVisible] = useState(false);
  const [ready, setReady] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [muted, setMuted] = useState(false);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [error, setError] = useState(false);

  useEffect(() => {
    const element = observerRef.current;
    if (!element) return;
    if (typeof IntersectionObserver === 'undefined') {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) {
        setVisible(true);
        observer.disconnect();
      }
    }, { rootMargin: '200px' });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!visible || !waveformRef.current) return;
    setReady(false);
    setPlaying(false);
    setMuted(false);
    setCurrentTime(0);
    setDuration(0);
    setError(false);
    const player = WaveSurfer.create({
      container: waveformRef.current,
      url: src,
      height: compact ? 34 : 50,
      waveColor: '#a78bfa',
      progressColor: '#7c3aed',
      cursorColor: '#5b21b6',
      cursorWidth: 1,
      barWidth: 2,
      barGap: 2,
      barRadius: 2,
      normalize: true,
      dragToSeek: true,
      backend: 'MediaElement',
    });
    playerRef.current = player;
    player.on('ready', value => { setDuration(value); setReady(true); });
    player.on('timeupdate', setCurrentTime);
    player.on('play', () => {
      if (activePlayer && activePlayer !== player) activePlayer.pause();
      activePlayer = player;
      setPlaying(true);
    });
    player.on('pause', () => {
      if (activePlayer === player) activePlayer = null;
      setPlaying(false);
    });
    player.on('finish', () => {
      if (activePlayer === player) activePlayer = null;
      setPlaying(false);
    });
    player.on('error', () => { setError(true); setReady(false); });
    return () => {
      if (activePlayer === player) activePlayer = null;
      player.destroy();
      playerRef.current = null;
    };
  }, [src, visible, compact]);

  const togglePlayback = () => {
    const player = playerRef.current;
    if (player && ready) void player.playPause().catch(() => setError(true));
  };

  const seekWithKeyboard = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const player = playerRef.current;
    if (!player || !ready) return;
    const next = event.key === 'ArrowRight' ? currentTime + 5
      : event.key === 'ArrowLeft' ? currentTime - 5
      : event.key === 'Home' ? 0
      : event.key === 'End' ? duration : null;
    if (next === null) return;
    event.preventDefault();
    player.setTime(Math.max(0, Math.min(duration, next)));
  };

  return <div ref={observerRef} className={`min-w-0 rounded-lg border border-violet-100 bg-white px-2 py-1.5 ${className}`}>
    <div className="flex min-w-0 items-center gap-2">
      <button type="button" disabled={!ready || error} onClick={togglePlayback}
        aria-label={`${playing ? '暂停' : '播放'}${label}`}
        className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-violet-100 text-violet-700 hover:bg-violet-200 disabled:cursor-not-allowed disabled:opacity-50">
        {!ready && !error ? <Loader2 className="h-4 w-4 animate-spin" /> : playing ? <Pause className="h-4 w-4 fill-current" /> : <Play className="h-4 w-4 fill-current" />}
      </button>
      <div className="relative min-w-0 flex-1">
        <div ref={waveformRef} role="slider" tabIndex={ready ? 0 : -1}
          aria-label={`${label}波形，左右方向键快进或快退 5 秒`}
          aria-valuemin={0} aria-valuemax={Math.round(duration)} aria-valuenow={Math.round(currentTime)}
          onKeyDown={seekWithKeyboard} className="min-w-0 cursor-pointer rounded focus:outline-none focus:ring-2 focus:ring-violet-500" />
        {!ready && !error && <span className="pointer-events-none absolute inset-0 flex items-center justify-center text-[11px] text-gray-400">{visible ? '正在加载波形…' : '等待加载波形…'}</span>}
      </div>
      <span className="flex-none whitespace-nowrap font-mono text-[11px] tabular-nums text-gray-600">{formatTime(currentTime)} / {formatTime(duration)}</span>
      <button type="button" disabled={!ready || error} onClick={() => {
        const next = !muted;
        playerRef.current?.setMuted(next);
        setMuted(next);
      }} aria-label={`${muted ? '取消静音' : '静音'}${label}`}
        className="flex h-7 w-7 flex-none items-center justify-center rounded text-gray-500 hover:bg-gray-100 disabled:opacity-40">
        {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
      </button>
    </div>
    {error && <div className="mt-1 text-xs text-red-600">波形加载失败，可使用备用播放器。<audio controls preload="metadata" src={src} className="mt-1 h-8 w-full" /></div>}
  </div>;
}
