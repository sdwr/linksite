'use client';

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { LinkSiteProvider } from '../contexts/LinkSiteContext';
import { LinkSiteState, LinkNode, SatelliteNode, ActionEvent } from '../types';

interface RealProviderProps {
  children: React.ReactNode;
}

const INITIAL_STATE: LinkSiteState = {
  featured: {
    link: { id: 'loading', title: 'Connecting...', url: '#', description: 'Waiting for stream...' },
    timeRemaining: 120,
    totalDuration: 120,
    reason: 'init'
  },
  satellites: [],
  recentActions: [],
  viewerCount: 0
};

export const RealProvider: React.FC<RealProviderProps> = ({ children }) => {
  const [state, setState] = useState<LinkSiteState>(INITIAL_STATE);
  const [isConnected, setIsConnected] = useState(false);

  // Use a ref to access current state in event handlers without dependency cycles
  // linkage: we might just use functional updates, but for complex patches ref is handy.
  // Actually, functional updates are safer.

  // Transform backend snake_case to frontend camelCase
  const transformState = useCallback((data: any) => {
    return {
      featured: data.featured ? {
        link: {
          ...data.featured.link,
          id: String(data.featured.link.id),
        },
        timeRemaining: data.featured.time_remaining_sec ?? data.featured.timeRemaining ?? 120,
        totalDuration: data.featured.total_duration_sec ?? data.featured.totalDuration ?? 120,
        reason: data.featured.reason ?? 'unknown',
      } : undefined,
      satellites: (data.satellites || []).map((s: any) => ({
        ...s,
        id: String(s.id),
        targetId: String(s.id),
      })),
      recentActions: (data.recent_actions || data.recentActions || []).map((a: any) => ({
        ...a,
        link_id: String(a.link_id),
      })),
      viewerCount: data.viewer_count ?? data.viewerCount ?? 0,
    };
  }, []);

  // Poll /api/now as primary data source (SSE through reverse proxies is unreliable)
  useEffect(() => {
    let active = true;
    let pollTimer: NodeJS.Timeout;

    const poll = async () => {
      try {
        const res = await fetch('/api/now');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        if (!active) return;

        // Transform /api/now format to match our state shape
        const featured = data.link ? {
          link: {
            id: String(data.link.id),
            title: data.link.title || '',
            url: data.link.url || '',
            feed_name: data.link.meta_json?.feed_title || '',
          },
          timeRemaining: data.timers?.seconds_remaining ?? 120,
          totalDuration: 120,
          reason: data.selection_reason || 'unknown',
        } : state.featured;

        const satellites = (data.satellites || []).map((s: any) => ({
          id: String(s.link_id),
          title: s.title || '',
          url: s.url || '',
          position: s.position || '',
          label: s.label || '',
          revealed: s.revealed ?? false,
          nominations: s.nominations ?? 0,
          targetId: String(s.link_id),
        }));

        setState({
          featured,
          satellites,
          recentActions: state.recentActions,
          viewerCount: data.viewer_count ?? 0,
        });
        setIsConnected(true);
      } catch (err) {
        console.error('Poll error:', err);
        setIsConnected(false);
      }

      if (active) {
        pollTimer = setTimeout(poll, 2000);
      }
    };

    poll();

    return () => {
      active = false;
      clearTimeout(pollTimer);
    };
  }, []);


  // --- Egress Actions ---

  const react = useCallback(async (targetId: string, value: 1 | -1) => {
    try {
      await fetch(`/api/links/${targetId}/react`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value })
      });
      // We don't update state here manually because we expect the SSE 'react' event to come back to us.
      // HOWEVER: For latency masking, optimistic updates are handled in LinkView. 
      // RealProvider acts as the "Server Source". LinkView can be optimistic on top of it.
      // OR: RealProvider implements optimistic update?
      // Let's rely on LinkView's built-in optimistic layer we just fixed.
      // RealProvider serves truth. Truth comes from SSE.
    } catch (err) {
      console.error('Failed to react:', err);
    }
  }, []);

  const nominate = useCallback(async (targetId: string) => {
    try {
      await fetch(`/api/links/${targetId}/nominate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
    } catch (err) {
      console.error('Failed to nominate:', err);
    }
  }, []);

  return (
    <LinkSiteProvider value={{ state, isConnected, react, nominate }}>
      {children}
    </LinkSiteProvider>
  );
};
