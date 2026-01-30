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

  // Determine probabilities based on upvotes
  const connectionsWithData = useMemo(() => {
    return currentNode.connections.map(conn => {
      const node = MOCK_NETWORK[conn.targetId];
      return { ...conn, node };
    }).filter(c => c.node);
  }, [currentNode]);

  const probabilities = useMemo(() => {
    if (connectionsWithData.length === 0) return {};

    // Simple mock probability: relative upvotes
    const totalUpvotes = connectionsWithData.reduce((sum, c) => sum + (c.node?.stats.upvotes || 0), 0);
    const probs: Record<string, number> = {};

    connectionsWithData.forEach(c => {
      if (totalUpvotes === 0) probs[c.targetId] = 1 / connectionsWithData.length;
      else probs[c.targetId] = (c.node?.stats.upvotes || 0) / totalUpvotes;
    });

    return probs;
  }, [connectionsWithData]);

  // Timer & Reveal Logic
  const [revealedCount, setRevealedCount] = useState(0);
  const DURATION = 10000; // 10 seconds per link
  const SATELLITE_COUNT = Math.min(connectionsWithData.length, 5);

  // Calculate markers for when to reveal satellites
  // Distribute them evenly over the first 80% of the timer
  const markers = useMemo(() => {
    return Array.from({ length: SATELLITE_COUNT }).map((_, i) => {
      // e.g. 5 items: 15%, 30%, 45%, 60%, 75%
      return 15 * (i + 1);
    });
  }, [SATELLITE_COUNT]);

  useEffect(() => {
    setRevealedCount(0);
  }, [currentLinkId]);

  // Background Lines
  // Calculate specific positions for the vertical list on the right
  // The list is centered vertically.
  // We want lines to go from center (50%, 50%) to the left edge of each list item.
  // List is at right-12 (48px) + w-80 (320px). Left edge is ~right-368px.
  // In screen width % (assuming 1920px), 370px is ~20%. So target X is 80%.

  const getLineCoordinates = (index: number, total: number) => {
    const centerX = '50%';
    const centerY = '50%';

    // Target X: Fixed near the list
    // Use calc for precision if possible, but line attributes need values. 
    // We'll use a safe percentage. 
    const targetX = '82%';

    // Target Y: Spread out vertically based on index
    // Spread ~10-12% per item
    const offset = (index - (total - 1) / 2) * 12;
    const targetY = `${50 + offset}%`;

    return { x1: centerX, y1: centerY, x2: targetX, y2: targetY };
  };

  return (
    <div className="relative w-full h-screen bg-[#050505] text-white overflow-hidden selection:bg-purple-500/30 font-sans">

      {/* Background Ambient Glow */}
      <div className="absolute top-[-20%] left-[-20%] w-[50%] h-[50%] bg-purple-900/10 blur-[120px] rounded-full pointer-events-none" />
      <div className="absolute bottom-[-20%] right-[-20%] w-[50%] h-[50%] bg-blue-900/10 blur-[120px] rounded-full pointer-events-none" />

      {/* SVG Tether Layer - Restored for Satellites */}
      <svg className="absolute inset-0 w-full h-full pointer-events-none z-10">
        {currentNode.connections.slice(0, 5).map((conn, index) => {
          const coords = getLineCoordinates(index, Math.min(currentNode.connections.length, 5));
          // Only show line if revealed? The user wants "faintly visible" or just "outline".
          // User said "make sure the lines are there".
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
        <LinkCard node={currentNode} />

        {/* Timer Bar */}
        <div className="w-[900px] max-w-[90vw] mt-6">
          <TimerBar
            key={currentLinkId} // Force re-mount on link change to reset timer state completely
            duration={DURATION}
            isRunning={true}
            markers={markers}
            onMarkerReached={() => {
              setRevealedCount(prev => prev + 1);
            }}
            onComplete={() => {
              // Auto-navigate to highest probability link
              // Find highest prob
              let bestId = connectionsWithData[0]?.targetId;
              let maxP = -1;
              Object.entries(probabilities).forEach(([id, p]) => {
                if (p > maxP) { maxP = p; bestId = id; }
              });
              if (bestId) setCurrentLinkId(bestId);
            }}
          />
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

      {/* The Left Wing (Rating) */}
      <div className="absolute left-12 top-1/2 -translate-y-1/2 flex flex-col items-center gap-4 z-30">
        <button
          className="group relative p-3 rounded-full hover:bg-white/10 text-neutral-400 hover:text-green-400 transition-all hover:scale-110 active:scale-90 duration-200"
          onClick={(e) => {
            const btn = e.currentTarget;
            btn.classList.add('animate-[spin_0.5s_ease-out]');
            setTimeout(() => btn.classList.remove('animate-[spin_0.5s_ease-out]'), 500);
          }}
        >
          <div className="absolute inset-0 rounded-full bg-green-500/20 scale-0 group-hover:scale-100 transition-transform duration-300" />
          <ChevronUp size={32} className="relative z-10" />
        </button>

        <div className="text-2xl font-bold font-mono tracking-tighter tabular-nums">
          <span className="animate-in slide-in-from-bottom duration-300 key={currentLinkId}">
            {currentNode.stats.upvotes - currentNode.stats.downvotes}
          </span>
        </div>

        <button
          className="group relative p-3 rounded-full hover:bg-white/10 text-neutral-400 hover:text-red-400 transition-all hover:scale-110 active:scale-90 duration-200"
          onClick={(e) => {
            const btn = e.currentTarget;
            btn.classList.add('animate-[shake_0.5s_ease-out]'); // Standard shake or wiggle
            // simplified shake manually via transform in keyframes or just scale
          }}
        >
          <div className="absolute inset-0 rounded-full bg-red-500/20 scale-0 group-hover:scale-100 transition-transform duration-300" />
          <ChevronDown size={32} className="relative z-10" />
        </button>
      </div>

      {/* The Right Wing (Satellites) */}
      <SatelliteList
        connections={currentNode.connections}
        revealedCount={revealedCount}
        probabilities={probabilities}
        onSelect={setCurrentLinkId}
      />

    </div>
  );
};
