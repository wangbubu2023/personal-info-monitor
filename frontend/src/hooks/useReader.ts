import { useState, useCallback, useEffect, useMemo } from 'react';
import { contentsApi } from '../services/contents';
import type { ReaderBlock, ReaderPayload } from '../services/contents';

function splitForReader(text: string): string[] {
  const cleaned = (text || '').replace(/\r\n/g, '\n').trim();
  if (!cleaned) return [];
  const paragraphs = cleaned.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  if (paragraphs.length > 1) return paragraphs;
  const protectedText = cleaned.replace(/\b(?:[A-Za-z]\.){2,}/g, (abbr) => abbr.replace(/\./g, '<DOT>'));
  return protectedText
    .split(/(?<=[。！？.!?])\s+/)
    .map((p) => p.replace(/<DOT>/g, '.').trim())
    .filter(Boolean);
}

function paragraphsToBlocks(paragraphs: string[]): ReaderBlock[] {
  return paragraphs
    .map((text) => text.trim())
    .filter(Boolean)
    .map<ReaderBlock>((text) => ({ type: 'paragraph', text }));
}

export const useReader = (id: string | undefined, translateRequested: boolean) => {
  const [data, setData] = useState<ReaderPayload | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [streamChunks, setStreamChunks] = useState<string[]>([]);
  const [streamTotal, setStreamTotal] = useState(0);
  const [streamTitle, setStreamTitle] = useState<string | null>(null);
  const [streamLoading, setStreamLoading] = useState(false);
  const [streamFinished, setStreamFinished] = useState(false);
  const [streamSucceeded, setStreamSucceeded] = useState(false);
  const [streamHint, setStreamHint] = useState<string | null>(null);

  const fetchReader = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res = await contentsApi.getReader(id, { translate: false });
      setData(res);
    } catch (err: any) {
      setError(err?.message || 'Failed to load content');
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    fetchReader();
  }, [fetchReader]);

  useEffect(() => {
    setStreamChunks([]);
    setStreamTotal(0);
    setStreamTitle(null);
    setStreamLoading(false);
    setStreamFinished(false);
    setStreamSucceeded(false);
    setStreamHint(null);

    if (!translateRequested || !id || !data) return;

    const controller = new AbortController();
    setStreamLoading(true);
    
    contentsApi.streamReaderTranslation(id, {
      signal: controller.signal,
      onEvent: (event) => {
        if (event.type === 'init') {
          setStreamTotal(event.paragraphs_total || 0);
          if (event.title) setStreamTitle(event.title);
        } else if (event.type === 'chunk') {
          setStreamChunks((prev) => [...prev, event.text]);
        } else if (event.type === 'done') {
          setStreamLoading(false);
          setStreamFinished(true);
          // 与后端一致：partial_fallback 仅表示部分段落回退原文，整体 translated 仍为 true
          const ok = !!event.translated;
          setStreamSucceeded(ok);
          if (event.message && event.message !== 'ok') setStreamHint(event.message);
        }
      },
    }).catch(() => {
      if (controller.signal.aborted) return;
      setStreamLoading(false);
      setStreamFinished(true);
      setStreamSucceeded(false);
      setStreamChunks([]);
    });

    return () => controller.abort();
  }, [translateRequested, id, data]);

  const displayTitle = useMemo(() => {
    if (!data) return '';
    if (!translateRequested) return data.title;
    return streamTitle?.trim() || data.translated_title || data.title;
  }, [data, translateRequested, streamTitle]);

  const displayParagraphs = useMemo(() => {
    if (!data) return [];
    if (!translateRequested || (streamFinished && !streamSucceeded)) {
      return splitForReader(data.body_raw || '');
    }
    if (streamChunks.length > 0) return streamChunks;
    return splitForReader(data.body_zh || data.body_raw || '');
  }, [data, translateRequested, streamChunks, streamFinished, streamSucceeded]);

  const displayBlocks = useMemo(() => {
    if (!data) return [];
    const mediaBlocks = (data.blocks || []).filter((block) => block.type === 'image');
    if (!translateRequested || (streamFinished && !streamSucceeded)) {
      return data.blocks?.length ? data.blocks : paragraphsToBlocks(splitForReader(data.body_raw || ''));
    }
    if (streamChunks.length > 0) return [...mediaBlocks, ...paragraphsToBlocks(streamChunks)];
    return [...mediaBlocks, ...paragraphsToBlocks(splitForReader(data.body_zh || data.body_raw || ''))];
  }, [data, translateRequested, streamChunks, streamFinished, streamSucceeded]);

  return {
    data,
    loading,
    error,
    displayTitle,
    displayParagraphs,
    displayBlocks,
    stream: {
      chunks: streamChunks,
      total: streamTotal,
      loading: streamLoading,
      finished: streamFinished,
      succeeded: streamSucceeded,
      hint: streamHint,
    }
  };
};
