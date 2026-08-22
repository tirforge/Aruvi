import { Files, Clock, PlayCircle, LogOut, HardDrive, X, Users, Zap, Shield, Search } from 'lucide-react';
import logo from '../assets/logo.png';
import { useAppStore } from '../lib/store';
import { useStorageStats, formatFileSize, useLogoutAll, useCurrentUser } from '../lib/api';
import { memo, useCallback, useState, type ComponentType } from 'react';

interface SidebarProps {
    isOpen: boolean;
    onClose: () => void;
}

function Sidebar({ isOpen, onClose }: SidebarProps) {
    // Narrow selectors: this renders on every FileBrowser render — a
    // whole-store subscription would re-render it on every store write.
    const activeSection = useAppStore((s) => s.activeSection);
    const setActiveSection = useAppStore((s) => s.setActiveSection);
    const setShowAdminPanel = useAppStore((s) => s.setShowAdminPanel);
    const { data: storage } = useStorageStats();
    const { data: user } = useCurrentUser();
    const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);
    const [showLogoutAllConfirm, setShowLogoutAllConfirm] = useState(false);
    const logoutAllMutation = useLogoutAll();

    const handleLogout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    };

    const handleLogoutAll = async () => {
        try {
            await logoutAllMutation.mutateAsync();
            handleLogout(); // Clear local session too
        } catch (error) {
            console.error('Failed to logout all', error);
            handleLogout(); // Fallback to local logout
        }
    };

    const handleNavClick = useCallback((section: 'files' | 'recent' | 'continue_watching' | 'grab') => {
        setActiveSection(section);
        if (window.innerWidth < 768) onClose(); // Close sidebar on mobile when item clicked
    }, [setActiveSection, onClose]);

    return (
        <>
            {/* Mobile Overlay */}
            <div 
                className={`fixed inset-0 bg-black/60 z-40 md:hidden backdrop-blur-sm transition-opacity duration-300 ${
                    isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
                }`}
                onClick={onClose}
            />

            <aside className={`
                w-64 bg-dark-900 border-r border-white/[0.06] flex flex-col shrink-0
                fixed inset-y-0 left-0 z-40
                transition-transform duration-300 ease-in-out shadow-2xl
                ${isOpen ? 'translate-x-0' : '-translate-x-full'}
            `}>
                {/* Logo Area */}
                <div className="p-6 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl overflow-hidden bg-dark-900 p-1 shadow-lg shadow-primary-500/20 flex items-center justify-center shrink-0">
                            <img 
                                src={logo} 
                                alt="Aruvi" 
                                className="w-full h-full object-contain" 
                            />
                        </div>
                        <span className="text-lg font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-white/70">
                            Aruvi
                        </span>
                    </div>
                    {/* Close button for mobile */}
                    <button 
                        onClick={onClose}
                        className="md:hidden p-1 text-dark-400 hover:text-white"
                    >
                        <X className="w-6 h-6" />
                    </button>
                </div>

                {/* Navigation */}
                <nav className="flex-1 px-3 space-y-1 overflow-y-auto">
                    <NavItem section="files" icon={Files} label="My Files" active={activeSection === 'files'} onClick={handleNavClick} />
                    <NavItem section="recent" icon={Clock} label="Recently Added" active={activeSection === 'recent'} onClick={handleNavClick} />
<NavItem section="continue_watching" icon={PlayCircle} label="Continue Watching" active={activeSection === 'continue_watching'} onClick={handleNavClick} />
<NavItem section="grab" icon={Search} label="Search Movies" active={activeSection === 'grab'} onClick={handleNavClick} />
                    {user?.is_admin && (
                        <button
                            onClick={() => { setShowAdminPanel(true); onClose(); }}
                            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-dark-400 hover:text-white hover:bg-white/[0.05] transition-colors"
                        >
                            <Shield className="w-5 h-5" />
                            Admin Panel
                        </button>
                    )}
                </nav>

                {/* Storage Info */}
                <div className="p-4 m-3 rounded-xl bg-dark-800/50 border border-white/[0.04]">
                    <div className="flex items-center gap-2 mb-2 text-sm text-dark-300">
                        <HardDrive className="w-4 h-4" />
                        <span>Storage</span>
                    </div>
                    {storage ? (
                        <>
                            <div className="text-xl font-bold text-white mb-1">
                                {formatFileSize(storage.total_size)}
                            </div>
                            <div className="text-xs text-primary-400">
                                Unlimited Storage <Zap className="w-3 h-3 inline-block text-primary-400" />
                            </div>
                        </>
                    ) : (
                        <div className="h-4 w-20 bg-dark-700 rounded animate-pulse" />
                    )}
                </div>

                {/* Logout */}
                <div className="p-4 border-t border-white/[0.06]">
                    <button
                        onClick={() => setShowLogoutConfirm(true)}
                        className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-dark-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
                    >
                        <LogOut className="w-5 h-5" />
                        <span className="font-medium">Logout</span>
                    </button>
                    <button
                        onClick={() => setShowLogoutAllConfirm(true)}
                        className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-dark-400 hover:text-orange-400 hover:bg-orange-500/10 transition-colors mt-1"
                    >
                        <Users className="w-5 h-5" />
                        <span className="font-medium">Logout All</span>
                    </button>
                </div>
            </aside>

            {/* Logout Modal */}
            {showLogoutConfirm && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in">
                    <div className="bg-dark-900 border border-white/10 rounded-2xl w-full max-w-sm overflow-hidden shadow-2xl animate-scale-in">
                        <div className="p-6 text-center">
                            <div className="w-12 h-12 bg-red-500/10 rounded-full flex items-center justify-center mx-auto mb-4">
                                <LogOut className="w-6 h-6 text-red-500" />
                            </div>
                            <h3 className="text-xl font-semibold text-white mb-2">Confirm Logout</h3>
                            <p className="text-dark-400 text-sm">
                                Are you sure you want to end your session?
                            </p>
                        </div>
                        <div className="p-4 border-t border-white/5 flex gap-3 bg-dark-800/50">
                            <button
                                onClick={() => setShowLogoutConfirm(false)}
                                className="flex-1 px-4 py-2 rounded-lg text-dark-300 hover:bg-white/5 transition-colors font-medium"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleLogout}
                                className="flex-1 px-4 py-2 rounded-lg bg-red-500 hover:bg-red-600 text-white font-medium transition-colors shadow-lg shadow-red-500/20"
                            >
                                Logout
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Logout All Modal */}
            {showLogoutAllConfirm && (
                <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-fade-in">
                    <div className="bg-dark-900 border border-white/10 rounded-2xl w-full max-w-sm overflow-hidden shadow-2xl animate-scale-in">
                        <div className="p-6 text-center">
                            <div className="w-12 h-12 bg-orange-500/10 rounded-full flex items-center justify-center mx-auto mb-4">
                                <Users className="w-6 h-6 text-orange-500" />
                            </div>
                            <h3 className="text-xl font-semibold text-white mb-2">Logout Everywhere</h3>
                            <p className="text-dark-400 text-sm">
                                This will end your session on <strong>all devices</strong>. Are you sure?
                            </p>
                        </div>
                        <div className="p-4 border-t border-white/5 flex gap-3 bg-dark-800/50">
                            <button
                                onClick={() => setShowLogoutAllConfirm(false)}
                                className="flex-1 px-4 py-2 rounded-lg text-dark-300 hover:bg-white/5 transition-colors font-medium"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleLogoutAll}
                                className="flex-1 px-4 py-2 rounded-lg bg-orange-500 hover:bg-orange-600 text-white font-medium transition-colors shadow-lg shadow-orange-500/20"
                                disabled={logoutAllMutation.isPending}
                            >
                                {logoutAllMutation.isPending ? 'Logging out...' : 'Logout All'}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}

type SectionId = 'files' | 'recent' | 'continue_watching' | 'grab';

// Module scope: a component defined inside Sidebar's render body is a NEW
// type on every render, so React unmounts/remounts all nav buttons whenever
// anything re-renders. Props keep it reusable and memoizable.
const NavItem = memo(function NavItem({ section, icon: Icon, label, active, onClick }: {
    section: SectionId;
    icon: ComponentType<{ className?: string }>;
    label: string;
    active: boolean;
    onClick: (section: SectionId) => void;
}) {
    return (
        <button
            onClick={() => onClick(section)}
            className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                active
                    ? 'bg-primary-600/10 text-primary-400 font-medium'
                    : 'text-dark-400 hover:text-white hover:bg-white/[0.05]'
            }`}
        >
            <Icon className="w-5 h-5" />
            {label}
        </button>
    );
});

export default memo(Sidebar);
