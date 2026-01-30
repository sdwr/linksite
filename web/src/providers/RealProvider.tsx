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

  useEffect(() => {
    let evtSource: EventSource | null = null;
    let reconnectTimer: NodeJS.Timeout;

    const connect = () => {
      // In dev mode, Next.js rewrites /api to the FastAPI backend (usually port 8000)
      // Ensure 'next.config.js' or setup proxy is configured. 
      // Assuming relative path works via Next.js proxy.
      const url = '/api/stream';
      console.log('Connecting to SSE:', url);

      evtSource = new EventSource(url);

      evtSource.onopen = () => {
        console.log('SSE Connected');
        setIsConnected(true);
      };

      evtSource.onerror = (err) => {
        console.error('SSE Error:', err);
        setIsConnected(false);
        evtSource?.close();
        // Retry logic
        reconnectTimer = setTimeout(connect, 3000);
      };

      // --- Event Handlers ---

      evtSource.addEventListener('state', (e) => {
        try {
          const data = JSON.parse(e.data);
          // Assuming data matches LinkSiteState structure roughly
          // We might need to validate or transform based on backend DTOs vs frontend types
          setState(data);
        } catch (err) {
          console.error('Error parsing state event:', err);
        }
      });

      evtSource.addEventListener('react', (e) => {
        try {
          const action = JSON.parse(e.data) as ActionEvent; // has LinkId, Value, UserId...

          setState(prev => {
            // 1. Update Time if applies to current link
            let newTime = prev.featured.timeRemaining;
            if (action.link_id === prev.featured.link.id && action.value) {
              // Backend logic mirrors this: +10s / -5s (or whatever contract says)
              // We replicate it for immediate feedback consistency if we didn't receive a 'state' update yet
              const delta = action.value === 1 ? 10 : -5;
              newTime = Math.max(0, newTime + delta);
            }

            return {
              ...prev,
              featured: {
                ...prev.featured,
                timeRemaining: newTime
              },
              recentActions: [action, ...prev.recentActions].slice(0, 50)
            };
          });
        } catch (err) {
          console.error('Error parsing react event:', err);
        }
      });

      evtSource.addEventListener('nominate', (e) => {
        try {
          const action = JSON.parse(e.data) as ActionEvent;

          setState(prev => {
            // Update satellite counts
            const newSatellites = prev.satellites.map(s => {
              if (s.id === action.link_id) {
                return { ...s, nominations: (s.nominations || 0) + 1 };
              }
              return s;
            });

            return {
              ...prev,
              satellites: newSatellites,
              recentActions: [action, ...prev.recentActions].slice(0, 50)
            };
          });
        } catch (err) {
          console.error('Error parsing nominate event:', err);
        }
      });

      evtSource.addEventListener('rotation', (e) => {
        try {
          // Backend sends: { new_link: LinkNode, reason: string }
          const data = JSON.parse(e.data);
          const newLink = data.new_link as LinkNode;
          const reason = data.reason;

          setState(prev => ({
            ...prev,
            featured: {
              ...prev.featured,
              link: newLink,
              timeRemaining: prev.featured.totalDuration, // Reset timer? Or does backend send duration?
              // Ideally we verify if backend sends duration in rotation event or we just default.
              // Assuming reset to default for now or wait for state update.
              reason: reason
            }
          }));
        } catch (err) {
          console.error('Error parsing rotation event:', err);
        }
      });
    };

    connect();

    return () => {
      evtSource?.close();
      clearTimeout(reconnectTimer);
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
