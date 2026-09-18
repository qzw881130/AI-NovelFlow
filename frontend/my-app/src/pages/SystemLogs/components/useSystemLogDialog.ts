import { useEffect, type RefObject } from 'react';

export function useSystemLogDialog(ref: RefObject<HTMLDialogElement>) {
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const previousOverflow = document.body.style.overflow;
    if (!dialog.open) dialog.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      if (dialog.open) dialog.close();
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.getClientRects().length) previousFocus.focus();
    };
  }, [ref]);
}
