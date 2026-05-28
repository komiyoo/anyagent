import { create } from "zustand";

export type ToastKind = "success" | "error" | "info";

export type StudioToast = {
  id: string;
  kind: ToastKind;
  message: string;
};

type ToastStore = {
  toasts: StudioToast[];
  dismissToast: (id: string) => void;
  showToast: (kind: ToastKind, message: string) => void;
};

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  dismissToast: (id) => set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) })),
  showToast: (kind, message) => {
    const id = crypto.randomUUID();
    set((state) => ({ toasts: [...state.toasts.slice(-3), { id, kind, message }] }));
    window.setTimeout(() => {
      set((state) => ({ toasts: state.toasts.filter((toast) => toast.id !== id) }));
    }, 3800);
  },
}));
