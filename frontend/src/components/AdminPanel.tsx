import { useState, useRef } from 'react';
import { useAppStore } from '../lib/store';
import { Shield, Users, FileText, HardDrive, Trash2, ArrowLeft, Clock, Activity, UserCheck, UserX, Database } from 'lucide-react';
import { useAdminStats, useAdminUsers, useToggleAdmin, useDeleteUser, formatFileSize, AdminUser } from '../lib/api';

function formatDate(iso: string) {
    // Backend sends naive UTC datetimes; parse them as UTC (matching
    // loginCode.ts) or the clock readout shifts by the viewer's timezone.
    const normalized = /(Z|[+-]\d{2}:\d{2})$/i.test(iso) ? iso : iso + 'Z';
    const d = new Date(normalized);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function errorMessage(err: any, fallback: string) {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join(', ');
    return detail || fallback;
}

function StatCard({ icon: Icon, label, value, sub }: { icon: any; label: string; value: string; sub?: string }) {
    return (
        <div className="glass-card p-4 flex items-center gap-4">
            <div className="p-3 rounded-xl bg-primary-500/10 text-primary-400">
                <Icon className="w-5 h-5" />
            </div>
            <div>
                <p className="text-2xl font-bold text-white">{value}</p>
                <p className="text-sm text-dark-400">{label}</p>
                {sub && <p className="text-xs text-dark-500">{sub}</p>}
            </div>
        </div>
    );
}

function UserRow({ user, onToggleAdmin, onDelete, togglePending, deletePending }: { user: AdminUser; onToggleAdmin: () => void | Promise<void>; onDelete: () => void | Promise<void>; togglePending: boolean; deletePending: boolean }) {
    const [confirmDelete, setConfirmDelete] = useState(false);
    const busyRef = useRef(false);

    const runGuarded = async (fn: () => void | Promise<void>) => {
        if (busyRef.current) return;
        busyRef.current = true;
        try {
            await fn();
        } finally {
            busyRef.current = false;
        }
    };

    return (
        <div className="flex items-center justify-between p-4 bg-dark-800/50 border border-white/[0.04] rounded-xl hover:bg-dark-800 transition-colors">
            <div className="flex items-center gap-4 min-w-0 flex-1">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold shrink-0 ${user.is_admin ? 'bg-primary-500/20 text-primary-400' : 'bg-dark-700 text-dark-300'}`}>
                    {(user.first_name || user.username || '?')[0].toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <span className="text-white font-medium truncate">
                            {user.first_name || user.username || 'Unknown'}
                            {user.last_name ? ` ${user.last_name}` : ''}
                        </span>
                        {user.is_admin && (
                            <span className="text-xs px-2 py-0.5 rounded-full bg-primary-500/10 text-primary-400 border border-primary-500/20 shrink-0">
                                Admin
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-dark-500 mt-1">
                        <span>@{user.username || 'no username'}</span>
                        <span>ID: {user.telegram_id}</span>
                        <span>{formatFileSize(user.storage_bytes)}</span>
                        <span>{user.file_count} files</span>
                    </div>
                    <div className="flex items-center gap-2 text-xs text-dark-500 mt-1">
                        <Clock className="w-3 h-3" />
                        <span>Joined: {formatDate(user.created_at)}</span>
                        <span className="text-dark-600">|</span>
                        <Activity className="w-3 h-3" />
                        <span>Last: {formatDate(user.last_active)}</span>
                    </div>
                </div>
            </div>
            <div className="flex items-center gap-2 shrink-0 ml-4">
                <button
                    onClick={() => runGuarded(onToggleAdmin)}
                    disabled={togglePending || deletePending}
                    className={`p-2 rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                        user.is_admin
                            ? 'text-orange-400 hover:bg-orange-500/10'
                            : 'text-dark-400 hover:text-primary-400 hover:bg-primary-500/10'
                    }`}
                    title={user.is_admin ? 'Revoke admin' : 'Make admin'}
                >
                    {user.is_admin ? <UserX className="w-4 h-4" /> : <UserCheck className="w-4 h-4" />}
                </button>
                {confirmDelete ? (
                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => runGuarded(onDelete)}
                            disabled={togglePending || deletePending}
                            className="px-3 py-1.5 text-xs rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            {deletePending ? 'Deleting...' : 'Confirm'}
                        </button>
                        <button
                            onClick={() => setConfirmDelete(false)}
                            disabled={togglePending || deletePending}
                            className="px-3 py-1.5 text-xs rounded-lg bg-dark-700 text-dark-300 hover:text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                            Cancel
                        </button>
                    </div>
                ) : (
                    <button
                        onClick={() => setConfirmDelete(true)}
                        disabled={togglePending || deletePending}
                        className="p-2 rounded-lg text-dark-400 hover:text-red-400 hover:bg-red-500/10 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Delete user"
                    >
                        <Trash2 className="w-4 h-4" />
                    </button>
                )}
            </div>
        </div>
    );
}

export default function AdminPanel({ onBack }: { onBack: () => void }) {
    const { data: stats, isLoading: statsLoading } = useAdminStats();
    const { data: users, isLoading: usersLoading } = useAdminUsers();
    const toggleAdmin = useToggleAdmin();
    const deleteUser = useDeleteUser();
    const { addToast } = useAppStore();

    const handleToggleAdmin = async (user: AdminUser) => {
        try {
            await toggleAdmin.mutateAsync(user.id);
        } catch (error) {
            addToast(errorMessage(error, 'Failed to update admin status'), 'error');
        }
    };

    const handleDeleteUser = async (user: AdminUser) => {
        try {
            await deleteUser.mutateAsync(user.id);
        } catch (error) {
            addToast(errorMessage(error, 'Failed to delete user'), 'error');
        }
    };

    return (
        <div className="min-h-screen bg-dark-950">
            <div className="max-w-5xl mx-auto px-4 py-8">
                {/* Header */}
                <div className="flex items-center gap-4 mb-8">
                    <button
                        onClick={onBack}
                        className="p-2 rounded-lg hover:bg-white/10 text-dark-400 hover:text-white transition-colors"
                    >
                        <ArrowLeft className="w-5 h-5" />
                    </button>
                    <div>
                        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
                            <Shield className="w-6 h-6 text-primary-400" />
                            Admin Panel
                        </h1>
                        <p className="text-dark-400 text-sm">Manage users and system settings</p>
                    </div>
                </div>

                {/* Stats */}
                {statsLoading ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                        {[1, 2, 3, 4].map(i => (
                            <div key={i} className="glass-card p-4 h-24 animate-pulse" />
                        ))}
                    </div>
                ) : stats ? (
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                        <StatCard icon={Users} label="Total Users" value={String(stats.total_users)} />
                        <StatCard icon={FileText} label="Total Files" value={String(stats.total_files)} />
                        <StatCard icon={HardDrive} label="Storage Used" value={formatFileSize(stats.total_storage_bytes)} />
                        <StatCard icon={Activity} label="Active Today" value={String(stats.active_today)} sub="Last 24 hours" />
                    </div>
                ) : null}

                {/* Users */}
                <div className="glass-panel p-6">
                    <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Users className="w-5 h-5 text-primary-400" />
                        All Users
                    </h2>
                    {usersLoading ? (
                        <div className="space-y-3">
                            {[1, 2, 3].map(i => (
                                <div key={i} className="h-20 bg-dark-800/50 rounded-xl animate-pulse" />
                            ))}
                        </div>
                    ) : users && users.length > 0 ? (
                        <div className="space-y-2">
                            {users.map(u => (
                                <UserRow
                                    key={u.id}
                                    user={u}
                                    onToggleAdmin={() => handleToggleAdmin(u)}
                                    onDelete={() => handleDeleteUser(u)}
                                    togglePending={toggleAdmin.isPending}
                                    deletePending={deleteUser.isPending}
                                />
                            ))}
                        </div>
                    ) : (
                        <p className="text-dark-400 text-center py-8">No users found</p>
                    )}
                </div>

                {/* Info */}
                <div className="mt-6 glass-card p-4 flex items-start gap-3">
                    <Database className="w-5 h-5 text-dark-500 shrink-0 mt-0.5" />
                    <p className="text-xs text-dark-500">
                        AUTH_USERS in env vars auto-grants admin on registration.
                        The first user to ever use the bot also becomes admin automatically.
                        Admins can promote/demote others here.
                    </p>
                </div>
            </div>
        </div>
    );
}
