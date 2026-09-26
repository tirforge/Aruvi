import { useEffect } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';
import { useAppStore } from '../lib/store';

export default function Toasts() {
    const toasts = useAppStore((s) => s.toasts);
    const removeToast = useAppStore((s) => s.removeToast);

    return (
        <div className="fixed bottom-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none" aria-live="polite">
            {toasts.map((toast) => (
                <ToastItem key={toast.id} toast={toast} onDismiss={() => removeToast(toast.id)} />
            ))}
        </div>
    );
}

function ToastItem({ toast, onDismiss }: { toast: { id: string; message: string; type: 'success' | 'error' | 'info' }; onDismiss: () => void }) {
    useEffect(() => {
        const timer = setTimeout(() => {
            onDismiss();
        }, 5000);

        return () => clearTimeout(timer);
    }, []);

    const getIcon = () => {
        const chip = 'w-8 h-8 rounded-lg flex items-center justify-center shrink-0 border';
        switch (toast.type) {
            case 'success': return <span className={`${chip} bg-green-500/15 border-green-500/25 shadow-[0_0_16px_-4px_rgba(34,197,94,0.5)]`}><CheckCircle className="w-4 h-4 text-green-400" /></span>;
            case 'error': return <span className={`${chip} bg-red-500/15 border-red-500/25 shadow-[0_0_16px_-4px_rgba(239,68,68,0.5)]`}><AlertCircle className="w-4 h-4 text-red-400" /></span>;
            default: return <span className={`${chip} bg-blue-500/15 border-blue-500/25 shadow-[0_0_16px_-4px_rgba(59,130,246,0.5)]`}><Info className="w-4 h-4 text-blue-400" /></span>;
        }
    };

    const getBgColor = () => {
         switch (toast.type) {
            case 'success': return 'border-green-500/25 border-l-2 border-l-green-400 bg-dark-900/90 shadow-green-900/20';
            case 'error': return 'border-red-500/25 border-l-2 border-l-red-400 bg-dark-900/90 shadow-red-900/20';
            default: return 'border-blue-500/25 border-l-2 border-l-blue-400 bg-dark-900/90 shadow-blue-900/20';
        }
    };

    return (
        <div className={`pointer-events-auto flex items-center gap-3 pl-4 pr-3 py-3 rounded-xl border shadow-xl backdrop-blur-md animate-slide-up sm:min-w-[300px] max-w-md ${getBgColor()}`}>
            {getIcon()}
            <p className="flex-1 text-sm font-medium text-white">{toast.message}</p>
            <button 
                onClick={onDismiss}
                className="p-1 rounded-lg hover:bg-white/10 text-dark-400 hover:text-white transition-colors"
            >
                <X className="w-4 h-4" />
            </button>
        </div>
    );
}
