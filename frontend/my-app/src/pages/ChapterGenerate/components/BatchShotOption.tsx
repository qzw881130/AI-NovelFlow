import { useRef, type ButtonHTMLAttributes, type PointerEvent } from 'react';

export function BatchShotOption({ selected, onToggle, onSelectionStart, onSelectionEnter, ...props }: Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'onClick'> & {
  selected: boolean;
  onToggle: () => void;
  onSelectionStart: (event: PointerEvent<HTMLButtonElement>) => void;
  onSelectionEnter: () => void;
}) {
  const mouseSelection = useRef(false);
  return <button {...props} type="button" aria-pressed={selected}
    onPointerDown={(event) => {
      mouseSelection.current = event.pointerType === 'mouse';
      if (mouseSelection.current) onSelectionStart(event);
    }}
    onPointerEnter={(event) => {
      if (event.pointerType === 'mouse') onSelectionEnter();
    }}
    onDragStart={(event) => event.preventDefault()}
    onClick={(event) => {
      // Touch scroll must not select on pointerdown; keyboard uses native button clicks.
      if (!mouseSelection.current || event.detail === 0) onToggle();
      mouseSelection.current = false;
    }}
  />;
}
