import { useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

export function GenerateDialog({ children, label, onClose, busy = false }: {
  children: ReactNode;
  label: string;
  onClose: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    const focused = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    // The top layer avoids the panels' container-query stacking contexts.
    dialog?.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      dialog?.close();
      document.body.style.overflow = overflow;
      if (focused?.isConnected) focused.focus();
    };
  }, []);

  return createPortal(
    <dialog ref={ref} aria-label={label} className="generate-dialog" onCancel={(event) => {
      event.preventDefault();
      if (!busy) onClose();
    }}>
      {children}
    </dialog>,
    document.body,
  );
}
