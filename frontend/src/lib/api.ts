/**
* API client and hooks for TelePlay backend.
*/
import axios from 'axios';
import { useSyncExternalStore } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

// Token store shared across media/thumbnail <img> srcs.
//
// Plain <img src="...?token=..."> elements capture the token at render time.
// If the token is rotated mid-session (401-driven refresh, multi-tab), every
// render-detached <img> keeps pointing at the stale token and 401s forever —
// react-query refetches won't change a component's output if it read the token
// directly. `useAccessToken` subscribes to both the in-tab custom event (fired
// by the refresh interceptor) and the `storage` event (another tab refreshed),
// so any component that builds a tokenized URL re-renders with the fresh token.
export function useAccessToken(): string {
    return useSyncExternalStore(
        (onStoreChange) => {
            window.addEventListener('storage', onStoreChange);
            window.addEventListener('access_token_changed', onStoreChange);
            return () => {
                window.removeEventListener('storage', onStoreChange);
                window.removeEventListener('access_token_changed', onStoreChange);
            };
        },
        () => localStorage.getItem('access_token') || '',
    );
}

const setStoredAccessToken = (token: string) => {
    localStorage.setItem('access_token', token);
    window.dispatchEvent(new CustomEvent('access_token_changed'));
};

// Types
export interface User {
id: number;
telegram_id: number;
username: string | null;
first_name: string | null;
last_name: string | null;
is_admin: boolean;
created_at: string;
last_active: string;
}

export interface AdminUser extends User {
file_count: number;
folder_count: number;
storage_bytes: number;
}

export interface AdminStats {
total_users: number;
total_files: number;
total_folders: number;
total_storage_bytes: number;
active_today: number;
}

export interface Folder {
id: number;
name: string;
parent_id: number | null;
user_id: number;
created_at: string;
updated_at: string;
file_count: number;
children?: Folder[];
}

export interface TelegramFile {
id: number;
user_id: number;
folder_id: number | null;
file_id: string;
file_unique_id: string;
file_name: string;
file_size: number;
mime_type: string | null;
file_type: 'video' | 'audio' | 'document' | 'image';
duration: number | null;
width: number | null;
height: number | null;
created_at: string;
updated_at: string;
stream_url: string;
thumbnail_url: string | null;
last_pos?: number;
public_hash?: string;
public_stream_url?: string;
}

export interface FileListResponse {
files: TelegramFile[];
total: number;
page: number;
per_page: number;
}

export interface BotInfo {
username: string;
name?: string;
server_version: string;
}

export interface LoginCodeResponse {
code: string;
expires_at: string;
}

export interface StorageStats {
total_size: number;
limit: number;
}

export interface AuthResponse {
access_token: string;
refresh_token: string;
user: User;
}
export interface PendingCodeResponse {
detail: string;
status: string;
}
export type CodeVerificationResponse = AuthResponse | PendingCodeResponse;

// API client — use runtime config (set by index.html) or fallback to /api
const API_BASE = (window as any).__BACKEND_URL__ || '';
export const api = axios.create({
baseURL: API_BASE + '/api',
});

// Add auth token to requests
api.interceptors.request.use((config) => {
const token = localStorage.getItem('access_token');
if (token) {
config.headers.Authorization = `Bearer ${token}`;
}
return config;
});

// Queue for failed requests during token refresh
let isRefreshing = false;
let failedQueue: Array<{
resolve: (token: string) => void;
reject: (error: any) => void;
}> = [];

const processQueue = (error: any, token: string | null = null) => {
failedQueue.forEach((prom) => {
if (error) {
prom.reject(error);
} else {
prom.resolve(token!);
}
});

failedQueue = [];
};

// Handle 401 and 429 errors
api.interceptors.response.use(
(response) => response,
async (error) => {
const originalRequest = error.config;

if (error.response?.status === 401 && !originalRequest._retry) {
if (originalRequest.url.includes('/auth/refresh')) {
// Refresh token itself failed/expired - clear everything
localStorage.removeItem('access_token');
localStorage.removeItem('refresh_token');
localStorage.removeItem('user');
delete api.defaults.headers.common['Authorization'];
window.location.href = '/login';
return Promise.reject(error);
}

if (isRefreshing) {
  return new Promise(function (resolve, reject) {
    failedQueue.push({ resolve, reject });
  })
  .then((token) => {
    // Mark the retry so a second 401 (e.g. authz denial) can't kick off
    // another refresh and rotate the refresh token in a loop.
    originalRequest._retry = true;
    originalRequest.headers['Authorization'] = 'Bearer ' + token;
    return api(originalRequest);
  })
  .catch((err) => {
    return Promise.reject(err);
  });
}

originalRequest._retry = true;
isRefreshing = true;

let refreshToken: string | null = null;

try {
refreshToken = localStorage.getItem('refresh_token');
if (!refreshToken) {
throw new Error('No refresh token available');
}

const { data } = await axios.post(API_BASE + '/api/auth/refresh', {
refresh_token: refreshToken,
});

const { access_token, refresh_token } = data;

setStoredAccessToken(access_token);
localStorage.setItem('refresh_token', refresh_token);

api.defaults.headers.common['Authorization'] = 'Bearer ' + access_token;
originalRequest.headers['Authorization'] = 'Bearer ' + access_token;

processQueue(null, access_token);
return api(originalRequest);
} catch (err) {
// Multi-tab race: another tab rotated the refresh token while this
// attempt was in flight - retry once with the current storage value.
const currentRefreshToken = localStorage.getItem('refresh_token');
if (currentRefreshToken && currentRefreshToken !== refreshToken && !originalRequest._retryRefresh) {
originalRequest._retryRefresh = true;
try {
const { data } = await axios.post(API_BASE + '/api/auth/refresh', {
refresh_token: currentRefreshToken,
});
const { access_token, refresh_token: rotatedToken } = data;
setStoredAccessToken(access_token);
localStorage.setItem('refresh_token', rotatedToken);
api.defaults.headers.common['Authorization'] = 'Bearer ' + access_token;
originalRequest.headers['Authorization'] = 'Bearer ' + access_token;
processQueue(null, access_token);
return api(originalRequest);
} catch {
// Retry also failed - fall through to hard logout below.
}
}

processQueue(err, null);
delete api.defaults.headers.common['Authorization'];
localStorage.removeItem('access_token');
localStorage.removeItem('refresh_token');
localStorage.removeItem('user');
window.location.href = '/login';
return Promise.reject(err);
} finally {
isRefreshing = false;
}
} else if (error.response?.status === 429) {
console.log('[API] 429 Too Many Requests - rate limited');
error.message = 'Too many requests. Please wait a moment and try again.';
}

return Promise.reject(error);
}
);

// ============== Auth Hooks ==============

export const useCurrentUser = () => {
return useQuery({
queryKey: ['currentUser'],
queryFn: async () => {
const { data } = await api.get<User>('/auth/me');
return data;
},
retry: 2,
retryDelay: 1000,
});
};

export const useLoginWithCode = () => {
return useMutation({
mutationFn: async (code: string) => {
const { data } = await api.post<CodeVerificationResponse>('/auth/code', { code });
return data;
},
});
};

export const useLogoutAll = () => {
return useMutation({
mutationFn: async () => {
await api.post('/auth/logout-all');
},
});
};

export const useBotInfo = () => {
return useQuery({
queryKey: ['botInfo'],
queryFn: async () => {
const { data } = await api.get<BotInfo>('/auth/bot/info');
return data;
},
staleTime: Infinity, // Bot info doesn't change during session
});
};

export const useGenerateLoginCode = () => {
return useMutation({
mutationFn: async () => {
const { data } = await api.post<LoginCodeResponse>('/auth/generate-code');
return data;
},
});
};

export const useVerifyLoginCode = () => {
return useMutation({
mutationFn: async (code: string) => {
const { data } = await api.post<CodeVerificationResponse>('/auth/verify-code', { code });
return data;
},
});
};

// ============== Files Hooks ==============

export const getFileDownloadToken = async (fileId: number): Promise<string> => {
    const { data } = await api.post<{ token: string }>(`/files/${fileId}/download-token`);
    return data.token;
};

// ============== Subtitles ==============

export interface SubtitleCandidate {
    provider: string;
    id: string;
    download_id?: number;
    name: string;
    language: string;
    language_name: string;
    score: number;
    format: string;
    matches: string[];
}

export interface SubtitleSearchResponse {
    file_id: number;
    language: string;
    providers: string[];
    guessed: {
        type: 'movie' | 'episode';
        title: string;
        season?: number | null;
        episode?: number | number[] | null;
        year?: number | null;
    };
    subtitles: SubtitleCandidate[];
}

export const searchInternetSubtitles = async (fileId: number, language = 'en'): Promise<SubtitleSearchResponse> => {
    const { data } = await api.get<SubtitleSearchResponse>('/subtitles/search', { params: { file_id: fileId, language } });
    return data;
};

export const fetchSubtitleContent = async (
    fileId: number,
    provider: string,
    subtitleId: string,
    downloadId?: number,
    language = 'en',
): Promise<{ provider: string; layer_id: string; format: string; text: string }> => {
    const { data } = await api.get<{ provider: string; layer_id: string; format: string; text: string }>(
        '/subtitles/content',
        { params: { file_id: fileId, provider, subtitle_id: subtitleId, download_id: downloadId, language } },
    );
    return data;
};export const useFiles = (folderId?: number | null, fileType?: string, search?: string, page = 1) => {
return useQuery({
queryKey: ['files', folderId, fileType, search, page],
queryFn: async () => {
const params: Record<string, any> = {};
if (folderId != null) params.folder_id = folderId;
if (fileType) params.file_type = fileType;
if (search) params.search = search;
params.page = page;
params.per_page = 50; // Load 50 files per page
const { data } = await api.get<FileListResponse>('/files', { params });
return data;
},
staleTime: 30000, // Keep data fresh for 30s to avoid over-fetching
});
};

export const useFile = (fileId: number) => {
return useQuery({
queryKey: ['file', fileId],
queryFn: async () => {
const { data } = await api.get<TelegramFile>(`/files/${fileId}`);
return data;
},
enabled: !!fileId,
staleTime: 30000,
refetchOnWindowFocus: false,
});
};

export const useUpdateFile = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ id, folder_id, ...data }: { id: number; file_name?: string; folder_id?: number | null }) => {
// Backend treats null as "not provided"; 0 means root folder.
const payload = { ...data, ...(folder_id !== undefined ? { folder_id: folder_id ?? 0 } : {}) };
const { data: result } = await api.patch<TelegramFile>(`/files/${id}`, payload);
return result;
},
onSuccess: () => {
// Invalidate both files and folders to ensure UI updates for moves
queryClient.invalidateQueries({ queryKey: ['files'] });
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
},
});
};

export const useDeleteFile = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (id: number) => {
await api.delete(`/files/${id}`);
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['files'] });
},
});
};

export const useDeleteFiles = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (ids: number[]) => {
await api.post('/files/batch-delete', ids);
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['files'] });
queryClient.invalidateQueries({ queryKey: ['folders'] }); // Files might be inside folders affecting counts
queryClient.invalidateQueries({ queryKey: ['storage'] });
},
});
};

export const useMoveFiles = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ ids, folderId }: { ids: number[]; folderId: number | null }) => {
await api.post('/files/batch-move', { ids, folder_id: folderId });
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['files'] });
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
},
});
};

export const useRecentFiles = (limit = 20) => {
return useQuery<FileListResponse>({
queryKey: ['files', 'recent', limit],
queryFn: async () => {
const { data } = await api.get<FileListResponse>('/files/recent', { params: { limit } });
return data;
},
});
};

export const useContinueWatching = (limit = 20) => {
return useQuery<FileListResponse>({
queryKey: ['files', 'continue-watching', limit],
queryFn: async () => {
const { data } = await api.get<FileListResponse>('/files/continue-watching', { params: { limit } });
return data;
},
});
};

export const useStorageStats = () => {
return useQuery<StorageStats>({
queryKey: ['storage'],
queryFn: async () => {
const { data } = await api.get<StorageStats>('/files/storage');
return data;
},
staleTime: 60000,
});
};

export const useUpdateProgress = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ fileId, position, duration }: { fileId: number; position: number; duration?: number }) => {
await api.post(`/files/${fileId}/progress`, { position, duration });
},
onSuccess: (_data, { fileId, position, duration }) => {
// Update caches in place instead of invalidating: progress is posted every
// ~10s during playback, so a refetch of every continue-watching card on
// each beat would hammer the backend. Mutate the cached resume point and
// reorder the continue-watching list (backend sorts by updated_at DESC) so
// percentages move live while the user watches. A finished movie
// (position >= duration → backend flips completed=True) is removed from
// continue-watching exactly as the query filter would.
queryClient.setQueryData<TelegramFile>(['file', fileId], (old) => {
if (!old) return old;
return { ...old, last_pos: position, ...(duration ? { duration } : {}) };
});
const finished = !!duration && position >= duration;
const updated = { last_pos: position, ...(duration ? { duration } : {}) } as const;
queryClient.setQueriesData<FileListResponse>({ queryKey: ['files', 'continue-watching'] }, (old) => {
if (!old) return old;
const { files: original } = old;
if (!original?.length) return old;
if (finished) {
const files = original.filter((f) => f.id !== fileId);
return files.length === original.length ? old : { ...old, files };
}
const others = original.filter((f) => f.id !== fileId);
const existing = original.find((f) => f.id === fileId);
if (!existing) return old; // file isn't in continue-watching — nothing to reorder
return { ...old, files: [{ ...existing, ...updated }, ...others] };
});
// The main file grid and the "recently added" list also render progress
// bars from last_pos — patch those entries in place too (order unchanged).
queryClient.setQueriesData<FileListResponse>({ queryKey: ['files'] }, (old) => {
if (!old?.files?.length) return old;
if (!old.files.some((f) => f.id === fileId)) return old;
return { ...old, files: old.files.map((f) => (f.id === fileId ? { ...f, ...updated } : f)) };
});
},
});
};

// ============== Folders Hooks ==============

export const useMoveFolders = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ ids, folderId }: { ids: number[]; folderId: number | null }) => {
await api.post('/folders/batch-move', { ids, folder_id: folderId });
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
},
});
};

export const useFolders = (parentId?: number | null, enabled = true) => {
return useQuery({
queryKey: ['folders', parentId],
queryFn: async () => {
const params: Record<string, any> = {};
if (parentId != null) params.parent_id = parentId;
const { data } = await api.get<Folder[]>('/folders', { params });
return data;
},
staleTime: 60000, // Folders change less often
enabled,
});
};

export const useFolderTree = () => {
return useQuery({
queryKey: ['folderTree'],
queryFn: async () => {
const { data } = await api.get<Folder[]>('/folders/tree');
return data;
},
staleTime: 60000,
});
};

export const useCreateFolder = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (data: { name: string; parent_id?: number | null }) => {
const { data: result } = await api.post<Folder>('/folders', data);
return result;
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
},
});
};

export const useUpdateFolder = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ id, ...data }: { id: number; name?: string; parent_id?: number | null }) => {
const { data: result } = await api.patch<Folder>(`/folders/${id}`, data);
return result;
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
},
});
};

export const useDeleteFolder = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async ({ id, moveFilesTo }: { id: number; moveFilesTo?: number | null }) => {
const params = moveFilesTo !== undefined ? { move_files_to: moveFilesTo } : {};
await api.delete(`/folders/${id}`, { params });
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
queryClient.invalidateQueries({ queryKey: ['files'] });
},
});
};

export const useDeleteFolders = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (ids: number[]) => {
await api.post('/folders/batch-delete', ids);
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['folders'] });
queryClient.invalidateQueries({ queryKey: ['folderTree'] });
queryClient.invalidateQueries({ queryKey: ['files'] });
queryClient.invalidateQueries({ queryKey: ['storage'] });
},
});
};


// ============== Grab / Movie Search ==============

export interface GrabSearchResult {
label: string;
row: number;
col: number;
msg_id: number;
file_name: string;
file_size: number;
group_username?: string;
chat_id?: number;
}

export interface GrabSearchResponse {
results: GrabSearchResult[];
group_chat_id?: number;
}

export interface GrabSelectResponse {
name: string;
size: number;
stream_url: string;
id: number;
file_id: string;
file_unique_id: string;
}

export const useGrabSearch = () => {
return useMutation({
mutationFn: async (query: string) => {
const { data } = await api.post<GrabSearchResponse>('/grab/search', { query });
return data;
},
});
};

export const useGrabSelect = () => {
return useMutation({
mutationFn: async (params: { query: string; row: number; col: number; msg_id?: number; chat_id?: number; group_username?: string; file_name?: string }) => {
const { data } = await api.post<GrabSelectResponse>('/grab/select', params);
return data;
},
});
};

// ============== Admin Hooks ==============

export const useAdminStats = () => {
return useQuery({
queryKey: ['admin', 'stats'],
queryFn: async () => {
const { data } = await api.get<AdminStats>('/admin/stats');
return data;
},
staleTime: 30000,
});
};

export const useAdminUsers = () => {
return useQuery({
queryKey: ['admin', 'users'],
queryFn: async () => {
const { data } = await api.get<AdminUser[]>('/admin/users');
return data;
},
staleTime: 15000,
});
};

export const useToggleAdmin = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (userId: number) => {
const { data } = await api.post(`/admin/users/${userId}/toggle-admin`);
return data;
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
},
});
};

export const useDeleteUser = () => {
const queryClient = useQueryClient();
return useMutation({
mutationFn: async (userId: number) => {
await api.delete(`/admin/users/${userId}`);
},
onSuccess: () => {
queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
queryClient.invalidateQueries({ queryKey: ['admin', 'stats'] });
},
});
};

// ============== Utilities ==============

export const formatFileSize = (bytes: number | string): string => {
const value = typeof bytes === 'string' ? Number(bytes) : bytes;
if (!Number.isFinite(value)) return '—';
const units = ['B', 'KB', 'MB', 'GB', 'TB'];
let size = value;
let unitIndex = 0;
while (size >= 1024 && unitIndex < units.length - 1) {
size /= 1024;
unitIndex++;
}
return `${size.toFixed(1)} ${units[unitIndex]}`;
};

export const formatDuration = (seconds: number | null): string => {
if (!seconds) return '';
if (!Number.isFinite(seconds)) return '—';
const hours = Math.floor(seconds / 3600);
const minutes = Math.floor((seconds % 3600) / 60);
const secs = Math.floor(seconds % 60);
if (hours > 0) {
return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}
return `${minutes}:${secs.toString().padStart(2, '0')}`;
};

export const getFileIcon = (fileType: string): string => {
switch (fileType) {
case 'video': return '🎬';
case 'audio': return '🎵';
case 'image': return '🖼️';
case 'document': return '📄';
default: return '📎';
}
};
