import { useEffect, useState } from 'react';
import { HardDrive } from 'lucide-react';
import { healthApi, type DiskUsage } from '../api/health';
import { useTranslation } from '../stores/i18nStore';

const formatBytes = (bytes: number) => {
  const unit = bytes >= 1024 ** 4 ? 'TB' : 'GB';
  const divisor = unit === 'TB' ? 1024 ** 4 : 1024 ** 3;
  return `${(bytes / divisor).toFixed(1)} ${unit}`;
};

export default function SidebarDiskUsage() {
  const { t } = useTranslation();
  const [disks, setDisks] = useState<DiskUsage[]>([]);
  const [error, setError] = useState(false);
  const totalBytes = disks.reduce((sum, disk) => sum + disk.total_bytes, 0);
  const usedBytes = disks.reduce((sum, disk) => sum + disk.used_bytes, 0);
  const usedPercent = totalBytes > 0 ? (usedBytes / totalBytes * 100).toFixed(1) : '0.0';

  useEffect(() => {
    let controller: AbortController | undefined;
    const refresh = async () => {
      controller?.abort();
      const request = new AbortController();
      controller = request;
      try {
        setDisks(await healthApi.getDisks(request.signal));
        setError(false);
      } catch {
        if (request.signal.aborted) return;
        setDisks([]);
        setError(true);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 60_000);
    return () => {
      window.clearInterval(timer);
      controller?.abort();
    };
  }, []);

  return (
    <section aria-label={t('nav.diskUsage')} className="rounded-lg border border-gray-200 bg-gray-50 p-2.5 text-xs">
      <div className="mb-2 flex items-center gap-1.5 font-semibold text-gray-700">
        <HardDrive className="h-4 w-4 text-gray-500" aria-hidden="true" />
        {t('nav.diskUsage')}
      </div>
      {error ? <p className="text-gray-500">{t('nav.diskUnavailable')}</p> : disks.length === 0 ? (
        <p className="text-gray-500">{t('nav.diskLoading')}</p>
      ) : (
        <div className="space-y-2.5">
          <p className="border-b border-gray-200 pb-2 text-[11px] text-gray-600">
            <span className="font-medium">{t('nav.diskTotal')}</span> · {t('nav.diskUsed')} {formatBytes(usedBytes)} / {formatBytes(totalBytes)} · {usedPercent}%
          </p>
          {disks.map((disk) => (
            <div key={disk.mount_point} title={disk.mount_point}>
              <div className="mb-1 flex items-center justify-between gap-1 text-gray-700">
                <span className="min-w-0 truncate font-medium">{disk.name}</span>
                <span className="shrink-0 tabular-nums">{disk.used_percent}%</span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-gray-200" role="progressbar" aria-label={disk.name} aria-valuenow={disk.used_percent} aria-valuemin={0} aria-valuemax={100}>
                <div
                  className={`h-full rounded-full ${disk.used_percent >= 95 ? 'bg-red-500' : disk.used_percent >= 85 ? 'bg-amber-500' : 'bg-blue-500'}`}
                  style={{ width: `${Math.min(100, Math.max(0, disk.used_percent))}%` }}
                />
              </div>
              <p className="mt-1 text-[11px] tabular-nums text-gray-500">
                {t('nav.diskUsed')} {formatBytes(disk.used_bytes)} / {formatBytes(disk.total_bytes)}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
