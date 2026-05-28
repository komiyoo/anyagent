import { X } from "lucide-react";
import { useToastStore } from "../stores/toastStore";

export function ToastViewport() {
  const { dismissToast, toasts } = useToastStore();

  return (
    <div className="toast-viewport" aria-live="polite" aria-relevant="additions">
      {toasts.map((toast) => (
        <div className={`toast ${toast.kind}`} key={toast.id} role="status">
          <span>{toast.message}</span>
          <button type="button" aria-label="Dismiss notification" onClick={() => dismissToast(toast.id)}>
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}
