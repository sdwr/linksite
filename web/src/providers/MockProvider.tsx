'use client';

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { LinkSiteProvider } from '../contexts/LinkSiteContext';
import { LinkSiteState, LinkNode, SatelliteNode, ActionEvent } from '../types';
import { MOCK_NETWORK } from '../data/mockData';

interface MockProviderProps {
  children: React.ReactNode;
}

export const MockProvider: React.FC<MockProviderProps> = ({ children }) => {
  // --- Local State ---
  const [currentLinkId, setCurrentLinkId] = useState<string>('link-a');
  const [timeLeft, setTimeLeft] = useState(120); // Default duration
  const [totalDuration, setTotalDuration] = useState(120);
  const [localVotes, setLocalVotes] = useState<Record<string, number>>({});
  const [recentActions, setRecentActions] = useState<ActionEvent[]>([]);

  // --- Derived State ---
  const currentNode = MOCK_NETWORK[currentLinkId];

  // Map MOCK_NETWORK connections to SatelliteNode
  const satellites: SatelliteNode[] = useMemo(() => {
    if (!currentNode) return [];

    // Calculate probabilities based on votes for sorting/display if needed
    // For now just mapping data
    return currentNode.connections.slice(0, 5).map(conn => {
      const node = MOCK_NETWORK[conn.targetId];
      // Mock some stats if missing
      const nominations = localVotes[conn.targetId] || 0;

      return {
        id: node.id,
        targetId: node.id,
        title: node.title,
        url: node.url,
        description: node.description,
        position: conn.position,
        label: conn.label,
        revealed: false, // Calculated by view based on timer usually, but here state
        nominations: nominations,
        stats: node.stats,
        comments: node.comments
      } as SatelliteNode;
    });
  }, [currentNode, localVotes]);

  // --- Timer Logic ---
  useEffect(() => {
    const timer = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 0) {
          return 0;
        }

        // Auto-rotate trigger at 1 second remaining to sync with 0
        if (prev === 1) {
          handleRotation();
        }

        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [currentLinkId, localVotes]);

  const handleRotation = () => {
    // 1. Pick Winner
    const currentNode = MOCK_NETWORK[currentLinkId];
    if (!currentNode) return;

    const connections = currentNode.connections;
    let nextId = connections[0]?.targetId; // Default fallback

    // Simple vote tally logic
    let maxVotes = -1;
    connections.forEach(conn => {
      const v = localVotes[conn.targetId] || 0;
      if (v > maxVotes) {
        maxVotes = v;
        nextId = conn.targetId;
      }
    });

    // 2. Add Rotation Action
    const action: ActionEvent = {
      type: 'rotation',
      link_id: nextId,
      user_id: 'director',
      ago_sec: 0
    };
    setRecentActions(prev => [action, ...prev].slice(0, 50));

    // 3. Update State
    // In a real app, the server rotates. Here we simulate it.
    // We update immediately. The View should handle visual transition based on 'rotation' action or key change.
    setCurrentLinkId(nextId);
  };

  // Reset timer on link change
  useEffect(() => {
    setTimeLeft(120);
    setTotalDuration(120);
    setLocalVotes({});
    setRecentActions([]);
  }, [currentLinkId]);

  // --- Actions ---

  const react = useCallback(async (targetId: string, value: 1 | -1) => {
    // Modify Time
    // Modify Time
    if (targetId === currentLinkId) {
      if (value === -1) {
        // Check if this action kills the timer
        setTimeLeft(prev => {
          const newVal = prev - 5;
          if (newVal <= 0) {
            // We need to trigger rotation, but we can't call handleRotation synchronously from here 
            // comfortably if it depends on state that might be stale, 
            // but handleRotation likely reads the ref/state.
            // Actually handleRotation uses closures over state (MOCK_NETWORK, currentLinkId, localVotes).
            // But 'react' is in useCallback with currentLinkId dependency, same as handleRotation could be.
            // Let's use a timeout or effect? 
            // Or just set to 0 and let the effect trigger it? 
            // The effect only runs on interval.
            // Let's force it.
            setTimeout(handleRotation, 0);
            return 0;
          }
          return newVal;
        });
      } else {
        setTimeLeft(prev => prev + 10);
      }
      // In real backend this changes total duration or active time
    }

    // Add Action
    const action: ActionEvent = {
      type: 'react',
      link_id: targetId,
      value: value,
      ago_sec: 0,
      user_id: 'me'
    };
    setRecentActions(prev => [action, ...prev].slice(0, 50));
  }, [currentLinkId]);

  const nominate = useCallback(async (targetId: string) => {
    setLocalVotes(prev => ({
      ...prev,
      [targetId]: (prev[targetId] || 0) + 1
    }));

    const action: ActionEvent = {
      type: 'nominate',
      link_id: targetId,
      ago_sec: 0,
      user_id: 'me'
    };
    setRecentActions(prev => [action, ...prev].slice(0, 50));
  }, []);

  // --- Construct State ---
  const state: LinkSiteState = {
    featured: {
      link: currentNode as unknown as LinkNode,
      timeRemaining: timeLeft,
      totalDuration: totalDuration,
      reason: 'mock-rotation'
    },
    satellites,
    recentActions,
    viewerCount: 1
  };

  return (
    <LinkSiteProvider value={{ state, isConnected: true, react, nominate }}>
      {children}
    </LinkSiteProvider>
  );
};
