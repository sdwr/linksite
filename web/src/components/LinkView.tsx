'use client';

import React, { useState, useMemo, useEffect } from 'react';
import { ChevronUp, ChevronDown, MessageSquare, Send } from 'lucide-react';
import { MOCK_NETWORK, LinkNode, Connection } from '@/data/mockData';
import { LinkCard } from './LinkCard';
import { TimerBar } from './TimerBar';
import { SatelliteList } from './SatelliteList';

export const LinkView: React.FC = () => {
  const [currentLinkId, setCurrentLinkId] = useState<string>('link-a');
  const currentNode = MOCK_NETWORK[currentLinkId];

  if (!currentNode) return <div className="text-white">Node not found</div>;

  // Determine probabilities based on upvotes + local session votes
  // We need to track local votes
  const [localVotes, setLocalVotes] = useState<Record<string, number>>({});

  const connectionsWithData = useMemo(() => {
    return currentNode.connections.map(conn => {
      const node = MOCK_NETWORK[conn.targetId];
      return { ...conn, node };
    }).filter(c => c.node);
  }, [currentNode]);

  const probabilities = useMemo(() => {
    if (connectionsWithData.length === 0) return {};

    // Calculate total including local session votes
    // Base score = upvotes. Local vote adds distinct weight (e.g. +500)
    const getScore = (id: string, base: number) => base + (localVotes[id] || 0) * 500;

    const totalScore = connectionsWithData.reduce((sum, c) => sum + getScore(c.targetId, c.node?.stats.upvotes || 0), 0);
    const probs: Record<string, number> = {};

    connectionsWithData.forEach(c => {
      const score = getScore(c.targetId, c.node?.stats.upvotes || 0);
      if (totalScore === 0) probs[c.targetId] = 1 / connectionsWithData.length;
      else probs[c.targetId] = score / totalScore;
    });

    return probs;
  }, [connectionsWithData, localVotes]);

  // Timer & Reveal Logic
  const [revealedCount, setRevealedCount] = useState(0);
  const [timeAdjustment, setTimeAdjustment] = useState<{ id: number, amountMs: number } | undefined>(undefined);
  const [transitionTargetId, setTransitionTargetId] = useState<string | null>(null);
  const [isTransitioning, setIsTransitioning] = useState(false);

  const DURATION = 10000; // 10 seconds per link
  const SATELLITE_COUNT = Math.min(connectionsWithData.length, 5);

  const transitionTo = (nextId: string) => {
    if (isTransitioning) return;
    setIsTransitioning(true);
    setTransitionTargetId(nextId);

    // Wait for exit animation (0.8s in css)
    setTimeout(() => {
      setCurrentLinkId(nextId);
      setTransitionTargetId(null);
      // New content fade in
      setTimeout(() => {
        setIsTransitioning(false);
      }, 100);
    }, 800);
  };

  // Calculate markers for when to reveal satellites
  // Distribute them evenly over the range 33% -> 85%
  const markers = useMemo(() => {
    if (SATELLITE_COUNT === 0) return [];
    const start = 33;
    const end = 85;
    const step = (end - start) / Math.max(1, SATELLITE_COUNT);

    return Array.from({ length: SATELLITE_COUNT }).map((_, i) => {
      return start + (step * i);
    });
  }, [SATELLITE_COUNT]);

  useEffect(() => {
    setRevealedCount(0);
    setLocalVotes({});
  }, [currentLinkId]);

  const handleVote = (targetId: string) => {
    setLocalVotes(prev => ({
      ...prev,
      [targetId]: (prev[targetId] || 0) + 1
    }));
  };

  const handleAdjustTime = (amountMs: number) => {
    setTimeAdjustment({ id: Date.now(), amountMs });
    // If adding time, we don't automatically hide satellites (keep them revealed)
    // If removing time, markers might be crossed in the TimerBar logic
  };

  // Background Lines
  // Calculate specific positions for the vertical list on the right
  // The list is centered vertically.
  // We want lines to go from center (50%, 50%) to the left edge of each list item.
  // List is at right-12 (48px) + w-80 (320px). Left edge is ~right-368px.
  // In screen width % (assuming 1920px), 370px is ~20%. So target X is 80%.

  const getLineCoordinates = (index: number, total: number) => {
    const centerX = '50%';
    const centerY = '50%';
    const targetX = '82%';
    const offset = (index - (total - 1) / 2) * 12;
    const targetY = `${50 + offset}%`;
    return { x1: centerX, y1: centerY, x2: targetX, y2: targetY };
  };

  return (
    <div className="relative w-full h-screen bg-[#050505] text-white overflow-hidden selection:bg-purple-500/30 font-sans">

      {/* Background Ambient Glow */}
      <div className="absolute top-[-20%] left-[-20%] w-[50%] h-[50%] bg-purple-900/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-20%] w-[50%] h-[50%] bg-blue-900/10 blur-[120px] rounded-full pointer-events-none" />

      {/* Transition Wrapper / Container */}
      <div
        className="absolute inset-0 w-full h-full"
      >
        {/* SVG Tether Layer - Restored for Satellites */}
        <svg className="absolute inset-0 w-full h-full pointer-events-none z-10 transition-opacity duration-500">
          {currentNode.connections.slice(0, 5).map((conn, index) => {
            const coords = getLineCoordinates(index, Math.min(currentNode.connections.length, 5));
            const isRevealed = index < revealedCount;
            return (
              <line
                key={conn.targetId}
                x1={coords.x1}
                y1={coords.y1}
                x2={coords.x2}
                y2={coords.y2}
                stroke="rgba(255,255,255,0.1)"
                strokeWidth={isRevealed ? "2" : "1"}
                strokeDasharray={isRevealed ? "none" : "5,5"}
                className={`transition-all duration-1000 ${isRevealed ? 'opacity-50' : 'opacity-20'}`}
              />
            );
          })}
        </svg>

        {/* Center Stage */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-20 flex flex-col items-center w-full max-w-4xl">
          <div className={`w-full transition-all duration-500 ${isTransitioning ? 'animate-slide-out-left' : 'animate-in fade-in zoom-in duration-500'}`}>
            <LinkCard node={currentNode} />
          </div>

          {/* Timer Bar + Controls */}
          <div className="w-[900px] max-w-[90vw] mt-6 flex items-center gap-4">
            {/* Reject / Subtract Time */}
            <button
              // Wait, logic in TimerBar: offset += amount.
              // effectiveElapsed = real - offset.
              // remaining = duration - effective.
              // If we want to REDUCE bar (jump forward), we need to INCREASE effective elapsed.
              // So we should DECREASE offset (if offset is "added time").
              // Current logic: offset += amount.
              // effective = real - offset.
              // So +amount DECREASES effective elapsed => ADDS TIME.
              // -amount INCREASES effective elapsed => REMOVES TIME.
              // "X reduces the bar" => remove time => pass negative.
              onClick={() => handleAdjustTime(-3000)} // Remove 3s (30%)
              className="p-3 rounded-full bg-neutral-900 border border-white/10 hover:border-red-500/50 hover:bg-neutral-800 text-neutral-400 hover:text-red-500 transition-all group"
            >
              <span className="font-bold text-xl group-active:scale-90 transition-transform block">✕</span>
            </button>

            <div className="flex-1">
              <TimerBar
                key={currentLinkId}
                duration={DURATION}
                isRunning={!isTransitioning}
                markers={markers}
                adjustment={timeAdjustment}
                onMarkerReached={() => {
                  setRevealedCount(prev => prev + 1);
                }}
                onComplete={() => {
                  // Navigate to highest probability (voted)
                  let bestId = connectionsWithData[0]?.targetId;
                  let maxP = -1;
                  Object.entries(probabilities).forEach(([id, p]) => {
                    if (p > maxP) { maxP = p; bestId = id; }
                  });
                  if (bestId) transitionTo(bestId);
                }}
              />
            </div>

            {/* Approve / Add Time */}
            <button
              onClick={() => handleAdjustTime(10000)} // Add 10s
              className="p-3 rounded-full bg-neutral-900 border border-white/10 hover:border-green-500/50 hover:bg-neutral-800 text-neutral-400 hover:text-green-500 transition-all group"
            >
              <div className="font-bold text-xl group-active:scale-90 transition-transform block">✓</div>
            </button>
          </div>

          {/* The Underground (Comments) */}
          <div className="w-[900px] max-w-[90vw] mt-6 bg-neutral-900/80 backdrop-blur-md rounded-xl p-6 border border-white/5 animate-in fade-in slide-in-from-bottom-4 duration-700">
            <div className="flex items-center gap-2 mb-4 text-neutral-400">
              <MessageSquare size={16} />
              <span className="text-sm font-medium uppercase tracking-wider">Discussion</span>
            </div>
            <div className="space-y-3 max-h-[150px] overflow-y-auto pr-2 custom-scrollbar">
              {currentNode.comments.map((comment, idx) => (
                <div key={idx} className="text-sm group">
                  <span className="font-bold text-purple-400 mr-2">{comment.user}</span>
                  <span className="text-neutral-300 group-hover:text-white transition-colors">{comment.text}</span>
                </div>
              ))}
            </div>
            <div className="mt-4 flex gap-2">
              <input
                type="text"
                placeholder="Add a comment..."
                className="flex-1 bg-black/50 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-purple-500/50 transition-colors"
              />
              <button className="p-2 bg-white text-black rounded-lg hover:bg-neutral-200 transition-colors">
                <Send size={16} />
              </button>
            </div>
          </div>
        </div>

        {/* The Right Wing (Satellites) */}
        <SatelliteList
          connections={currentNode.connections}
          revealedCount={revealedCount}
          probabilities={probabilities}
          onSelect={handleVote}
          transitionTargetId={transitionTargetId}
        />
      </div>
    </div>
  );
};
