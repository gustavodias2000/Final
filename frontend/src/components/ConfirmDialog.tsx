import { useCallback, useEffect, useId, useRef, useState, type ReactElement } from "react";
import { AlertTriangle, CircleHelp } from "lucide-react";

import "./confirm-dialog.css";

export type ConfirmOptions = {
  title: string;
  message: string;
  // Rótulo que diz o que acontece ("Aprovar 12 itens"); nunca um "OK" genérico.
  confirmLabel: string;
  cancelLabel?: string;
  // "danger": ação destrutiva ou irreversível. Botão vermelho e foco inicial no Cancelar.
  tone?: "danger" | "default";
};

export type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

// Confirmação própria, no lugar de window.confirm. Devolve a função que abre a
// janela (e resolve true/false) e o elemento que precisa ser renderizado na página.
export function useConfirm(): [ConfirmFn, ReactElement | null] {
  const [request, setRequest] = useState<{ id: number; options: ConfirmOptions } | null>(null);
  const resolveRef = useRef<((value: boolean) => void) | null>(null);
  const nextId = useRef(0);

  const confirm = useCallback<ConfirmFn>((options) => {
    // Um novo pedido encerra o anterior como cancelado.
    resolveRef.current?.(false);
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      nextId.current += 1;
      setRequest({ id: nextId.current, options });
    });
  }, []);

  const settle = useCallback((result: boolean) => {
    const resolve = resolveRef.current;
    resolveRef.current = null;
    setRequest(null);
    resolve?.(result);
  }, []);

  useEffect(() => () => resolveRef.current?.(false), []);

  const element = request ? <ConfirmDialog key={request.id} options={request.options} onSettle={settle} /> : null;
  return [confirm, element];
}

function ConfirmDialog({ options, onSettle }: { options: ConfirmOptions; onSettle: (result: boolean) => void }) {
  const { title, message, confirmLabel, cancelLabel = "Cancelar", tone = "default" } = options;
  const danger = tone === "danger";
  const dialogRef = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const pressedBackdrop = useRef(false);
  const settled = useRef(false);
  const id = useId();
  const titleId = `${id}-title`;
  const messageId = `${id}-message`;

  const finish = useCallback((result: boolean) => {
    if (settled.current) return;
    settled.current = true;
    onSettle(result);
  }, [onSettle]);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (!dialog.open) dialog.showModal();
    (danger ? cancelRef : confirmRef).current?.focus();
    return () => {
      if (dialog.open) dialog.close();
      // Devolve o foco a quem abriu a janela, se ele ainda estiver na tela.
      if (previous?.isConnected) previous.focus();
    };
  }, [danger]);

  return <dialog
    ref={dialogRef}
    className={`confirm-dialog${danger ? " confirm-dialog-danger" : ""}`}
    role="alertdialog"
    aria-modal="true"
    aria-labelledby={titleId}
    aria-describedby={messageId}
    // Esc dispara "cancel"; o fechamento fica com o React, que desmonta a janela.
    onCancel={(event) => { event.preventDefault(); finish(false); }}
    // Fecho inesperado (ex.: o navegador ignora o preventDefault num segundo Esc).
    onClose={() => { if (!dialogRef.current?.open) finish(false); }}
    // O conteúdo ocupa a janela inteira: um clique no próprio <dialog> é no fundo.
    // Exige que o clique comece e termine no fundo, para não fechar ao arrastar uma seleção.
    onPointerDown={(event) => { pressedBackdrop.current = event.target === event.currentTarget; }}
    // O modal nativo deixa o Tab escapar para a barra do navegador; aqui ele circula entre os dois botões.
    onKeyDown={(event) => {
      if (event.key !== "Tab") return;
      const first = cancelRef.current;
      const last = confirmRef.current;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }}
    onClick={(event) => {
      if (event.target === event.currentTarget && pressedBackdrop.current) finish(false);
      pressedBackdrop.current = false;
    }}
  >
    <div className="confirm-dialog-body">
      <span className="confirm-dialog-icon" aria-hidden="true">
        {danger ? <AlertTriangle size={18} /> : <CircleHelp size={18} />}
      </span>
      <div className="confirm-dialog-copy">
        <h2 id={titleId}>{title}</h2>
        <p id={messageId}>{message}</p>
      </div>
      <div className="confirm-dialog-actions">
        <button ref={cancelRef} type="button" className="button button-ghost" onClick={() => finish(false)}>{cancelLabel}</button>
        <button
          ref={confirmRef}
          type="button"
          className={`button ${danger ? "button-danger" : "button-primary"}`}
          onClick={() => finish(true)}
        >
          {confirmLabel}
        </button>
      </div>
    </div>
  </dialog>;
}
