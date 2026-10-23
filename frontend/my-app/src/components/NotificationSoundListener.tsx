import { useEffect } from 'react';
import { notificationApi } from '../api/notifications';
import type { PageSoundConfig } from '../api/notifications';
import { playNotificationSound, unlockNotificationAudio } from '../services/notificationSound';
import { toast } from '../stores/toastStore';

/** Browser sound delivery is independent of server-side Feishu and Telegram dispatch. */
export default function NotificationSoundListener() {
  useEffect(() => {
    let active = true;
    let cursor: number | null = null;
    let polling = false;
    let pending = false;
    let sound: PageSoundConfig = { enabled: true, soundId: 'chime', volume: 0.7 };
    let warned = false;

    const play = async () => {
      try {
        await playNotificationSound(sound.soundId, sound.volume);
        pending = false;
        warned = false;
      } catch {
        pending = true;
        if (!warned) {
          toast.error('浏览器阻止了提示音，请点击页面后重试。');
          warned = true;
        }
      }
    };
    const onGesture = () => {
      void unlockNotificationAudio().then(() => {
        if (pending && sound.enabled) void play();
      }).catch(() => { /* The next user gesture may unlock audio. */ });
    };
    window.addEventListener('pointerdown', onGesture);
    window.addEventListener('keydown', onGesture);

    const poll = async () => {
      if (!active || polling) return;
      polling = true;
      try {
        if (cursor === null) {
          const config = await notificationApi.getConfig();
          if (!active) return;
          cursor = config.latestPageSoundId;
          sound = config.pageSound;
        } else {
          const result = await notificationApi.getPageSound(cursor);
          if (!active) return;
          sound = result.pageSound;
          if (result.deliveries.length) {
            cursor = result.deliveries[result.deliveries.length - 1].id;
            if (sound.enabled) await play();
          }
        }
      } catch {
        // A sound polling error must never affect any other notification channel.
      } finally {
        polling = false;
      }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 3000);
    return () => {
      active = false;
      window.clearInterval(timer);
      window.removeEventListener('pointerdown', onGesture);
      window.removeEventListener('keydown', onGesture);
    };
  }, []);
  return null;
}
