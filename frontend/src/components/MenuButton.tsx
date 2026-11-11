import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { ChevronDown, LoaderCircle } from "lucide-react";

import "./menu.css";

export type MenuEntry =
  | {
    type?: "item";
    key: string;
    label: ReactNode;
    description?: ReactNode;
    icon?: ReactNode;
    tone?: "danger";
    disabled?: boolean;
    onSelect: () => void;
  }
  | { type: "separator"; key: string };

type MenuItemEntry = Extract<MenuEntry, { onSelect: () => void }>;

const GAP = 6;
const EDGE = 8;

// Botão que abre um menu de ações (padrão "menu button" da WAI-ARIA).
// O menu usa posição fixa para não ser cortado por contêineres com overflow.
export function MenuButton({ label, icon, items, disabled, busy, className = "button button-ghost", title }: {
  label: ReactNode;
  icon?: ReactNode;
  items: MenuEntry[];
  disabled?: boolean;
  busy?: boolean;
  className?: string;
  title?: string;
}) {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const focusOnOpen = useRef<"first" | "last">("first");
  const id = useId();
  const triggerId = `${id}-trigger`;
  const menuId = `${id}-menu`;
  const actionable = items.filter((entry): entry is MenuItemEntry => entry.type !== "separator");

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  function openMenu(focus: "first" | "last") {
    focusOnOpen.current = focus;
    setOpen(true);
  }

  // Abaixo do botão, alinhado à direita dele; desliza para dentro da tela se faltar espaço.
  const place = useCallback(() => {
    const trigger = triggerRef.current;
    const menu = menuRef.current;
    if (!trigger || !menu) return;
    // Aplicado direto no elemento: precisa valer antes do foco, ainda no mesmo quadro.
    menu.style.maxHeight = "";
    const rect = trigger.getBoundingClientRect();
    const viewportWidth = document.documentElement.clientWidth;
    const { offsetWidth: width, offsetHeight: height } = menu;
    const left = Math.min(Math.max(EDGE, rect.right - width), viewportWidth - width - EDGE);
    const below = window.innerHeight - rect.bottom - GAP - EDGE;
    const above = rect.top - GAP - EDGE;
    // Com o botão perto do pé da tela, abre para cima: um menu fixo fora da tela não rola.
    const up = height > below && above > below;
    const room = up ? above : below;
    menu.dataset.side = up ? "top" : "bottom";
    menu.style.left = `${Math.max(EDGE, left)}px`;
    menu.style.top = `${up ? rect.top - GAP - Math.min(height, room) : rect.bottom + GAP}px`;
    menu.style.maxHeight = `${Math.max(120, room)}px`;
  }, []);

  useLayoutEffect(() => {
    if (!open) return;
    place();
    const target = focusOnOpen.current === "first" ? 0 : actionable.length - 1;
    itemRefs.current[target]?.focus({ preventScroll: true });
    // Só ao abrir: o foco não deve saltar quando os itens mudam com o menu aberto.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, place]);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (!menuRef.current?.contains(target) && !triggerRef.current?.contains(target)) close(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("resize", place);
      window.removeEventListener("scroll", place, true);
    };
  }, [open, close, place]);

  function focusItem(index: number) {
    const count = actionable.length;
    if (!count) return;
    itemRefs.current[(index + count) % count]?.focus();
  }

  function activate(entry: MenuItemEntry) {
    if (entry.disabled) return;
    close(true);
    entry.onSelect();
  }

  function onTriggerKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      openMenu(event.key === "ArrowDown" ? "first" : "last");
    }
  }

  function onMenuKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const current = itemRefs.current.findIndex((item) => item === document.activeElement);
    switch (event.key) {
      case "ArrowDown": event.preventDefault(); focusItem(current + 1); break;
      case "ArrowUp": event.preventDefault(); focusItem(current < 0 ? -1 : current - 1); break;
      case "Home": event.preventDefault(); focusItem(0); break;
      case "End": event.preventDefault(); focusItem(-1); break;
      case "Escape": event.preventDefault(); event.stopPropagation(); close(true); break;
      case "Tab": close(false); break;
      case "Enter":
      case " ": {
        event.preventDefault();
        const entry = actionable[current];
        if (entry) activate(entry);
        break;
      }
    }
  }

  let itemIndex = -1;
  return <>
    <button
      ref={triggerRef}
      id={triggerId}
      type="button"
      className={`${className} menu-trigger`}
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      aria-busy={busy || undefined}
      disabled={disabled}
      title={title}
      onClick={() => (open ? close(false) : openMenu("first"))}
      onKeyDown={onTriggerKeyDown}
    >
      {busy ? <LoaderCircle className="spin" size={15} aria-hidden="true" /> : icon}
      {label}
      <ChevronDown className="menu-chevron" size={14} aria-hidden="true" />
    </button>
    {open ? <div
      ref={menuRef}
      id={menuId}
      className="menu"
      role="menu"
      aria-labelledby={triggerId}
      onKeyDown={onMenuKeyDown}
    >
      {items.map((entry) => {
        if (entry.type === "separator") return <div key={entry.key} className="menu-separator" role="separator" />;
        itemIndex += 1;
        const index = itemIndex;
        const labelId = `${id}-${entry.key}-label`;
        const descriptionId = `${id}-${entry.key}-description`;
        return <button
          key={entry.key}
          ref={(element) => { itemRefs.current[index] = element; }}
          type="button"
          role="menuitem"
          tabIndex={-1}
          className={`menu-item${entry.tone === "danger" ? " menu-item-danger" : ""}`}
          aria-disabled={entry.disabled || undefined}
          aria-labelledby={labelId}
          aria-describedby={entry.description ? descriptionId : undefined}
          onClick={() => activate(entry)}
          onPointerMove={(event) => { if (document.activeElement !== event.currentTarget) event.currentTarget.focus(); }}
        >
          {entry.icon ? <span className="menu-item-icon" aria-hidden="true">{entry.icon}</span> : null}
          <span className="menu-item-text">
            <span id={labelId} className="menu-item-label">{entry.label}</span>
            {entry.description ? <span id={descriptionId} className="menu-item-description">{entry.description}</span> : null}
          </span>
        </button>;
      })}
    </div> : null}
  </>;
}
