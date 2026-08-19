/**
 * GrabSearch — search auto-filter groups and grab movies to play.
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { Search, Film, Download, ExternalLink, Copy, Check, Loader2, X, Zap, Play } from 'lucide-react';
import { useGrabSearch, useGrabSelect, formatFileSize, GrabSearchResult, GrabSelectResponse } from '../lib/api';
import { useQueryClient } from '@tanstack/react-query';

import { useAppStore } from '../lib/store';

const MIME_BY_EXT: Record<string, string> = {
  mkv: 'video/x-matroska',
  avi: 'video/x-msvideo',
  mov: 'video/quicktime',
  webm: 'video/webm',
  mp4: 'video/mp4',
};

export default function GrabSearch() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<GrabSearchResult[]>([]);
  const [searched, setSearched] = useState(false);
  const [grabbed, setGrabbed] = useState<GrabSelectResponse | null>(null);
  const [grabbingIds, setGrabbingIds] = useState<Set<string>>(new Set());
  const [copied, setCopied] = useState(false);
  const { addToast, setPreviewFile } = useAppStore();
  const queryClient = useQueryClient();

  // Bumped on every search/clear so stale in-flight responses are dropped.
  const searchSeqRef = useRef(0);
  // Pairs the displayed results with the query + chat that produced them.
  const lastSearchRef = useRef<{ query: string; chatId?: number } | null>(null);
  const copyTimerRef = useRef<number | null>(null);

  const searchMutation = useGrabSearch();
  const selectMutation = useGrabSelect();

  // Close modal on Escape; reset copied state on open/close.
  useEffect(() => {
    setCopied(false);
    if (!grabbed) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setGrabbed(null);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [grabbed]);

  // Clear the copy-check timer on unmount.
  useEffect(() => {
    return () => {
      if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
    };
  }, []);

  const errorMessage = (err: any, fallback: string) => {
    const detail = err?.response?.data?.detail;
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join(', ');
    return detail || fallback;
  };

  const handleSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) return;
    if (q.length < 2) {
      addToast('Type at least 2 characters', 'info');
      return;
    }
    const seq = ++searchSeqRef.current;
    setSearched(true);
    setResults([]);
    setGrabbed(null);
    try {
      const data = await searchMutation.mutateAsync(q);
      if (seq !== searchSeqRef.current) return;
      setResults(data.results);
      lastSearchRef.current = { query: q, chatId: data.group_chat_id };
      if (data.results.length === 0) {
        addToast('No results found', 'info');
      }
    } catch (err: any) {
      if (seq !== searchSeqRef.current) return;
      setSearched(false);
      addToast(errorMessage(err, 'Search failed'), 'error');
    }
  }, [query, searchMutation, addToast]);

  const handleSelect = useCallback(async (item: GrabSearchResult) => {
    const itemId = `${item.msg_id}-${item.row}-${item.col}`;
    if (grabbingIds.has(itemId)) return;
    const last = lastSearchRef.current;
    if (!last) return;
    setGrabbingIds((prev) => new Set(prev).add(itemId));
    try {
      const result = await selectMutation.mutateAsync({
        query: last.query,
        row: item.row,
        col: item.col,
        msg_id: item.msg_id,
        chat_id: item.chat_id ?? last.chatId,
        group_username: item.group_username,
        file_name: item.file_name,
      });
      setGrabbed(result);
      // Refresh file list so the new file shows up
      queryClient.invalidateQueries({ queryKey: ['files'] });
      queryClient.invalidateQueries({ queryKey: ['files', 'recent'] });
      queryClient.invalidateQueries({ queryKey: ['storage'] });
      addToast('Movie grabbed!', 'success');
    } catch (err: any) {
      addToast(errorMessage(err, 'Failed to grab'), 'error');
    } finally {
      setGrabbingIds((prev) => {
        const next = new Set(prev);
        next.delete(itemId);
        return next;
      });
    }
  }, [grabbingIds, selectMutation, queryClient, addToast]);

  const handleCopyUrl = useCallback(async () => {
    if (!grabbed) return;
    try {
      await navigator.clipboard.writeText(grabbed.stream_url);
      setCopied(true);
      if (copyTimerRef.current !== null) window.clearTimeout(copyTimerRef.current);
      copyTimerRef.current = window.setTimeout(() => setCopied(false), 2000);
      addToast('URL copied!', 'success');
    } catch {
      addToast('Failed to copy', 'error');
    }
  }, [grabbed, addToast]);

  const handleWatchNow = useCallback(() => {
    if (!grabbed) return;
    const streamUrl = grabbed.stream_url;
    const ext = grabbed.name.split('.').pop()?.toLowerCase() ?? '';
    setPreviewFile({
      id: grabbed.id,
      user_id: 0,
      folder_id: null,
      file_id: grabbed.file_id,
      file_unique_id: grabbed.file_unique_id,
      file_name: grabbed.name,
      file_size: grabbed.size,
      mime_type: MIME_BY_EXT[ext] ?? 'video/mp4',
      file_type: 'video',
      duration: null,
      width: null,
      height: null,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      stream_url: streamUrl,
      thumbnail_url: null,
    });
    setGrabbed(null);
  }, [grabbed, setPreviewFile]);

  const getVlcUrl = (url: string) => {
    return 'vlc://' + url;
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !searchMutation.isPending) handleSearch();
  };

  const isGrabbing = (item: GrabSearchResult) => {
    return grabbingIds.has(`${item.msg_id}-${item.row}-${item.col}`);
  };

  // Highlight the matched query inside result titles (projectduck-style smart search).
  // Regex with 'i' flag matches against the original text, so the slice offsets are
  // always correct even for case mappings that change length (e.g. İ → i̇).
  const highlightMatch = (text: string, q: string) => {
    const needle = q.trim();
    if (!needle) return text;
    const re = new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
    const m = re.exec(text);
    if (!m) return text;
    return (
      <>
        {text.slice(0, m.index)}
        <span className="text-primary-300">{m[0]}</span>
        {text.slice(m.index + m[0].length)}
      </>
    );
  };

  const handleClear = () => {
    searchSeqRef.current++;
    lastSearchRef.current = null;
    setQuery('');
    setResults([]);
    setSearched(false);
  };

  return (
    <div className="p-6 animate-fade-in">
      {/* Search Header */}
      <div className="mb-8">
        <h2 className="text-3xl font-bold text-white mb-2">Search Movies</h2>
        <p className="text-dark-400">
          Find movies from Telegram groups and add them to your library
        </p>
      </div>

      {/* Search Bar */}
      <div className="relative mb-8 max-w-2xl">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-dark-500 pointer-events-none" />
        <input
          type="text"
          placeholder="Search movies, shows, anything..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          className="input-search w-full text-base pl-11 pr-28 py-3"
        />
        {query && (
          <button
            onClick={handleClear}
            className="absolute right-24 top-1/2 -translate-y-1/2 p-1 text-dark-500 hover:text-white transition-colors"
            title="Clear search"
          >
            <X className="w-4 h-4" />
          </button>
        )}
        <button
          onClick={handleSearch}
          disabled={!query.trim() || searchMutation.isPending}
          className="btn-primary absolute right-1.5 top-1/2 -translate-y-1/2 px-5 py-2 text-sm"
        >
          {searchMutation.isPending ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            'Search'
          )}
        </button>
      </div>

      {/* Loading skeletons */}
      {searchMutation.isPending && (
        <div className="space-y-2 max-w-2xl">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="glass-card p-4 flex items-center gap-4">
              <div className="skeleton w-12 h-12 rounded-xl shrink-0" />
              <div className="flex-1 min-w-0 space-y-2">
                <div className="skeleton h-4 w-2/3 rounded" />
                <div className="skeleton h-3 w-1/3 rounded" />
              </div>
              <div className="skeleton w-24 h-9 rounded-lg shrink-0" />
            </div>
          ))}
        </div>
      )}

      {/* Initial hint */}
      {!searchMutation.isPending && !searched && results.length === 0 && (
        <div className="max-w-2xl">
          <div className="glass-card p-8 text-center">
            <div className="w-14 h-14 rounded-2xl bg-primary-500/10 flex items-center justify-center mx-auto mb-4">
              <Film className="w-7 h-7 text-primary-400" />
            </div>
            <h3 className="text-lg font-semibold text-white mb-1">Find something to watch</h3>
            <p className="text-dark-400 text-sm max-w-sm mx-auto">
              Search a movie or show name — results come from connected Telegram groups.
              Grab a match to add it to your library.
            </p>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!searchMutation.isPending && searched && results.length === 0 && (
        <div className="text-center py-16 glass-card max-w-md mx-auto">
          <div className="w-16 h-16 rounded-2xl bg-dark-800 flex items-center justify-center mx-auto mb-5">
            <Search className="w-8 h-8 text-dark-500" />
          </div>
          <h3 className="text-lg font-semibold text-white mb-1">No results for “{query.trim()}”</h3>
          <p className="text-dark-400 text-sm">Try a different search term or check the spelling</p>
        </div>
      )}

      {/* Results */}
      {results.length > 0 && (
        <div className="space-y-2 max-w-2xl">
          <div className="flex items-center gap-2 mb-4">
            <span className="badge">
              {results.length} result{results.length > 1 ? 's' : ''}
            </span>
            <span className="text-xs text-dark-500">Click any result to grab it</span>
          </div>
          {results.map((item) => {
            const grabbing = isGrabbing(item);
            return (
              <div
                key={`${item.msg_id}-${item.row}-${item.col}`}
                className={`glass-card p-4 flex items-center gap-4 card-hover cursor-pointer group transition-opacity ${
                  grabbing ? 'opacity-60 pointer-events-none' : ''
                }`}
                onClick={() => !grabbing && handleSelect(item)}
              >
                <div className="w-12 h-12 rounded-xl bg-primary-500/10 flex items-center justify-center shrink-0 group-hover:bg-primary-500/20 transition-colors">
                  {grabbing ? (
                    <Loader2 className="w-6 h-6 animate-spin text-primary-400" />
                  ) : (
                    <Film className="w-6 h-6 text-primary-400" />
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-white font-semibold truncate group-hover:text-primary-300 transition-colors">
                    {highlightMatch(item.file_name, query)}
                  </p>
                  <p className="text-dark-500 text-sm mt-0.5 flex items-center gap-2">
                    {item.label && <span className="truncate">{item.label}</span>}
                    {item.label && <span className="shrink-0 text-dark-700">·</span>}
                    <span className="shrink-0">{item.file_size > 0 ? formatFileSize(item.file_size) : 'Unknown size'}</span>
                  </p>
                </div>
                <button
                  onClick={(e) => { e.stopPropagation(); if (!grabbing) handleSelect(item); }}
                  disabled={grabbing}
                  className="btn-primary shrink-0 px-4 py-2 text-sm flex items-center gap-2"
                >
                  {grabbing ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  Grab
                </button>
              </div>
            );
          })}
        </div>
      )}

      {/* Watch Now Modal */}
      {grabbed && (
        <div
          className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in"
          onClick={() => setGrabbed(null)}
        >
          <div
            className="glass-panel w-full max-w-lg overflow-hidden animate-scale-in"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-bold text-white flex items-center gap-2">
                  <Zap className="w-5 h-5 text-green-400" />
                  Ready to Watch
                </h3>
                <button
                  onClick={() => setGrabbed(null)}
                  className="p-1 text-dark-500 hover:text-white transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <p className="text-dark-300 text-sm mb-1">Grabbed:</p>
              <p className="text-white font-medium text-lg mb-2 truncate">{grabbed.name}</p>
              <p className="text-dark-500 text-sm mb-6">{grabbed.size > 0 ? formatFileSize(grabbed.size) : 'Unknown size'}</p>

              <div className="glass-card p-4 mb-6">
                <p className="text-dark-400 text-xs mb-2 uppercase tracking-wider font-medium">Stream URL</p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 text-xs text-primary-300 truncate bg-dark-900/50 rounded-lg px-3 py-2 border border-white/[0.04] font-mono">
                    {grabbed.stream_url}
                  </code>
                  <button
                    onClick={handleCopyUrl}
                    className="btn-icon"
                    title="Copy URL"
                  >
                    {copied ? <Check className="w-4 h-4 text-green-400" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={handleWatchNow}
                  className="btn-primary flex-1 flex items-center justify-center gap-2 py-3"
                >
                  <Play className="w-4 h-4" />
                  Watch Now
                </button>
                <a
                  href={getVlcUrl(grabbed.stream_url)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-secondary flex-1 flex items-center justify-center gap-2 py-3"
                >
                  <ExternalLink className="w-4 h-4" />
                  Watch in VLC
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
