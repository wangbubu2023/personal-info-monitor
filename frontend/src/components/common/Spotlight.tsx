import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Hash, FileText, X, Command } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { contentsApi } from '../../services/contents';

interface SpotlightProps {
  isOpen: boolean;
  onClose: () => void;
}

interface SearchResult {
  id: string;
  title: string;
  source_name: string;
  content_type: string;
}

const Spotlight: React.FC<SpotlightProps> = ({ isOpen, onClose }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const navigate = useNavigate();

  const handleSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const data = await contentsApi.list({ search: q.trim(), page_size: 8, page: 1 });
      setResults(
        (data.items || []).map((item) => ({
          id: item.id,
          title: item.translated_title || item.title,
          source_name: item.source_name || '',
          content_type: item.content_type,
        })),
      );
      setSelectedIndex(0);
    } catch (err) {
      console.error('Spotlight search failed:', err);
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      handleSearch(query);
    }, 200);
    return () => clearTimeout(timer);
  }, [query, handleSearch]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (isOpen) onClose();
      }
      if (!isOpen) return;

      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % (results.length || 1));
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + (results.length || 1)) % (results.length || 1));
      }
      if (e.key === 'Enter' && results[selectedIndex]) {
        e.preventDefault();
        navigate(`/reader/${results[selectedIndex].id}`);
        onClose();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, results, selectedIndex, onClose, navigate]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[1000] flex items-start justify-center pt-[14vh] px-4">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="fixed inset-0 bg-[#293859]/45 backdrop-blur-sm"
        />

        <motion.div
          initial={{ opacity: 0, scale: 0.97, y: -16 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.97, y: -16 }}
          className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-[rgba(88,100,118,0.14)] bg-white/95 shadow-[0_24px_64px_-20px_rgba(41,56,89,0.35)] backdrop-blur-xl"
        >
          <div className="flex items-center border-b border-[rgba(88,100,118,0.1)] px-4 py-4 sm:px-5">
            <Search className="mr-3 h-5 w-5 shrink-0 text-[#586476]" />
            <input
              autoFocus
              placeholder="搜索标题与内容…（⌘K）"
              className="w-full bg-transparent text-[17px] text-[#293859] outline-none placeholder:text-[#586476]/70"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            <div className="ml-2 flex items-center gap-1 rounded-lg border border-[rgba(88,100,118,0.12)] bg-[#eef4f8] px-2 py-0.5 text-[12px] text-[#586476]">
              <Command size={10} />
              <span>K</span>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="ml-3 rounded-lg p-1.5 text-[#586476] hover:bg-[rgba(88,100,118,0.08)] hover:text-[#293859]"
            >
              <X size={20} />
            </button>
          </div>

          <div className="max-h-[58vh] overflow-y-auto p-2">
            {loading && query && (
              <div className="px-4 py-10 text-center text-[14px] text-[#586476]">搜索中…</div>
            )}

            {!loading && results.length > 0 && (
              <div className="space-y-0.5">
                <div className="px-3 py-2 text-[12px] font-semibold uppercase tracking-[0.12em] text-[#586476]">
                  结果
                </div>
                {results.map((item, index) => (
                  <div
                    key={item.id}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      navigate(`/reader/${item.id}`);
                      onClose();
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        navigate(`/reader/${item.id}`);
                        onClose();
                      }
                    }}
                    className={`flex cursor-pointer items-center gap-3 rounded-xl px-3 py-3 transition-colors ${
                      index === selectedIndex ? 'bg-[#49A8C9]/14' : 'hover:bg-[rgba(88,100,118,0.06)]'
                    }`}
                  >
                    <div
                      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${
                        index === selectedIndex
                          ? 'bg-[#49A8C9] text-white'
                          : 'border border-[rgba(88,100,118,0.1)] bg-[#eef4f8] text-[#586476]'
                      }`}
                    >
                      {item.content_type === 'x' ? <Hash size={16} /> : <FileText size={16} />}
                    </div>
                    <div className="min-w-0 flex-1 overflow-hidden">
                      <div className="truncate text-[14px] font-medium text-[#293859]">{item.title}</div>
                      <div
                        className={`truncate text-[12px] ${
                          index === selectedIndex ? 'text-[#49A8C9]' : 'text-[#586476]'
                        }`}
                      >
                        {item.source_name}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {!loading && query && results.length === 0 && (
              <div className="px-4 py-10 text-center text-[14px] text-[#586476]">没有与「{query}」匹配的结果</div>
            )}

            {!query && (
              <div className="px-4 py-10 text-center text-[14px] text-[#586476]">输入关键词，在全库中查找文章</div>
            )}
          </div>

          <div className="flex items-center justify-between border-t border-[rgba(88,100,118,0.1)] bg-[#eef4f8]/60 px-4 py-3 text-[12px] text-[#586476] sm:px-5">
            <div className="flex gap-4">
              <span className="flex items-center gap-1">
                <span className="rounded border border-[rgba(88,100,118,0.15)] bg-white px-1.5 py-0.5">↵</span>
                打开
              </span>
              <span className="flex items-center gap-1">
                <span className="rounded border border-[rgba(88,100,118,0.15)] bg-white px-1.5 py-0.5">↑↓</span>
                选择
              </span>
            </div>
            <span className="hidden sm:inline">全文检索</span>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default Spotlight;
