import { useCallback, useEffect, useRef } from 'react';

interface PollingOptions<T> {
  fetch: (signal: AbortSignal) => Promise<T>;
  onSuccess: (data: T) => void;
  onError?: (error: unknown) => void;
  onSettled?: () => void;
  intervalMs: number;
  timeoutMs?: number;
}

/** One request at a time, including manual refreshes; stop on unmount. */
export function createSerialPoller<T>(options: PollingOptions<T>) {
  let stopped = false;
  let inFlight: Promise<void> | null = null;
  let controller: AbortController | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const refresh = (): Promise<void> => {
    if (stopped || document.hidden) return Promise.resolve();
    if (inFlight) return inFlight;
    clearTimeout(timer);
    const request = new AbortController();
    controller = request;
    let timedOut = false;
    const deadline = setTimeout(() => {
      timedOut = true;
      request.abort();
    }, options.timeoutMs ?? 15000);

    inFlight = Promise.resolve().then(() => options.fetch(request.signal))
      .then(data => {
        if (!stopped && !request.signal.aborted) options.onSuccess(data);
      })
      .catch(error => {
        if (!stopped && (!request.signal.aborted || timedOut)) options.onError?.(error);
      })
      .finally(() => {
        clearTimeout(deadline);
        inFlight = null;
        controller = null;
        if (!stopped) {
          options.onSettled?.();
          if (!document.hidden) timer = setTimeout(refresh, options.intervalMs);
        }
      });
    return inFlight;
  };

  const visibilityChanged = () => {
    if (document.hidden) {
      clearTimeout(timer);
      controller?.abort();
    } else {
      void refresh();
    }
  };
  document.addEventListener('visibilitychange', visibilityChanged);
  void refresh();

  return {
    refresh,
    stop: () => {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
    },
  };
}

export function useSerialPolling<T>(options: PollingOptions<T>) {
  const callbacks = useRef(options);
  callbacks.current = options;
  const poller = useRef<ReturnType<typeof createSerialPoller<T>> | null>(null);

  useEffect(() => {
    const current = createSerialPoller({
      fetch: options.fetch,
      intervalMs: options.intervalMs,
      timeoutMs: options.timeoutMs,
      onSuccess: data => callbacks.current.onSuccess(data),
      onError: error => callbacks.current.onError?.(error),
      onSettled: () => callbacks.current.onSettled?.(),
    });
    poller.current = current;
    return () => {
      current.stop();
      if (poller.current === current) poller.current = null;
    };
  }, [options.fetch, options.intervalMs, options.timeoutMs]);

  return useCallback(() => poller.current?.refresh() ?? Promise.resolve(), []);
}
